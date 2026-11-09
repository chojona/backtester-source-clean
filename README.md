# Futures research backtester and NQ Research Terminal

Source-only Python tools for futures backtesting, causal intraday research, realized-volatility analysis, and a local **NQ Research Terminal v0.3** with read-only release access. Market records, credentials, fitted models, and generated research outputs are not bundled.

The Python engine and the terminal are separate workflows. The engine accepts user-supplied inputs or explicitly constructed software examples. The terminal requires an existing sealed `nq-ohlcv-research-v2.0.0` release and never substitutes demo candles.

## Start here

| Goal | Guide |
| --- | --- |
| Install the Python tools and run a local example | [Getting started](docs/GETTING_STARTED.md) |
| Launch the NQ terminal, use drawings and replay, or inspect its API | [Terminal guide](terminal/README.md) |
| Find the implementation behind a feature | [Architecture](docs/ARCHITECTURE.md) |
| Run tests and prepare a change | [Development](docs/DEVELOPMENT.md) |
| Understand inputs, timing, eligibility, and certification | [Data and provenance](docs/DATA_AND_PROVENANCE.md) |
| Check what belongs in Git | [Source export boundary](PUBLIC_EXPORT.md) |

## Python quick start

Requires Python 3.12 or newer. Run these commands from the repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest tests -q
```

No provider account or historical dataset is needed for the core offline tests. Optional SDK/chart checks may skip when their dependencies are absent.

To exercise the included example workflow:

```sh
python scripts/generate_synthetic_examples.py
python -m backtester validate-data data/synthetic_NQ_1m.csv --symbol NQ --interval 1
python -m backtester daily --data data/sample.csv --output results/daily-example
```

These examples are deterministic software fixtures, not observed prices or evidence of market performance. Generated files stay in ignored directories. The terminal does not consume them.

## What is implemented

| Area | Scope |
| --- | --- |
| Daily backtest | Long-only moving-average crossover with configurable futures costs, contract sizing, and margin assumptions |
| Intraday engine | Completed-bar strategy contexts, session calendars, raw-contract selection, execution modeling, risk checks, and run reports |
| Event and signal research | Weekly VWAP reaction event studies, causal features, separately calculated outcomes, interaction analysis, and robustness utilities |
| Synthetic strategy laboratory | Versioned specifications, execution, analytics, and robustness checks that explicitly require synthetic inputs |
| Realized measurements | Volatility/variance estimators and optional local chart exports |
| NQ exploratory adapter | Read-only dataset/calendar binding and availability classifications; all exploratory outputs remain non-certifying |
| NQ terminal | Sealed-release browsing, Globex/RTH display, configurable indicators, persistent price/time drawings, resizable panels, and server-filtered replay |

The intraday CLI supports ES, MES, NQ, MNQ, GC, and MGC. The terminal is specifically bound to the NQ release. Its Strategy Research, Backtest Results, and Experiment History tabs remain inactive; they are not connected to the Python research utilities.

## Repository layout

```text
backtester/          Python engines, research algorithms, adapters, chart assets
  research_nq/      Non-certifying exploratory manifest and read-only adapter
config/             Example research configuration and empty evidence registry
scripts/            Constructed examples and source-publication checks
terminal/           Read-only FastAPI/DuckDB backend and local launcher
  tests/            Historical-release backend integration tests
  web/              Next.js/TypeScript UI and Playwright tests
tests/              Core offline regression tests
docs/               Setup, architecture, development, and data guides
```

## Research boundaries

Bar-open timestamps and decision-time availability are distinct. Terminal replay filters completed source minutes before calculating candles, statistics, and indicators. Retrospective release eligibility and a matching local file seal do not establish strict historical certification.

Provider access requires separately obtained credentials and data rights. There is no live trading or brokerage connection. Keep source datasets, provider responses, calendars, private evidence, screenshots of market data, and generated reports outside Git; see the [publication rules](PUBLIC_EXPORT.md).

The [v0.3 implementation report](terminal/IMPLEMENTATION_V03.md) describes the VWAP workspace and synthetic demo. The [continuous chart guide](terminal/CONTINUOUS.md) covers Raw and Adjusted history, roll uncertainty, and intraday loading. Historical strategy execution remains blocked. [Research review status](docs/RESEARCH_REVIEW_STATUS.md)
