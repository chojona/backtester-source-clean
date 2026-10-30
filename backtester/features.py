"""Streaming VWAP, ATR and levels with explicit completeness flags."""
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType


@dataclass
class VWAP:
    basis: str = "typical"
    weighted_sum: float = 0.0
    volume: float = 0.0

    def __post_init__(self):
        if self.basis not in ("typical", "close", "ohlc4"):
            raise ValueError("VWAP basis must be typical, close or ohlc4")

    def update(self, bar):
        price = {"typical": (bar.high + bar.low + bar.close) / 3,
                 "close": bar.close, "ohlc4": (bar.open + bar.high + bar.low + bar.close) / 4}[self.basis]
        self.weighted_sum += price * bar.volume
        self.volume += bar.volume
        return self.value

    @property
    def value(self):
        return self.weighted_sum / self.volume if self.volume else None


class FeatureEngine:
    def __init__(self, calendar, basis="typical", ib_minutes=60, atr_period=14):
        if ib_minutes <= 0 or atr_period <= 0:
            raise ValueError("IB and ATR periods must be positive")
        self.calendar, self.basis, self.ib_minutes, self.atr_period = calendar, basis, ib_minutes, atr_period
        VWAP(basis)
        self.day = self.week = self.contract = None
        self.previous_day = {}
        self.prior_close = None
        self.true_ranges = deque(maxlen=atr_period)
        self.last_end = None
        self.week_complete = False

    def reset_day(self, info):
        if self.day is not None:
            self.previous_day = dict(PDH=self.day_high if self.rth_complete else None,
                                     PDL=self.day_low if self.rth_complete else None,
                                     PDC=self.day_close if self.rth_complete else None,
                                     previous_day_complete=self.rth_complete,
                                     previous_trading_date=self.day.isoformat())
        expected_previous = info.trading_date - timedelta(days=1)
        while expected_previous.weekday() >= 5 or self.calendar.overrides.get(expected_previous.isoformat(), {}).get("closed"):
            expected_previous -= timedelta(days=1)
        if self.day is not None and self.day != expected_previous:
            self.previous_day.update(PDH=None, PDL=None, PDC=None, previous_day_complete=False)
        self.day = info.trading_date
        self.vwaps = {name: VWAP(self.basis) for name in ("session", "rth", "overnight")}
        self.day_high = self.day_low = self.day_close = None
        self.on_high = self.on_low = None
        self.rth_open_price = self.session_open_price = None
        self.ib_high = self.ib_low = None
        self.ib_count_seconds = self.rth_count_seconds = 0
        self.ib_started = self.rth_started = False
        self.rth_complete = False
        self.rth_gap = False
        self.session_complete = info.minutes_from_session_open == 0
        self.overnight_complete = info.minutes_from_session_open == 0
        self.ib_complete = False
        self.day_gap = False

    def update(self, bar, reset=False):
        info = self.calendar.classify(bar.timestamp)
        if info is None:
            raise ValueError("Feature bar outside the trading calendar")
        if self.last_end and bar.timestamp < self.last_end:
            raise ValueError("Features require non-overlapping chronological bars")
        if reset:
            # Unadjusted roll levels are incomparable; restart all price state.
            self.day = self.week = None
            self.previous_day = {}
            self.prior_close = None
            self.true_ranges.clear()
            self.last_end = None
        if info.trading_date != self.day:
            self.reset_day(info)
        if info.week != self.week:
            self.week = info.week
            self.weekly = VWAP(self.basis)
            self.week_complete = info.trading_date.weekday() == 0 and info.minutes_from_session_open == 0
        if self.last_end and self.last_end < bar.timestamp:
            probe = self.last_end
            while probe < bar.timestamp:
                if self.calendar.valid_bar(probe, bar.duration):
                    self.day_gap = True
                    self.session_complete = self.week_complete = False
                    if self.calendar.classify(probe).session == "RTH":
                        self.rth_gap = True
                    if self.calendar.classify(probe).session == "OVERNIGHT":
                        self.overnight_complete = False
                probe += bar.duration
        traded = bar.bar_state == "TRADED"
        if bar.coverage_state == "UNKNOWN":
            self.day_gap = self.rth_gap = True
            self.session_complete = self.week_complete = self.overnight_complete = False
        if traded and bar.timestamp == info.open:
            self.session_open_price = bar.open
        self.vwaps["session"].update(bar)
        self.weekly.update(bar)
        if info.session == "OVERNIGHT":
            self.vwaps["overnight"].update(bar)
            if traded:
                self.on_high = max(self.on_high, bar.high) if self.on_high is not None else bar.high
                self.on_low = min(self.on_low, bar.low) if self.on_low is not None else bar.low
        if info.session == "RTH":
            self.vwaps["rth"].update(bar)
            if bar.timestamp == info.segment_open:
                self.rth_open_price = bar.open if traded else None
                self.rth_started = self.ib_started = True
            if traded:
                self.day_high = max(self.day_high, bar.high) if self.day_high is not None else bar.high
                self.day_low = min(self.day_low, bar.low) if self.day_low is not None else bar.low
                self.day_close = bar.close
            self.rth_count_seconds += bar.duration.total_seconds()
            rth_length = (info.segment_close - info.segment_open).total_seconds()
            self.rth_complete = self.rth_started and not self.rth_gap and self.rth_count_seconds == rth_length and bar.end == info.segment_close
            ib_end = info.segment_open + timedelta(minutes=self.ib_minutes)
            if bar.end <= ib_end:
                if traded:
                    self.ib_high = max(self.ib_high, bar.high) if self.ib_high is not None else bar.high
                    self.ib_low = min(self.ib_low, bar.low) if self.ib_low is not None else bar.low
                self.ib_count_seconds += bar.duration.total_seconds()
            self.ib_complete = self.ib_started and not self.rth_gap and self.ib_count_seconds == self.ib_minutes * 60 and bar.end >= ib_end
        if traded:
            tr = max(bar.high - bar.low, abs(bar.high - self.prior_close), abs(bar.low - self.prior_close)) if self.prior_close is not None else bar.high - bar.low
            self.true_ranges.append(tr)
            self.prior_close = bar.close
        atr = sum(self.true_ranges) / self.atr_period if len(self.true_ranges) == self.atr_period else None
        self.last_end, self.contract = bar.end, bar.contract
        values = dict(self.previous_day)
        values.update(
            timestamp=bar.end, trading_date=info.trading_date, session=info.session,
            minutes_from_session_open=info.minutes_from_session_open,
            minutes_to_session_close=info.minutes_to_session_close,
            minutes_from_segment_open=(bar.timestamp - info.segment_open).total_seconds() / 60,
            minutes_to_segment_close=(info.segment_close - bar.timestamp).total_seconds() / 60,
            session_vwap=self.vwaps["session"].value, rth_vwap=self.vwaps["rth"].value,
            overnight_vwap=self.vwaps["overnight"].value, weekly_vwap=self.weekly.value,
            session_vwap_complete=self.session_complete, weekly_vwap_complete=self.week_complete,
            rth_vwap_complete=self.rth_started and not self.rth_gap,
            ONH=self.on_high if self.overnight_complete else None,
            ONL=self.on_low if self.overnight_complete else None,
            overnight_complete=self.overnight_complete,
            RTH_Open=self.rth_open_price, Session_Open=self.session_open_price,
            IBH=self.ib_high if self.ib_complete else None,
            IBL=self.ib_low if self.ib_complete else None, ib_complete=self.ib_complete,
            developing_IBH=self.ib_high, developing_IBL=self.ib_low,
            ATR=atr, day_gap=self.day_gap,
        )
        return MappingProxyType(values)
