# Phase 1 chart foundation verification

## 1. Baseline reconciliation

GitHub redirected the checkout's configured remote to
`chojona/backtester-source-clean`. The fetch advanced `origin/main` from
`ada63a6b75242ff5461bc1ec95b6dc4553373e35` to
`d7470d49a2dd0753c0437eb718eb09801ced5fe8`. PR #6 had already merged the
secondary worktree's three commits `be15c24`, `69ac1f7`, and `fa93370`.
`phase1/chart-foundation` starts at the merge. The primary worktree is
detached at `b998421` and contains unpublished v0.3 source. Both source
worktrees retain their original state. [Merged integration](https://github.com/chojona/backtester-source-clean/pull/6)

| Source and ownership | File inventory and disposition |
| --- | --- |
| Primary tracked edits | `.gitignore`, `README.md`, `scripts/check_source_boundary.py`, and `setup.py`. Main already provides terminal artifact exclusions, updated v0.3 documentation, terminal source allowlisting, and packaged research assets. Retained main's versions. |
| VWAP research workspace | `backtester/terminal/{__init__.py,app.js,index.html,research.py,server.py}`, `terminal/research_api.py`, `terminal/web/components/ResearchOverlay.tsx`, `tests/test_terminal_research.py`, and `terminal/tests/test_research_api.py`. The merged implementations retain the constructed execution demo and historical certification gate. |
| Continuous prices and review metadata | `terminal/{api.py,continuous.py,continuous_data.py,CONTINUOUS.md,IMPLEMENTATION_V03.md}`, `terminal/web/components/{ContinuousOverlay,ContinuousQuality,Drawings,Explorer,MarketChart,Terminal}.tsx`, `terminal/web/{app/globals.css,lib/continuous.ts,lib/types.ts}`. Compared the primary versions with the secondary integration and kept the merged seal checks, independent blocks, 20-session navigation, full daily view, and UI fixes. |
| Continuous tests and CI | The primary untracked `tests/test_continuous_terminal.py` was superseded by `terminal/tests/test_continuous_terminal.py`, `terminal/tests/serve_synthetic.py`, `terminal/web/tests/{continuous,intraday,research}.spec.ts`, and `.github/workflows/terminal.yml`. Retained the merged variants and existing v0.2 documentation. |
| Ignored local files | Local environment files, dependency trees, caches, generated browser output, and the two external sealed datasets stayed outside Git. |

`git diff --name-status ada63a6..d7470d4` lists every inherited change.
Before Phase 1 edits the source boundary passed across 223 blobs, the core
suite returned 401 passed and 3 skipped, and the terminal returned 13 passed
and 31 skipped offline and 44 passed with both seals configured. TypeScript
and the production Webpack build passed. Turbopack's CSS worker hit a local
subprocess port restriction. The browser runner initially reported a missing
Playwright-pinned browser. The subsequent browser lanes use the existing
Chromium executable and the same production Next.js app.

## 2. Historical window API

Changed `terminal/api.py`, `terminal/chart_window.py`, `terminal/data.py`,
`terminal/continuous_data.py`, and `terminal/tests/test_chart_window.py`.

`GET /api/chart/window` accepts a session date for the initial request and
a signed cursor for later pages. It preserves whole trading sessions and caps
responses at 2,500 displayed candles. A 1m Globex page can contain a single
full session, with an earlier or later cursor for the adjacent one. Intraday
pages consider at most 20 trading dates. Continuous daily pages consider up
to 250 dates, with daily OHLCV and HLC3 VWAP aggregated in DuckDB.

Exact-contract queries preserve eligibility, exact contract predicates and
previous-session context checks. Continuous queries preserve source contract,
roll and adjustment block identity and return reviewed gap metadata, including
empty or excluded sessions. RTH queries retain the established aggregation
anchors. Window queries share the existing aggregation logic and avoid building
full snapshot payloads for every selected session. No observations are
generated for missing minutes. Exact-contract gaps outside admitted sessions
remain outside the series. Continuous gap classifications describe the
release's reviewed Globex intervals and include a truncation flag.

The cursor binds the verified source and derived artifact identities, contract,
frame, display, indicator parameters, cutoff and page configuration. Cursors
expire on API restart and are valid within the issuing worker. The supported
local deployment uses a single worker. `as_of` applies the observation-close
convention in the query. Raw cutoff requests omit retrospective roll overlap
details and session quality flags. Adjusted history is retrospective and the
API rejects cutoff requests for it. The startup seal checks validate artifact
hashes. The window endpoint also checks file identity before and after a page
and rejects changed files until restart. Both stores require immutable local
release directories.

## 3. Incremental chart history

Changed `terminal/web/lib/{chartWindow,types,useChartHistory}.ts`,
`terminal/web/components/{ContinuousQuality,MarketChart,Terminal}.tsx`, and
`terminal/web/tests/{continuous,intraday,terminal}.spec.ts`. Removed
`terminal/web/lib/useIntradayHistory.ts`.

The browser requests a selected-session snapshot for analytics, the explorer
and replay. The chart's historical controller separately loads the visible
series using cursor pages. It requests an initial page immediately and
collects the remaining startup pages before a single update. The default
targets 20 sessions. A 30,000-candle and 32-page cache cap takes precedence
over larger intraday presets. Full continuous daily mode traverses the
available history through bounded pages. For this release it covers 4,262
declared sessions, including gaps. Older and newer loads preserve the visible
UTC range while retaining complete pages, with direction-aware eviction and
cursors on both retained edges. Viewport changes during a user pan trigger
edge loads. A failed load offers retry and history reload. When the selected
window is empty, directional buttons allow navigation.

Candles, volume and indicators update on the same time scale. The chart
instance stays mounted while history and layouts change. Replay displays
snapshots authorized for the current contract, date, display, frame and
replay prefix. The chart hides observations and anchors beyond the replay
cutoff while a rewind is pending.

## 4. Workspace hardening

Changed `terminal/web/lib/workspace.ts`,
`terminal/web/components/{Drawings,MarketChart,Terminal}.tsx`,
`terminal/web/app/globals.css`, and
`terminal/web/tests/{v02,workspace}.spec.ts`.

Version 3 workspace records carry layout, fullscreen, history preferences,
indicators, viewport and drawings. Legacy v2 settings and unadjusted drawings
migrate on read. Drawings are keyed by contract, display and verified release
and build identity. Adjusted anchors also require a matching adjustment block
on both ends. Legacy adjusted drawings remain in their original storage keys
because those records have no build or block identity. UTC and price anchors
persist across timeframe changes. A reloaded browser can restore the app's
fullscreen layout. Native browser fullscreen requires a user gesture.
Storage errors preserve usability and in-memory settings for the visit.

## 5. Verification and release

Changed `.github/workflows/terminal.yml`,
`terminal/tests/benchmark_chart_window.py`, `terminal/web/tests/research.spec.ts`, `terminal/README.md`,
`terminal/CONTINUOUS.md`, this report, and `docs/{ARCHITECTURE,DEVELOPMENT}.md`.
Public CI runs the terminal backend and production browser suite using
formula-generated temporary Parquet, with external data roots absent.
The separately configured local lane verifies the sealed artifacts and
runs release-only assertions.

The initial hosted push run reached the mobile research test's five-second
assertion timeout while the constructed experiment was still running. The
test now waits up to 30 seconds for the same completion state.

| Feature | Verification |
| --- | --- |
| Exact, Raw and Adjusted with all six frames and both displays | Constructed API-to-snapshot reconciliation, weighted VWAP calculation, release-backed page cap and edge checks |
| Signed cursors, observation cutoff and adjusted blocks | API tampering, restart, configuration, cutoff, seal-change, unresolved-roll and empty-session checks |
| Bidirectional loading, overlapping records and rapid switching | Production Playwright in the constructed and release lanes |
| Workspace, drawings and replay | Production Playwright migration, fullscreen, resize, storage denial, time/price projection, replay cutoff and workspace regressions |
| v0.3 VWAP workspace and v0.2 behavior | Production browser research demo, explorer and replay suites and offline research tests |
| Full continuous daily history | Production browser verifies 4,262 declared sessions, the roll overlay, responsive chart layout, quality pagination and restoration after an intraday switch |

### Local results

| Verification lane | Result |
| --- | --- |
| `python scripts/check_source_boundary.py` | Passed |
| `python -m pytest -q tests` with offline test dependencies | 403 passed, 1 live opt-in skip with the optional Databento SDK installed. |
| `python -m pytest -q terminal/tests` without external roots | 68 passed, 32 release-dependent skips |
| `python -m pytest -q terminal/tests` with both sealed roots | 100 passed |
| `npm run typecheck` and `npm run build -- --webpack` | Passed |
| `NQ_BROWSER_FIXTURE=1 npm run test:smoke` | 10 passed, 7 release or benchmark skips |
| `NQ_BROWSER_RELEASE=1 NQ_BROWSER_BENCHMARK=1 npm run test:smoke` | 13 passed, 4 fixture-only skips. The research demo used its formula-only inputs. |

### Performance

Reference machine is a Mac16,1 with Apple M4 and 16 GiB RAM on macOS 26.6.2.
Python 3.12.13, DuckDB 2.0.0, Node 22.23.2, Next.js 16.4.5, Playwright
1.57.0, and headless Chromium 145.0.7632.6 were used. The API probe measures
30 sequential warm ASGI requests per configuration, including serialization.
It excludes cold seal hashing, network, Next.js proxy and browser rendering.

| Sealed-release API configuration | p50 | p95 | Peak candles |
| --- | ---: | ---: | ---: |
| Exact 1m Globex | 121.4 ms | 122.8 ms | 1,380 |
| Exact 15m RTH | 121.9 ms | 124.4 ms | 208 |
| Raw 1m Globex | 155.6 ms | 157.5 ms | 1,365 |
| Raw 5m RTH | 215.2 ms | 221.5 ms | 1,560 |
| Adjusted daily Globex | 136.5 ms | 141.1 ms | 247 |

All sampled warm API configurations met the 500 ms preliminary p95 target.
The formula-only probe covered the same configurations with p95 from 54.2 ms
to 83.0 ms. Fixture sessions are intentionally short, so release-backed
results are the reference for performance.

The Chromium probe loaded the 20-session Raw 1m startup window in 5.20 s from
session selection, with the selected session chart rendered during startup.
It observed 28,980 candles at peak across four older and four newer pans,
59 MiB retained JS heap after startup and 70 MiB after the pans, measured
after a forced GC through CDP. The slowest measured pan was 1.43 s including
Playwright input and assertion overhead. The largest synchronous chart
`setData` batch was 309.6 ms. These single-run figures include concurrent
local verification workload and exclude native browser memory. Multi-page
startup and rendering near the cache ceiling remain the largest costs.

### Provenance and independent review

- Source `nq-ohlcv-research-v2.0.0`, terminal release ID
  `317ea36e24750da31646389e42c0e99beb7bf8454f387e8c0a6faeaafc8e5fcf`.
  Sealed summary SHA-256
  `ca43f1999f851419ab6a73a3dd0d167c75288b4f921be259cc8791234ea4a0f9`.
- Continuous build ID
  `293da8df59935a798eaaaf26aa72d59e80d0c9dd3fccb97e74395dde8e15b123`.
  Verified output-set ID
  `62b2c96fea3857c8dc58255bb5afc49c7c58ac24aeaf74770480a40b278304f6`.
- Sealed observations retain retrospective QC eligibility. Strict historical
  certification remains unresolved, and historical VWAP execution remains
  **NO-GO**. M1-R independent acceptance and EXP-001 v0.2 independent review
  remain pending separately. [Research review status](../docs/RESEARCH_REVIEW_STATUS.md)

### Reproduce

From the repository root, install the documented Python and frontend
dependencies and run the [terminal verification commands](README.md#verification).
Run the offline checks and API probes from the repository root. Use Python
3.12 for the pinned dependencies.

```sh
python -m pip install -e '.[test]' -r requirements-databento.txt -r terminal/requirements.txt
python scripts/check_source_boundary.py
env -u BACKTESTER_LIVE_TESTS -u DATABENTO_API_KEY python -m pytest -q tests
python -m terminal.tests.benchmark_chart_window --synthetic --samples 30
# After exporting both validated dataset roots
python -m terminal.tests.benchmark_chart_window --samples 30
# With production Next.js and the release API running
cd terminal/web
NQ_BROWSER_RELEASE=1 NQ_BROWSER_BENCHMARK=1 npm run test:smoke -- intraday.spec.ts -g 'repeated history'
```
