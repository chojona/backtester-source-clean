"""Outcome-free opening-range event decisions on a constructed cash-session clock."""

from dataclasses import dataclass
from datetime import datetime, time

from .inputs import MINUTE, Session, ticks
from .protocol import Protocol


@dataclass(frozen=True)
class OpeningRangeEvent:
    first_cross: datetime
    decision_time: datetime
    max_source_availability: datetime
    range_high_ticks: int
    range_low_ticks: int
    side: int
    closes_ticks: tuple[int, int, int]
    accepted: bool


@dataclass(frozen=True)
class Decision:
    reason: str
    event: OpeningRangeEvent | None = None


def detect_opening_range(session: Session, protocol: Protocol) -> Decision:
    opening_end = session.cash_open + protocol.opening_minutes * MINUTE
    opening = [session.observations.get(session.cash_open + offset * MINUTE)
               for offset in range(protocol.opening_minutes)]
    if any(bar is None or not bar.traded or bar.available_at > opening_end for bar in opening):
        return Decision("unavailable_opening_range")
    high = max(ticks(bar.bar.high) for bar in opening)
    low = min(ticks(bar.bar.low) for bar in opening)
    scan_through = time.fromisoformat(protocol.scan_through)
    cash_time = time.fromisoformat(protocol.cash_open)
    last_scan_offset = (scan_through.hour - cash_time.hour) * 60 + scan_through.minute - cash_time.minute

    max_available = max(bar.available_at for bar in opening)
    for offset in range(protocol.opening_minutes, last_scan_offset + 1):
        label = session.cash_open + offset * MINUTE
        bar = session.observations.get(label)
        if bar is None or not bar.traded or bar.available_at > label + MINUTE:
            return Decision("unavailable_scan_bar")
        max_available = max(max_available, bar.available_at)
        close = ticks(bar.bar.close)
        if close >= high + protocol.outside_ticks:
            side, edge = 1, high
        elif close <= low - protocol.outside_ticks:
            side, edge = -1, low
        else:
            continue

        decision_time = label + (protocol.confirmation_bars + 1) * MINUTE
        confirmation = [session.observations.get(label + step * MINUTE)
                        for step in range(1, protocol.confirmation_bars + 1)]
        if any(item is None or not item.traded for item in confirmation):
            return Decision("missing_confirmation")
        max_available = max(max_available, *(item.available_at for item in confirmation))
        if max_available > decision_time:
            return Decision("late_confirmation")
        closes = (close, *(ticks(item.bar.close) for item in confirmation))
        accepted = all(side * (value - edge) >= protocol.outside_ticks for value in closes)
        return Decision("accepted" if accepted else "rejected",
                        OpeningRangeEvent(label, decision_time, max_available, high, low, side, closes, accepted))
    return Decision("no_cross")
