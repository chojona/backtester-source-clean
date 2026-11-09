# NQ Research Terminal v0.3 — implementation and validation

## Source reconciliation and infrastructure reuse

This task started at `b998421`, before the terminal existed. The local repository
also contains v0.2 (`c106421`). Its `terminal/` source is restored here, with its
existing Next.js/React interface, FastAPI/DuckDB dataset service, drawings,
workspace persistence, interval aggregation, replay, indicators and provenance.
The frontend source publication allowance is restored from the same commit;
production evidence registries and certification code are unchanged.

Research reuses `features.VWAP`, the cryptographically bound
`ReadOnlyExploratoryAdapter`, calendar/grid validation, classification and
availability controls, and `signal_evaluation` session-block bootstrap. Existing
`signal_research` supplies causal feature/outcome separation conventions.
`strategy_pipeline` and `synthetic_execution` were inspected: their specifications
and admission policy are synthetic execution contracts, not permission to backtest
licensed historical data. They are deliberately not repurposed as historical gates.

## Working surfaces

The Strategy Research and Experiment History tabs open the local research
workspace inside the existing terminal. A shared Python research module powers
both FastAPI and a dependency-free standalone software-test server. There is one
event detector and one evaluator, rather than a second research engine.

Select the fixed VWAP specification, exact raw contract, inclusive ET trading
dates and complete-observation policy. Submit a queued job, inspect errors or a
completed report, select events, inspect their corresponding chart and forward
windows, download the verified JSON artifact, reopen history and compare two
artifacts. No parameter search or brokerage endpoints exist.

The original market chart can receive research markers only for 1m data with a
matching release identity, contract, session, candle timestamp and close. A
synthetic experiment cannot overlay historical prices. The research chart always
uses candles carried by the exact immutable experiment. Higher-timeframe marker
projection is intentionally unavailable. Independent cost scenarios are never
presented as actual simulated entry/exit markers.

## Scientific specification: vwap-acceptance-rejection 1.0.0

- Historical input contract: observed raw-contract one-minute OHLCV; no stitching,
  filling or back adjustment. The VWAP is explicitly the HLC3 volume-weighted
  proxy, not trade-notional VWAP.
- Reset at 18:00 ET previous calendar date using the bound exchange calendar.
  Require every valid minute from reset through 12:17 ET, allowing only scheduled
  closures. Reject missing, duplicate, unordered, off-grid, unresolved, materialized,
  zero-volume, unavailable or invalid observations. Sessions that fail this required
  analysis window are listed as excluded. This does not certify a full trading day.
- Signals confirm at bar end, 09:45–12:00 ET inclusive. Publication later than
  bar end blocks bar-close confirmation. Assumed-close availability is disclosed.
- Acceptance: a crossing close at least one NQ tick (0.25 point) beyond its VWAP,
  followed by another close at least one tick on that side. The close before the
  crossing must be on or beyond the opposite side of its own contemporaneous VWAP.
- Rejection: previous close at least one tick on a side; current range touches
  current VWAP; current close finishes at least one tick on that same side.
- Acceptance wins simultaneous classification; a deterministic 15-minute signal
  cooldown is applied per session across directions/classes. Detection uses only
  completed prefixes. Future bars never enter detection.
- Labels are signed simple close returns at +5/+10/+15 minutes, with favorable
  and adverse excursions across intervening OHLC ranges. Ties are misses.
- Controls use the same ET minute and event direction on other eligible dates in
  the same predeclared partition. Baselines are descriptive evaluations and never
  inputs to the detector. No matching across development/validation partitions.
- Session-block percentile intervals use the existing helper: seed 1701, 500
  resamples, minimum five event sessions. Bonferroni allocates 0.05/18 across two
  partitions, three horizons and three metrics (hit rate, return, paired excess).
  Sparse or unmatched estimates are explicitly unavailable. No significance or
  alpha claim is made.
- Independent cost scenario: one NQ contract, $20/point, first observed open
  strictly later than confirmation (one minute later than the immediate boundary),
  exit open 15 minutes after that entry, 0.25 point adverse slippage per side and
  $2.50 commission per side: $15 round trip. Report mean net USD per event.
  These independent, potentially overlapping scenarios are NOT portfolio returns.
  Sharpe, profit factor and equity curves are null with an accounting explanation.

## Admission and current blocked state

The sealed v2.0.0 release is retrospectively QC eligible, not strict certified.
`PRODUCTION_MANIFESTS` remains empty. The existing historical chart read path is
preserved; historical strategy execution invokes both `VWAP` and `signal`
`require_strict_dataset` gates before any observation read. Hash seals and
exploratory manifests cannot override those gates. The standard v2.0.0 research
request therefore ends with an explicit BLOCKED/NO-GO state. No historical
experiment, final-holdout inspection, protected-market-file read, empirical
performance or production certification was performed during this task.

