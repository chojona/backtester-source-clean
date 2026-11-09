# Architecture and code map

The repository contains a reusable Python research package and an independent local NQ terminal. They share concepts such as completed-bar availability and exact contract identity, but the terminal does not invoke the backtest engine or execute strategies.

## Python workflows

`backtester/__main__.py` dispatches explicit commands to the daily, intraday, volatility, chart, or provider CLI. Without an explicit recognized subcommand it retains the daily CLI behavior.

| Responsibility | Implementation |
| --- | --- |
| Daily moving-average example | `backtester/engine.py`, `daily_cli.py` |
| Intraday CSV ingestion and bar validation | `backtester/data.py` |
| Instrument definitions and tick conventions | `backtester/instruments.py` |
| Trading dates, segments, and calendar overrides | `backtester/sessions.py` |
| Contract selection and roll handling | `backtester/rolls.py` |
| Intraday orchestration | `backtester/intraday.py` |
| Frozen strategy contexts | `backtester/strategy.py` |
| Execution and portfolio accounting | `backtester/execution.py`, `portfolio.py` |
| Risk configuration and checks | `backtester/risk.py` |
| Session and quantitative features | `backtester/features.py`, `quant_features.py`, `feature_contracts.py` |
| VWAP reaction events and labels | `backtester/research.py` |
| Signal features, evaluation, and interactions | `backtester/signal_research.py`, `signal_evaluation.py`, `signal_interactions.py` |
| Synthetic strategy specifications and pipeline | `backtester/strategy_spec.py`, `strategy_pipeline.py`, `synthetic_execution.py` |
| Strategy analytics and robustness | `backtester/strategy_analytics.py`, `robustness.py`, `robustness_regimes.py` |
| Realized measurements and charts | `backtester/volatility.py`, `profile.py`, `volatility_charts.py` |
| Run metadata and reports | `backtester/reports.py` |
| Databento source adapter and coverage | `backtester/providers/` |
| Certification and production evidence gates | `backtester/market_certification.py`, `evidence_registry.py` |

The intraday CLI reads configuration, validates data, selects raw constituent contracts, and constructs the engine. Strategies receive frozen snapshots of completed bars rather than provider or engine references. Event outcomes are calculated separately from decision-time features. CLI reports capture input/code hashes, configuration, calendar and execution assumptions, integrity findings, and run identifiers.

Roll-adjusted research representations and raw executable prices are distinct. The volatility/chart path consumes selected raw bars rather than adjusted research closes. The synthetic laboratory enforces its own synthetic-input contract and is not connected to historical terminal data.

## Exploratory NQ lane

`backtester/research_nq/` is a read-only, non-certifying adapter surface:

- `manifest.py` and `schema.py` validate manifest structure and keep Python/JSON Schema acceptance aligned.
- `binding.py` binds supplied dataset and calendar bytes to their declared hashes.
- `classifications.py` keeps observed, inferred no-trade, materialized, and unresolved availability distinct.
- `adapter.py` reconciles bound bars and calendar context and exposes causal exploratory records.

This lane always declares `strict_eligible=False`. Its detailed contracts and review status are maintained in the package's [specification](../backtester/research_nq/SPEC.md), [binding guide](../backtester/research_nq/BINDING.md), and [M1-R handoff](../backtester/research_nq/M1R_HANDOFF.md). A general repository guide does not change those statuses.

## Terminal request path

```text
Browser selection / replay cursor
    → Next.js /api rewrite
    → FastAPI parameter validation
    → ResearchStore: verified external Parquet + eligibility/context queries
    → Completed source-minute prefix
    → Display filter, aggregation, indicators, statistics, Explorer page
    → One snapshot consumed by chart, sidebar, and Explorer
```

| Component | Responsibility |
| --- | --- |
| `terminal/launch.py` | Reads local environment configuration, checks default ports, starts and stops both loopback servers |
| `terminal/api.py` | Read-only HTTP endpoints, bounded parameters, and error translation |
| `terminal/data.py` | Seal verification, exact contract/eligibility predicates, cutoff filtering, aggregation, indicator math, time-to-cursor lookup |
| `terminal/web/next.config.ts` | Rewrites frontend `/api/` calls to the local backend |
| `terminal/web/components/Terminal.tsx` | Selection, request cancellation, playback, layout, and workspace state |
| `terminal/web/components/MarketChart.tsx` | Lightweight Charts lifecycle, series, previous-session price lines, viewport persistence and replay following |
| `terminal/web/components/Drawings.tsx` | Price/time overlay, object selection, handles, anchor editing, and replay-aware visibility |
| `terminal/web/components/IndicatorManager.tsx` | Indicator appearance and parameter controls |
| `terminal/web/components/Analytics.tsx` | Statistics and context from the same snapshot used for plotting |
| `terminal/web/components/Explorer.tsx` | Paged observed candles and explicitly inactive workspace tabs |
| `terminal/web/lib/types.ts` | API types, fetch helper, price/time formatting |
| `terminal/web/lib/workspace.ts` | Local persistence, settings normalization, drawing validation/projection |

The server verifies six consumed artifacts against `SUCCESS.json`. DuckDB connections are in-memory; historical records remain in the external release. An individual snapshot calculates at most one selected session, while range requests are bounded and return separate session arrays.

The observed-minute cutoff is applied before aggregation and derived calculations. RTH display further filters that prefix to the ordinary 09:30–16:00 ET window. A developing higher-timeframe candle therefore contains completed source minutes only. Previous-session context retains the exact prior-candidate gate and never borrows across rolls or skipped dates.

## Browser-local state

Local storage uses three families of keys:

| Key | State |
| --- | --- |
| `nq:v2:workspace` | Selection, display, layout, main panel visibility, indicator configuration |
| `nq:v2:view:<contract>/<session>/<frame>/<display>` | Historical chart time window; replay windows append `/replay` |
| `nq:v2:drawings:<contract>:<session>:<display>` | Drawing objects with UTC-time/price anchors and creation cutoff |

Drawings are independent of timeframe and are reprojected when scales change. Objects created after the replay cutoff or containing future anchors are hidden from both the overlay and object editor. Browser state is local to an origin/profile, does not sync across devices, and is not written into the sealed dataset.

## Operational limits

The terminal has no execution/brokerage endpoints, live data feed, order flow, options flow, or historical strategy runner. The offline Matplotlib/HTML chart exporter is a separate application path with its own aggregation behavior; its exported reports are not terminal inputs.


### Terminal chart history

The chart obtains history through `/api/chart/window`. The endpoint checks
verified release identity, bounds each query to selected dates, and returns
whole-session pages with separate continuation cursors. Exact contracts use
the sealed eligibility predicate. Continuous Raw and Adjusted use the
verified derived files and preserve roll and adjustment block identity.
A browser-local cache merges observed bars and keeps gaps separately.
The selected-session snapshot remains the source for replay and the
session analytics panels. [Phase 1 architecture and verification](../terminal/PHASE1_VERIFICATION.md)
