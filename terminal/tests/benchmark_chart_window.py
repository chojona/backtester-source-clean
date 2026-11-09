"""Measure warm API latency without logging market rows or filesystem paths."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import math
import os
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from fastapi.testclient import TestClient

from terminal.api import app
from terminal.continuous import build
from terminal.tests.test_continuous_terminal import make_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--samples', type=int, default=30)
    args = parser.parse_args()
    if args.samples < 5:
        parser.error('--samples must be at least 5')
    with (TemporaryDirectory(prefix='nq-window-probe-') if args.synthetic else nullcontext()) as tmp:
        if tmp:
            root = Path(tmp)
            release, cleaned = make_inputs(root, missing=True, extended=True)
            continuous = root / 'continuous'
            build(release, cleaned, continuous)
            os.environ.update(NQ_DATA_ROOT=str(release), NQ_CONTINUOUS_ROOT=str(continuous))
        elif not (os.environ.get('NQ_DATA_ROOT') and os.environ.get('NQ_CONTINUOUS_ROOT')):
            parser.error('Set both validated dataset roots or use --synthetic')
        with TestClient(app) as client:
            exact = client.get('/api/contracts').raise_for_status().json()[0]['contract']
            for contract, frame, display, limit in (
                (exact, '1m', 'Globex', 20), (exact, '15m', 'RTH', 20),
                ('NQ1! Raw', '1m', 'Globex', 20), ('NQ1! Raw', '5m', 'RTH', 20),
                ('NQ1! Adjusted', 'daily', 'Globex', 250),
            ):
                dates = client.get('/api/sessions', params={'contract': contract, 'limit': 5000}).raise_for_status().json()
                session = dates[len(dates)//2]['trading_date']
                config = dict(contract=contract, timeframe=frame, display=display, sessions=limit)
                params = dict(config, session=session)
                first = client.get('/api/chart/window', params=params).raise_for_status().json()
                # Exercise adjacent cursors when available, including movement back to newer pages.
                latencies, max_candles, max_bytes = [], 0, 0
                page = first
                for i in range(args.samples):
                    direction = 'older' if i % 8 < 4 else 'newer'
                    cursor = page[direction+'_cursor']
                    query = dict(config, cursor=cursor) if cursor else params
                    start = perf_counter()
                    response = client.get('/api/chart/window', params=query).raise_for_status()
                    latencies.append((perf_counter()-start)*1000)
                    page = response.json()
                    max_candles = max(max_candles, len(page['bars']))
                    max_bytes = max(max_bytes, len(response.content))
                label = 'exact' if contract == exact else contract
                p95 = sorted(latencies)[math.ceil(len(latencies)*.95)-1]
                print(f'{label:12} {frame:5} {display:6} n={len(latencies):2} '
                      f'p50={median(latencies):6.1f}ms p95={p95:6.1f}ms '
                      f'peak_candles={max_candles:4} peak_bytes={max_bytes:7}')


if __name__ == '__main__':
    main()
