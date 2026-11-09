from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite

from terminal.data import DataError, ET

VERSION = 'amt-ohlcv-v1'
MINUTE = timedelta(minutes=1)
TICK_SIZE = .25
MAX_PRICE_ROWS = 4096
MAX_OBSERVATIONS = 31 * 1500


def local_stamp(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), ET).astimezone(timezone.utc)


def session_bounds(day: date, display: str) -> tuple[datetime, datetime]:
    if display == 'RTH':
        return local_stamp(day, 9, 30), local_stamp(day, 16)
    return local_stamp(day - timedelta(days=1), 18), local_stamp(day, 17)


def trading_date(stamp: datetime) -> date:
    local = stamp.astimezone(ET)
    return local.date() + timedelta(days=local.hour >= 18)


def elapsed_minutes(start: datetime, end: datetime, cutoff: datetime) -> int:
    return max(0, (min(end, cutoff) - start) // MINUTE)


def price_tick(price: float) -> int:
    if price is None or not isfinite(price):
        raise DataError('AMT requires finite source prices')
    units = price / TICK_SIZE
    tick = round(units)
    if abs(tick - units) > 1e-7:
        raise DataError('AMT source price is off the NQ tick grid')
    return tick


@dataclass(frozen=True, slots=True)
class Bar:
    time: datetime
    low: int
    high: int
    close: int
    volume: int

    @property
    def typical_tick(self) -> int:
        return (self.low + self.high + self.close + 1) // 3
