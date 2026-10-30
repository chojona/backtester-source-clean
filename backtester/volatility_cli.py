"""Deterministic local realized-measurement report; no execution or forecasts."""
import argparse
from dataclasses import asdict
from pathlib import Path
import json

from .cli import objects, read_config, sha256
from .reports import serial
from .rolls import ContinuousSeries, RollConfig
from .volatility import RealizedVolatility


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["volatility"])
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--symbol", required=True, choices=["NQ", "ES", "GC"])
    parser.add_argument("--contract")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--tbpv-squared-threshold", type=float)
    parser.add_argument("--as-of", help="Only include bars completed by this aware ISO timestamp")
    args = parser.parse_args()
    args.interval = 1
    try:
        from datetime import datetime
        cutoff = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
        if cutoff and cutoff.tzinfo is None:
            raise ValueError("as-of requires timezone")
        config = read_config(args.config)
        _, calendar, provider = objects(args, config)
        digest = sha256(args.data)
        bars, integrity = provider.load()
        if digest != sha256(args.data):
            raise ValueError("Input changed during ingestion")
        bars = tuple(b for b in bars if cutoff is None or b.end <= cutoff)
        if not bars:
            raise ValueError("No completed bars at cutoff")
        stream = RealizedVolatility(calendar, tbpv_squared_threshold=args.tbpv_squared_threshold)
        # Reuse causal roll selection, consume only raw prices. No trading objects.
        series = ContinuousSeries(calendar, RollConfig(**config.get("roll", {})))
        records = {}
        for item in series.select(bars):
            row = stream.update(item.raw, as_of=item.raw.end)
            records[(row.trading_date, row.contract)] = row
        print(json.dumps(dict(schema_version="realized-volatility-1", data_sha256=digest,
                              input_price_basis="raw", calendar_source=calendar.source,
                              integrity=asdict(integrity), records=[asdict(r) for r in records.values()],
                              limitations=["Synthetic fixtures verify implementation only; real-data acceptance pending.",
                                           "Incomplete prefixes are null; observed_rv is a diagnostic.",
                                           "5m/15m use completed segment-anchored blocks; inspect covered minutes."]),
                         default=serial, allow_nan=False, indent=2))
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
