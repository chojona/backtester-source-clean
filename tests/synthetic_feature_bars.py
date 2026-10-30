"""Construct artificial feature observations; no saved snapshots or market records."""
from datetime import datetime, timedelta, timezone
from backtester.quant_features import Observation

def bars(instrument, closes, *, source="STEP11A_SYNTHETIC", arrival_seconds=0):
    origin = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
    result = []
    for index, price in enumerate(closes):
        start = origin + timedelta(minutes=index)
        end = start + timedelta(minutes=1)
        result.append(Observation(instrument, source, "2026-01-05", "RTH",
            start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z"),
            (end + timedelta(seconds=arrival_seconds)).isoformat().replace("+00:00", "Z"),
            price, price, price, price, 100 + index, instrument + "H26"))
    return result
