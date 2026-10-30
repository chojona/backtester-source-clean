"""Timezone-aware trading dates, configurable exchange breaks and date overrides."""
from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional

UTC = timezone.utc
NY = ZoneInfo("America/New_York")


def local_at(day, clock):
    return datetime.combine(day, time.fromisoformat(clock), NY).astimezone(UTC)


@dataclass(frozen=True)
class SessionInfo:
    trading_date: date
    session: str
    open: datetime
    close: datetime
    segment_open: datetime
    segment_close: datetime
    minutes_from_session_open: float
    minutes_to_session_close: float
    week: str


@dataclass
class SessionCalendar:
    template: str = "equity"
    eth_open: str = "18:00"
    eth_close: str = "17:00"
    rth_open: Optional[str] = None
    rth_close: Optional[str] = None
    breaks: Optional[list] = None
    overrides: dict = field(default_factory=dict)
    source: str = "weekday template; holidays NOT certified"

    def __post_init__(self):
        if self.template not in ("equity", "gold"):
            raise ValueError("Unknown session template")
        self.rth_open = self.rth_open or ("09:30" if self.template == "equity" else "08:20")
        self.rth_close = self.rth_close or ("16:00" if self.template == "equity" else "13:30")
        if self.breaks is None:
            # Legacy pre-2021 template retained for reproducibility. Use a dated calendar for current NQ.
            self.breaks = [("16:15", "16:30")] if self.template == "equity" else []
        for clock in (self.eth_open, self.eth_close, self.rth_open, self.rth_close):
            time.fromisoformat(clock)
        if not (self.rth_open < self.rth_close <= self.eth_close < self.eth_open):
            raise ValueError("Require RTH open < RTH close <= ETH close < evening ETH open")
        for day, override in self.overrides.items():
            date.fromisoformat(day)
            if not isinstance(override, dict) or set(override) - {"closed", "eth_close", "rth_close", "breaks"}:
                raise ValueError("Calendar override has unsupported fields")
            if "closed" in override and not isinstance(override["closed"], bool):
                raise ValueError("Calendar closed flag must be boolean")
            for start, end in override.get("breaks", []):
                if not time.fromisoformat(start) < time.fromisoformat(end):
                    raise ValueError("Override break must have increasing clocks")
            for key in ("eth_close", "rth_close"):
                if key in override:
                    time.fromisoformat(override[key])
        for start, end in self.breaks:
            if not time.fromisoformat(start) < time.fromisoformat(end):
                raise ValueError("Break must have increasing intraday clocks")

    def bounds(self, trading_date):
        override = self.overrides.get(trading_date.isoformat(), {})
        return (local_at(trading_date - timedelta(days=1), self.eth_open),
                local_at(trading_date, override.get("eth_close", self.eth_close)),
                local_at(trading_date, self.rth_open),
                local_at(trading_date, override.get("rth_close", self.rth_close)))

    def classify(self, timestamp):
        if timestamp.tzinfo is None:
            raise ValueError("Timezone-aware timestamp required")
        stamp = timestamp.astimezone(UTC)
        local = stamp.astimezone(NY)
        trading_date = local.date() + timedelta(days=1) if local.time() >= time.fromisoformat(self.eth_open) else local.date()
        if trading_date.weekday() >= 5 or self.overrides.get(trading_date.isoformat(), {}).get("closed"):
            return None
        opened, closed, rth_open, rth_close = self.bounds(trading_date)
        if not opened <= stamp < closed:
            return None
        for start, end in self.overrides.get(trading_date.isoformat(), {}).get("breaks", self.breaks):
            if local_at(trading_date, start) <= stamp < local_at(trading_date, end):
                return None
        if stamp < rth_open:
            name, segment_open, segment_close = "OVERNIGHT", opened, min(rth_open, closed)
        elif stamp < rth_close:
            name, segment_open, segment_close = "RTH", rth_open, min(rth_close, closed)
        else:
            name, segment_open, segment_close = "POST_RTH", rth_close, closed
        monday = trading_date - timedelta(days=trading_date.weekday())
        return SessionInfo(trading_date, name, opened, closed, segment_open, segment_close,
                           (stamp - opened).total_seconds() / 60,
                           (closed - stamp).total_seconds() / 60, monday.isoformat())

    def valid_bar(self, timestamp, duration):
        first = self.classify(timestamp)
        last = self.classify(timestamp + duration - timedelta(microseconds=1))
        if not first or not last or first.trading_date != last.trading_date or first.session != last.session:
            return False
        # Also catch a bar spanning a maintenance halt.
        probe = timestamp
        while probe < timestamp + duration:
            if self.classify(probe) is None:
                return False
            probe += timedelta(minutes=1)
        return True
