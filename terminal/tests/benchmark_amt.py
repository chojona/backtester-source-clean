"""Warm ASGI probe for bounded AMT responses, without logging source prices."""
import argparse
from contextlib import nullcontext
from math import ceil
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
    if not args.synthetic and not (os.getenv('NQ_DATA_ROOT') and os.getenv('NQ_CONTINUOUS_ROOT')):
        parser.error('Set both sealed dataset roots or select --synthetic')

    with TemporaryDirectory(prefix='nq-amt-probe-') if args.synthetic else nullcontext() as directory:
        if directory:
            root = Path(directory)
            release, cleaned = make_inputs(root, missing=True, extended=True)
            continuous = root / 'continuous'
            build(release, cleaned, continuous)
            os.environ.update(NQ_DATA_ROOT=str(release), NQ_CONTINUOUS_ROOT=str(continuous))
        with TestClient(app) as client:
            provenance = client.get('/api/provenance').raise_for_status().json()
            print(provenance['chart_series'], provenance['continuous']['chart_series'])
            exact = client.get('/api/contracts').raise_for_status().json()[0]
            newest = dict(contract=exact['contract'], session=exact['last_session'])
            adjusted = dict(contract='NQ1! Adjusted', session='2026-03-13' if directory else '2026-08-31')
            cases = [
                ('profile', newest | dict(method='uniform', row_ticks=4, sensitivity=True)),
                ('tpo', newest | dict(display='RTH', row_ticks=4, representation='letters')),
                ('profile', newest | dict(contract='NQ1! Raw', method='hlc3', row_ticks=4)),
                ('profile', adjusted | dict(scope='month', row_ticks=16, method='uniform')),
                ('vwap', adjusted | dict(scope='month', display='RTH')),
                ('context', newest | dict(display='RTH', row_ticks=4)),
            ]
            for route, params in cases:
                path = '/api/amt/' + route
                client.get(path, params=params).raise_for_status()
                elapsed, peak_rows, peak_bytes, minutes = [], 0, 0, 0
                for _ in range(args.samples):
                    start = perf_counter()
                    response = client.get(path, params=params).raise_for_status()
                    elapsed.append((perf_counter() - start) * 1000)
                    body = response.json()
                    payload = body.get(route, {})
                    peak_rows = max(peak_rows, len(payload.get('rows', payload.get('points', []))))
                    peak_bytes = max(peak_bytes, len(response.content))
                    minutes = max(minutes, body['coverage']['observed_minutes'])
                label = 'Exact' if not params['contract'].startswith('NQ1!') else params['contract']
                print(f'{route:7} {label:13} {params.get("scope", "session"):7} {params.get("display", "Globex"):6} '
                      f'n={args.samples} p50={median(elapsed):.1f}ms p95={sorted(elapsed)[ceil(len(elapsed)*.95)-1]:.1f}ms '
                      f'rows_or_points={peak_rows} source_minutes={minutes} bytes={peak_bytes}', flush=True)


if __name__ == '__main__':
    main()
