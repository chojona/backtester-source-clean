"""Create deterministic, synthetic CSV examples in the ignored data directory."""

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def generate(output_dir: Path) -> None:
    daily = []
    day = date(2024, 1, 2)
    while len(daily) < 500:
        if day.weekday() < 5:
            index = len(daily)
            opening = 4500 + (index % 31) * 0.25 + index * 0.1
            daily.append({"date": day.isoformat(), "open": opening,
                          "close": opening + ((index % 9) - 4) * 0.25})
        day += timedelta(days=1)
    write_csv(output_dir / "sample.csv", ["date", "open", "close"], daily)

    minute = []
    five_minute = []
    fields = ["timestamp", "open", "high", "low", "close", "volume", "contract", "symbol"]
    for session in range(2):
        start = datetime(2026, 1, 4 + session, 23, tzinfo=timezone.utc)
        for index in range(1380):
            if 1335 <= index < 1350:  # Calendar maintenance break, 16:15–16:30 New York time.
                continue
            timestamp = start + timedelta(minutes=index)
            opening = 20000 + session * 15 + index * 0.01
            closing = opening + ((index % 11) - 5) * 0.25
            minute.append({"timestamp": timestamp.isoformat(), "open": opening,
                           "high": max(opening, closing) + 0.5,
                           "low": min(opening, closing) - 0.5,
                           "close": closing, "volume": 100 + index % 300,
                           "contract": "NQZ26", "symbol": "NQ"})
            if index % 5 == 4:
                group = minute[-5:]
                five_minute.append({"timestamp": group[0]["timestamp"],
                                    "open": group[0]["open"],
                                    "high": max(row["high"] for row in group),
                                    "low": min(row["low"] for row in group),
                                    "close": group[-1]["close"],
                                    "volume": sum(row["volume"] for row in group),
                                    "contract": "NQZ26", "symbol": "NQ"})
    write_csv(output_dir / "synthetic_NQ_1m.csv", fields, minute)
    write_csv(output_dir / "synthetic_NQ_5m.csv", fields, five_minute)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    generate(parser.parse_args().output_dir)
