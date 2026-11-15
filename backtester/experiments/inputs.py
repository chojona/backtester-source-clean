"""Constructed one-minute sessions with separate bar and availability clocks."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from types import MappingProxyType
from typing import Mapping
from zoneinfo import ZoneInfo

from backtester.data import Bar
from backtester.instruments import contract_root, instrument

from .protocol import Protocol


MINUTE = timedelta(minutes=1)
TICK_SIZE = instrument("NQ").tick_size


def ticks(price: float) -> int:
    value = price / TICK_SIZE
    if not value.is_integer():
        raise ValueError("NQ price must align to a whole tick")
    return int(value)


@dataclass(frozen=True)
class Observation:
    bar: Bar
    available_at: datetime

    def __post_init__(self):
        if self.available_at.utcoffset() is None or self.available_at < self.bar.end:
            raise ValueError("OHLCV availability must be at or after bar close")
        object.__setattr__(self, "available_at", self.available_at.astimezone(timezone.utc))
        if self.bar.symbol != "NQ" or self.bar.duration != MINUTE:
            raise ValueError("Expected a one-minute NQ bar")
        for price in (self.bar.open, self.bar.high, self.bar.low, self.bar.close):
            ticks(price)

    @property
    def traded(self) -> bool:
        return self.bar.bar_state == "TRADED" and self.bar.published and self.bar.volume > 0


@dataclass(frozen=True)
class Session:
    day: date
    contract: str
    cash_open: datetime
    cash_close: datetime
    observations: Mapping[datetime, Observation]

    def __post_init__(self):
        if (contract_root(self.contract) != "NQ" or self.cash_open.utcoffset() is None
                or self.cash_close.utcoffset() is None
                or self.cash_close - self.cash_open != 390 * MINUTE):
            raise ValueError("Expected a constructed full NQ cash session")
        observations = dict(self.observations)
        for label, observation in observations.items():
            if (label != observation.bar.timestamp or observation.bar.contract != self.contract
                    or not self.cash_open <= label < self.cash_close
                    or (label - self.cash_open) % MINUTE):
                raise ValueError("Invalid label or contract in synthetic session")
        object.__setattr__(self, "observations", MappingProxyType(observations))

    def coverage_reason(self) -> str | None:
        for offset in range((self.cash_close - self.cash_open) // MINUTE):
            observation = self.observations.get(self.cash_open + offset * MINUTE)
            if observation is None:
                return "missing_cash_bar"
            if not observation.traded:
                return "nontraded_cash_bar"
        return None


def make_session(
    protocol: Protocol,
    day: date,
    *,
    closes: Mapping[int, int],
    opens: Mapping[int, int],
    missing: tuple[int, ...] = (),
    late: Mapping[int, int] | None = None,
) -> Session:
    """Generate bars in ticks keyed by minute offset from the cash open."""
    zone = ZoneInfo(protocol.timezone)
    cash_open, cash_close = (
        datetime.combine(day, time.fromisoformat(label), zone).astimezone(timezone.utc)
        for label in (protocol.cash_open, protocol.cash_close)
    )
    contract = "NQH30"
    observations = {}
    for offset in range((cash_close - cash_open) // MINUTE):
        if offset in missing:
            continue
        label = cash_open + offset * MINUTE
        open_ticks = opens.get(offset, 80000)
        close_ticks = closes.get(offset, 80000)
        high_ticks = max(open_ticks, close_ticks, 80002) if offset < 30 else max(open_ticks, close_ticks)
        low_ticks = min(open_ticks, close_ticks, 79998) if offset < 30 else min(open_ticks, close_ticks)
        bar = Bar(label, open_ticks * TICK_SIZE, high_ticks * TICK_SIZE, low_ticks * TICK_SIZE,
                  close_ticks * TICK_SIZE, 1, contract, "NQ")
        observations[label] = Observation(bar, label + (1 + (late or {}).get(offset, 0)) * MINUTE)
    return Session(day, contract, cash_open, cash_close, observations)


def acceptance_fixture(protocol: Protocol) -> tuple[Session, ...]:
    cases = (
        ({30: 80003, 31: 80004, 32: 80003}, {33: 80004, 63: 80014, 34: 80005, 64: 80015}, ()),
        ({30: 80003, 31: 79997, 32: 80003, 34: 80004, 35: 80004, 36: 80004},
         {33: 80004, 63: 79994, 34: 80005, 64: 79995}, ()),
        ({30: 80002}, {}, ()),
        ({117: 79997, 118: 79996, 119: 79997}, {120: 79996, 150: 79986, 121: 79995, 151: 79985}, ()),
        ({30: 80003, 31: 80003}, {}, (32,)),
    )
    return tuple(
        make_session(protocol, date(2030, 1, day), closes=closes, opens=opens, missing=missing)
        for day, (closes, opens, missing) in enumerate(cases, start=7)
    )