A future independently accepted release also needs a reviewed calendar,
availability metadata and predeclared chronological partitions. A generic canonical
bound-input adapter is available via administrator-owned `NQ_RESEARCH_BUNDLE`;
this does not convert the current Parquet release into a certified dataset.
It is gated by the same production checks. No UI or bundle can supply trust pins.
The final chronological partition is sealed; selecting it rejects the request.

## Persistence and replay

Artifacts use a SHA-256 identity over canonical JSON including specification,
configuration, dataset/calendar hashes, manifest plus reference, partition map,
source/content code identity, results, candles and validation outcomes. Atomic
exclusive hard-link publication never overwrites an existing artifact. Reads
verify content identity; comparisons do not mutate inputs. Store outside source
(`NQ_EXPERIMENT_STORE`, default ignored `results/terminal`). Jobs are in-memory;
completed artifacts survive restart, but an interrupted job must be resubmitted.

Replay endpoints filter by explicit aware UTC cutoff and omit all outcomes,
baselines, full-sample counts, metrics, coverage and provenance. The research UI
hides history/comparison/provenance, disables execution and clears pending chart
content immediately while a replay request resolves. Main-chart replay unmounts
the research result pane and requests only causal markers. Future drawings are
handled by the preserved v0.2 drawing implementation. Replay is a display and API
response contract, not an access-control boundary against a person independently
opening a completed artifact.

## Run

Existing historical chart setup and launch remain as documented in README.
Research is blocked by default. For an explicit formula-only software demo:

```sh
# Integrated terminal; use separate processes, no NQ_DATA_ROOT required for demo.
NQ_RESEARCH_DEMO=1 NQ_EXPERIMENT_STORE=/tmp/nq-experiments \
  .venv-terminal/bin/python -m uvicorn terminal.api:app --host 127.0.0.1 --port 8000
cd terminal/web && npm run dev
# Open http://127.0.0.1:3000, then Strategy Research.
# Market chart stays disconnected unless the separately licensed release is configured.
```

Or run only the shared research software demo, without frontend dependencies:

```sh
python3.12 -m backtester.terminal.server --demo --store /tmp/nq-experiments
# Open http://127.0.0.1:8765
```

Never use demo flags on a session intended for historical experiment execution.
Synthetic provenance and a persistent synthetic banner accompany every demo run.

## Validation commands

```sh
python -m pytest tests terminal/tests -q
python scripts/check_source_boundary.py
cd terminal/web
npm run typecheck
npm run build
# With the demo API and frontend running:
npm run test:smoke -- research.spec.ts
# Existing v0.2 drawing geometry unit regression needs no market data:
npm run test:smoke -- v02.spec.ts -g 'price/time projection'
```

`tests/test_terminal_research.py` covers signal prefix invariance under future
mutations, weighted VWAP/reset, objective event conditions, observation eligibility,
late publication, sealed holdout, chronological partitions, forbidden parameter
controls, chart alignment, forward horizons, cost timing, matched controls,
bootstrap availability, immutable reproducibility, integrity failures, API job
execution/replay and historical rejection before market reads. Browser smoke
covers the integrated iframe, execution, chart rendering, history, comparison,
replay visibility, cursor advance, holdout errors and browser exceptions.

Licensed historical API/browser regression cases require an explicitly configured
release; they were not run against market files in this task. Optional provider,
JSON Schema and matplotlib checks can skip when dependencies are absent. See the
validation results appended below for exact outcomes.

## Validation results — 2026-11-06

- Full Python regression: **378 passed, 36 skipped**, one upstream Starlette/httpx
  deprecation warning. Skips: 31 licensed-release integration cases without
  `NQ_DATA_ROOT`, two absent Databento dependency checks, one live-provider opt-in,
  one optional JSON Schema check and one optional matplotlib rendering check.
- Research desktop integration, mobile results layout and existing v0.2
  price/time/drawing replay geometry: **3 browser tests passed**. No browser
  exceptions. Chromium was run outside the sandbox because macOS disallowed its
  sandboxed Mach service registration.
- TypeScript typecheck: passed, including after final responsive layout changes.
- Next.js production build: passed. JavaScript syntax check: passed.
- Existing reachable-history source-boundary check: passed (172 blobs).
  Additional pending-source scan: 40 new files, zero disallowed paths, binary
  contents or credential patterns. `git diff --check`: passed.
- Final desktop/mobile QA corrected mobile grid overflow; a 390px viewport now
  stays within 390px. The research chart axis uses ET.

The original historical browser cases were not run: they require licensed market
inputs and would inspect actual observations. No empirical result is claimed.
The displayed software-demo metrics describe formulas, not the NQ market.
