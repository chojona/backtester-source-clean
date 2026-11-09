# Phase 2 auction analytics verification

Verified November 9, 2026, America/New_York. GitHub reported PR #7 merged at
`7b13ccab572f386902971f1ba28ae743bcd5bc22`, the fetched `origin/main` and
base of `phase2/auction-market-theory`. Inspected the status of all registered
worktrees, including ignored and untracked entries. Phase 2 uses the clean
task worktree. [Phase 1 merge](https://github.com/chojona/backtester-source-clean/pull/7)

## Milestones

| Milestone | Files and decisions | Verification and limits |
| --- | --- | --- |
| M0 · `e54cbf1` | `docs/AMT_METHODOLOGY.md`. Audited terminal API, exact and continuous stores, chart windows, workspace, Phase 1 verification and dataset bindings. Reconciled the 1,365- and 1,380-minute ordinary Globex regimes. | Source schema and eligible regime boundaries inspected. Dated exceptions remain uncertified. |
| M1 · `d89f879` | `terminal/amt/{model,source,profile,api}.py`, API router and profile tests. Integer NQ ticks, exact-rational uniform allocation, conserved millionth-unit transport, deterministic value area, nodes and model sensitivity. | 19 initial tests. Both estimators reconcile independently to sealed one-minute observations. |
| M2 · `11fef6e` | `terminal/amt/tpo.py`, TPO route and tests. UTC elapsed periods from ET display open, merged ranges, RTH Initial Balance. | 4 initial tests. DST, missing and partial periods, overlapping ranges and tie handling. Occupancy estimates use observed bar ranges. |
| M3 · `d3c4115` | `terminal/amt/vwap.py`, scoped reader, VWAP route and tests. Weighted population bands, inclusive manual anchor and output filtering after accumulation. | 3 initial tests. Zero weights, disconnected minutes, repeatable output slices and adjusted cutoff rejection. |
| M4 · `ae8f06f` | `terminal/amt/context.py`, calendar scopes, capabilities and context route. Incompatible prior levels are suppressed. | 5 initial tests. Composites distinguish declared, admitted and excluded sessions. No publication evidence is inferred from them. |
| M5 · `7dfe5d9` | `AuctionTools.tsx`, `AuctionOverlay.tsx`, `amt.ts`, `MarketChart.tsx`, CSS and Playwright. One canvas primitive uses the existing chart transforms and visible chart data. The selected snapshot supplies replay cutoffs. | Fixture tests exercise anchor selection and editing, timeframe changes, persistence, replay and delayed requests. The release lane measures retained heap and bounded drawing work. |
| M6 | Shared store dependencies, grouped rational allocation, source/roll/cutoff adversarial tests, five independent release reconciliation tests, API benchmark, synthetic CI and documentation. | Local results below. License-dependent inputs are read through the same verified stores; the fixture lane builds temporary formula-only artifacts. |

## Source inventory and identity

| Source | AMT use |
| --- | --- |
| v2 `SUCCESS.json`, `summary.json`, `input-bindings.json` | Verified by the existing store and represented by the release identity. |
| v2 `research.parquet` and `session-eligibility.parquet` | Exact-contract minute observations, session membership, retrospective eligibility, ordinary calendar and prior candidate date. |
| v2 `selected-observations-with-flags.parquet` and `contract-rolls.parquet` | Continuous build inputs bound to the source release. |
| Continuous `raw.parquet` and `adjusted.parquet` | Observations and source contract, segment, roll, offset and adjustment block lineage. |
| Continuous copied eligibility and `selected-gap-intervals.parquet` | Reviewed Globex coverage. Gap intervals are clipped by the request cutoff. |
| Continuous seal and roll, adjustment and quality manifests | Output-set identity, decision boundaries, independent block lineage and unresolved rolls. |

The methodology is `amt-ohlcv-v1`. Verified source is
`nq-ohlcv-research-v2.0.0`, release ID
`317ea36e24750da31646389e42c0e99beb7bf8454f387e8c0a6faeaafc8e5fcf`.
Continuous build
`293da8df59935a798eaaaf26aa72d59e80d0c9dd3fccb97e74395dde8e15b123`,
output-set ID
`62b2c96fea3857c8dc58255bb5afc49c7c58ac24aeaf74770480a40b278304f6`.
Response envelopes expose the relevant output hashes and per-session lineage.
Temporary formula-only seals are regenerated per test run. The data roots
and sealed trust registries stayed read-only.

## Verification results

| Lane | Result |
| --- | --- |
| Offline backtester suite | 403 passed, 1 skipped. The skipped Databento test requires explicit live opt-in and an API key. |
| Terminal backend without roots | 106 passed, 37 skipped. All skips require an external release. |
| Terminal backend with both roots | 143 passed, including 43 AMT tests. |
| Source boundary and whitespace | Passed. |
| TypeScript and Next.js production Turbopack build | Passed. |
| Production Chromium, constructed fixture | 12 passed, 8 release-only skips. |
| Production Chromium, sealed release and benchmark | 14 passed, 6 fixture-only skips. |
| Final AMT-only browser rerun | Constructed 2 passed and 1 release-only skip. Release 1 passed and 2 fixture-only skips. |
| UI evidence | Playwright captured the constructed profile, TPO letters, and edited anchored VWAP. The screenshot is a local artifact outside the source repository. |

### Reproduce

Use Python 3.12.13, DuckDB 2.0.0 and FastAPI 0.162.0 for the local terminal
lanes. Frontend versions were Node 22.23.2, Next.js 16.4.5, Playwright 1.57.0
and Chromium 145.0.7632.6 on Apple Silicon macOS 26.6.2. The local offline
environment added a read-only site-packages directory for `jsonschema`;
installing the test extra in one environment removes that step.

From the repository root, use `core_python` and `terminal_python` for the
corresponding Python executables. Supply `NQ_DATA_ROOT` and
`NQ_CONTINUOUS_ROOT` only for the release lanes.

```sh
env -u BACKTESTER_LIVE_TESTS -u DATABENTO_API_KEY "$core_python" -m pytest -q tests
# Local run with the separately installed schema dependency
env -u BACKTESTER_LIVE_TESTS -u DATABENTO_API_KEY "$core_python" -c \
  'import site,sys,pytest; site.addsitedir(sys.argv[1]); raise SystemExit(pytest.main(["-q","tests"]))' "$schema_site"
env -u NQ_DATA_ROOT -u NQ_CONTINUOUS_ROOT "$terminal_python" -m pytest -q terminal/tests
"$terminal_python" -m pytest -q terminal/tests
"$terminal_python" scripts/check_source_boundary.py
git diff --check
"$terminal_python" -m terminal.tests.benchmark_amt --synthetic --samples 30
"$terminal_python" -m terminal.tests.benchmark_amt --samples 30
"$terminal_python" -m terminal.tests.benchmark_chart_window --samples 30
(cd terminal/web && npm ci && npm run typecheck && npm run build)
```

For browser checks, start the API and Next.js in separate shells. The release
browser lane opts into the existing formula-only research demo using a temporary
experiment store. That demo uses constructed inputs and never the sealed
historical market rows. Set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to a compatible
installed browser or run `npx playwright install chromium`.

```sh
# Constructed API
"$terminal_python" -m terminal.tests.serve_synthetic
# Release API instead, with both sealed roots exported
NQ_RESEARCH_DEMO=1 NQ_EXPERIMENT_STORE="$(mktemp -d)" \
  "$terminal_python" -m uvicorn terminal.api:app --host 127.0.0.1 --port 8000
# Web server
(cd terminal/web && npm run start)
# Run the matching lane
(cd terminal/web && NQ_BROWSER_FIXTURE=1 npm run test:smoke)
(cd terminal/web && NQ_BROWSER_RELEASE=1 NQ_BROWSER_BENCHMARK=1 npm run test:smoke)
# Optional constructed screenshot
(cd terminal/web && NQ_BROWSER_FIXTURE=1 NQ_AMT_SCREENSHOT=/tmp/auction-tools.png \
  npm run test:smoke -- amt.spec.ts -g 'auction controls persist')
```

## Performance

ASGI probes used 30 sequential warm requests per configuration including
serialization. Cold seal hashing, the HTTP proxy and browser rendering are
outside these figures. Price rows are bounded at 4,096, observations at
46,500 and TPO representation at 24,000 merged intervals.

| Sealed AMT route | p50 | p95 | Output rows or points | Source minutes | Bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Exact session Globex uniform + sensitivity | 66.3 ms | 68.0 ms | 308 | 1,380 | 22,436 |
| Exact session RTH TPO letters | 48.7 ms | 49.3 ms | 160 | 390 | 14,248 |
| Raw session Globex HLC3 | 84.1 ms | 88.0 ms | 299 | 1,380 | 27,859 |
| Adjusted month Globex uniform | 382.1 ms | 397.5 ms | 508 | 28,980 | 48,211 |
| Adjusted month RTH VWAP | 390.7 ms | 413.0 ms | 8,190 | 8,190 | 1,824,459 |
| Exact session RTH context | 116.6 ms | 118.3 ms | — | 390 | 4,480 |

The constructed API probe ranged from 39.2 to 71.9 ms p95. Its largest
profile had six rows and its largest VWAP had 360 points. The short fixture
sessions exercise the API paths but are unsuitable for release sizing.

| Phase 1 chart-window path | Published p95 | Phase 2 rerun p95 | Peak candles in rerun |
| --- | ---: | ---: | ---: |
| Exact 1m Globex | 122.8 ms | 130.3 ms | 1,380 |
| Exact 15m RTH | 124.4 ms | 131.4 ms | 208 |
| Raw 1m Globex | 157.5 ms | 190.1 ms | 1,365 |
| Raw 5m RTH | 221.5 ms | 259.5 ms | 1,560 |
| Adjusted daily Globex | 141.1 ms | 155.7 ms | 247 |

The rerun used the existing chart endpoint and benchmark. These are separate
measurements from the published Phase 1 run. All five stayed below its 500 ms
p95 target.

The release browser AMT probe retained 27,600 chart candles. Enabling the
profile returned a visible result in 156 ms. Heap after forced GC was 51 MiB
before AMT and 53 MiB with profile, TPO and weekly VWAP enabled. One sampled
zoom update took 48 ms including automation overhead. Its primitive draw
took 2.7 ms and submitted 4,262 work items across price rows, period ranges
and band vertices. Enabling the overlays did not increment chart `setData`.
The final AMT-only rerun measured 145 ms profile response-to-display, 42 ms
zoom probe time and 2.6 ms drawing, with the same heap and work counts.

| Raw 1m 20-session history benchmark | Phase 1 reference | Phase 2 |
| --- | ---: | ---: |
| Startup | 5.20 s | 5.20 s |
| Peak candles | 28,980 | 28,980 |
| Initial / post-pan retained JS heap | 59 / 70 MiB | 59 / 71 MiB |
| Slowest of eight pans | 1.43 s | 1.57 s |
| Largest synchronous chart batch | 309.6 ms | 293.4 ms |

The chart-history comparison uses single local runs with AMT off, while the
AMT browser probe compares off and on in one session. Browser timings include
Playwright scheduling and omit native browser memory. See
[Phase 1 verification](PHASE1_VERIFICATION.md#performance) for the reference.

## Risk register and scientific gates

| Risk or boundary | Handling |
| --- | --- |
| True volume at price and traded TPO occupancy are unavailable. | Classifications explicitly identify OHLCV estimates. The sensitivity response exposes changes between the two permitted allocation models. Trade-exact remains reserved. |
| Historical publication timing and dated calendar exceptions remain unresolved. | Replay filters closed observations and labels retrospective admission. Partial, excluded and unsupported grids stay visible in coverage. |
| Roll jumps and incompatible adjusted blocks can distort composites. | Raw scopes reject mixed segments. Adjusted scopes reject independent blocks and causal requests. Compatible adjusted blocks retain every contributing contract and offset. |
| Long periods can generate large VWAP payloads or wide profile ranges. | All scopes are bounded. VWAP supports trimming output after accumulating the prefix. Wider profile rows fit a broader price span. |
| Rendering varies with zoom and browser hardware. | The primitive clips to the pane, caps letter drawing work and decimates wide visible VWAP paths. Letters fall back to blocks at small cell sizes. |
| Historical certification and research authority remain pending. | Strict historical certification is **NO-GO**. Independent M1-R acceptance and EXP-001 v0.2 review remain separate. Phase 2 adds no historical signal study, execution test, profit experiment or live execution authority. |

See [AMT methodology](../docs/AMT_METHODOLOGY.md) and
[research review status](../docs/RESEARCH_REVIEW_STATUS.md).
