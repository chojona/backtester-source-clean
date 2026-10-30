from datetime import datetime, timedelta, date
import json
from pathlib import Path
import pytest
from backtester.data import Bar
from backtester.instruments import instrument
from backtester.sessions import NY, UTC, SessionCalendar, local_at
from backtester.rolls import SelectedBar


def make_bar(stamp="2026-01-05T09:30", opening=100, high=None, low=None, close=None,
             volume=10, contract="ESZ26", minutes=1, **optional):
    when = datetime.fromisoformat(stamp) if isinstance(stamp, str) else stamp
    if when.tzinfo is None:
        when = when.replace(tzinfo=NY)
    closing = opening if close is None else close
    return Bar(when, opening, max(opening, closing) + 1 if high is None else high,
               min(opening, closing) - 1 if low is None else low, closing, volume,
               contract, "ES", timedelta(minutes=minutes), **optional)


def day_bars(day=date(2026, 1, 5), calendar=None, minutes=1, price=100, contract="ESZ26"):
    calendar = calendar or SessionCalendar()
    opened, closed, _, _ = calendar.bounds(day)
    result = []
    stamp = opened
    duration = timedelta(minutes=minutes)
    while stamp < closed:
        if calendar.valid_bar(stamp, duration):
            result.append(make_bar(stamp, price, contract=contract, minutes=minutes))
        stamp += duration
    return result


def selected(bars):
    return [SelectedBar(b, b) for b in bars]
