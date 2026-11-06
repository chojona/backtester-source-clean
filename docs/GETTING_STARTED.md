# Getting started

Choose the Python research tools or the NQ terminal workflow. They have different inputs and dependency sets. All commands below start at the repository root unless a `cd` is shown.

## Python research tools

Use Python 3.12 or newer:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest tests -q
```

`setup.py` defines the package and optional dependencies; `pyproject.toml` pins the build backend. The installed `backtester` command and `python -m backtester` share the same entry point.

Optional capabilities are installed explicitly:

```sh
# Matplotlib exports and offline interactive chart reports
python -m pip install -e '.[test,charts]'

# Provider adapter SDK; not required for offline research tests
python -m pip install -e '.[test,databento]'
```

Installing an SDK does not acquire data. This guide does not invoke any provider downloads.

### Run the constructed examples

```sh
python scripts/generate_synthetic_examples.py
python -m backtester validate-data data/synthetic_NQ_1m.csv --symbol NQ --interval 1
python -m backtester daily --data data/sample.csv --output results/daily-example
```

The generator creates `sample.csv`, `synthetic_NQ_1m.csv`, and `synthetic_NQ_5m.csv` under ignored `data/`. These formulas test software paths only. The integrity report can flag off-tick prices in the minute examples; generating a file does not make it market-valid or certified.

The daily example writes `summary.json`, `equity.csv`, and `trades.csv` to the requested local output directory. Do not commit those outputs.

### Inspect user-supplied intraday data

Replace the input path with an existing file you are entitled to use:

```sh
python -m backtester validate-data \
  --data /absolute/path/to/minute-bars.csv --symbol NQ --interval 1
```

See [data conventions](DATA_AND_PROVENANCE.md) before interpreting the report. The [example configuration](../config/research.example.json) contains illustrative execution, risk, and calendar settings that must be reviewed for the intended input.

For a run that computes engine features without submitting strategy orders:

```sh
python -m backtester run \
  --data /absolute/path/to/minute-bars.csv --symbol NQ --interval 1 \
  --strategy feature-audit --config config/research.example.json \
  --output results
```

The CLI reports a generated run ID. To display its summary, replace `RUN_ID` with that ID:

```sh
python -m backtester report RUN_ID --output results
```

Missing intervals and off-tick prices can stop a run. Inspect and understand those conditions rather than treating permissive flags as data repair. The weekly VWAP reaction strategy is an event study and submits no trades.

### Realized-volatility tools

These commands consume user-supplied one-minute data. The chart export requires the `charts` extra:

```sh
python -m backtester volatility \
  --data /absolute/path/to/minute-bars.csv --symbol NQ

python -m backtester volatility-charts \
  --data /absolute/path/to/minute-bars.csv --symbol NQ \
  --output reports/local-charts
```

The volatility command prints JSON. The chart command creates an offline HTML viewer, copied local chart assets, measurements, and scientific image exports. Its output directory must not already exist. This offline viewer is separate from the Next.js NQ terminal.

## NQ Research Terminal

The terminal requires Python 3.12+, Node 22+, npm, and access to the existing sealed NQ release. Use a separate Python environment because its dependency list is independent of the core package's test extras:

```sh
python3.12 -m venv .venv-terminal
.venv-terminal/bin/python -m pip install -r terminal/requirements.txt
npm --prefix terminal/web ci
cp terminal/.env.example terminal/.env
```

Edit the ignored `terminal/.env` so `NQ_DATA_ROOT` points to the release's existing build directory. See the [required artifact list](../terminal/README.md#dataset-binding). No data is copied or downloaded by the launcher.

```sh
.venv-terminal/bin/python -m terminal.launch
```

Open [the local frontend](http://127.0.0.1:3000); the API schema is available at [the local API docs](http://127.0.0.1:8000/docs). Both processes bind to loopback. Ctrl-C stops both. Ports 3000 and 8000 must be free.

The [terminal guide](../terminal/README.md) covers production builds, separate processes, drawing controls, indicators, replay, and browser tests.

## Help and troubleshooting

| Symptom | Where to check |
| --- | --- |
| `No module named backtester` | Activate the intended environment and install the repository with `pip install -e ...` |
| Terminal returns 503 | Verify `NQ_DATA_ROOT`, required artifact presence, release version, and hashes; no fallback data is supplied |
| Terminal port is occupied | Stop the process using that port before running the combined launcher |
| Input is rejected for timestamps, gaps, or contract identity | Read [data conventions](DATA_AND_PROVENANCE.md) and inspect `validate-data` output |
| Historical tests skip | Set `NQ_DATA_ROOT` in the test process; the launcher reading `.env` does not export it into your shell |
| Browser executable is absent | Install Playwright Chromium or set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` as documented in the terminal guide |

For command-specific flags, use `python -m backtester daily --help`, `python -m backtester validate-data --help`, `python -m backtester run --help`, `python -m backtester volatility --help`, or `python -m backtester volatility-charts --help`. The top-level `--help` describes the legacy daily CLI, not every dispatched subcommand.
