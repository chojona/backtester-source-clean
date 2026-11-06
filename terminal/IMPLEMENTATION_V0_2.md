# NQ Research Terminal v0.2 — implementation and verification

Delivered 2026-11-06. The production preview was verified on local ports 3102 (frontend) and 8102 (read-only API). Both servers were stopped after verification at the user’s request.

## Baseline and preserved integration

This worktree began at `b998421`, before the terminal existed. The existing v0.1 implementation was recovered from local branch `codex/nq-quant-research-terminal` (`8342c84`), including its original API, dataset adapter, launcher, dependency lock, tests, and narrow source-publication allowances. The v0.2 changes extend that implementation. The offline volatility viewer and core backtester were left unchanged.

The service still verifies the six consumed sealed release artifacts, queries DuckDB in memory against external Parquet, requires exact contract/selected-contract identity and `eligible_full_session IS TRUE`, reconciles manifest counts, and enforces the exact prior-candidate context gate. No source dataset, certification rule, trust registry, or research adapter was modified. No synthetic market data, order flow, brokerage integration, or market-data acquisition was added.

## Workspace

- Fullscreen uses the existing chart instance and includes replay controls.
- Pointer and keyboard dividers resize the chart and analytics sidebar. The bottom workspace has a native resize handle and accessible divider.
- Analytics and Workspace collapse independently; the indicator manager and drawing objects use collapsible panels.
- Globex/RTH display is server-side. RTH filters eligible observations to [09:30,16:00) ET before aggregation, statistics, and VWAP; it anchors candles at the RTH open. It does not alter eligibility or the observed-minute replay cursor.
- Local persistence covers contract, session, timeframe, display, layout dimensions, panel visibility, indicator configuration, and chart time windows. Chart time windows are stored per contract/session/timeframe/display, with replay viewports kept separately. Large replay jumps bring the current bars into a readable window; ordinary playback follows the right edge when it is already in view and respects panning away from that edge. Resizing locks the visible time range rather than remounting or resetting the chart.
- Missing, malformed, or unavailable local storage falls back safely. Write failures produce a visible message.

## Drawings

Horizontal line, horizontal ray, trendline, rectangle, Fibonacci retracement (0, .236, .382, .5, .618, .786, 1), and price range are implemented in a price/time overlay. Price range shows points and percentage change.

Stored anchors are UTC seconds and prices, never screen pixels. Rendering reprojects through the chart's time and price scales, including interpolation when an anchor falls between coarser candles. Select objects on the chart or in Objects; drag handles or edit UTC/price anchors. Hide/show and deletion are supported.

Storage is scoped by contract, session date, and Globex/RTH context, independently of timeframe. Each drawing also records its creation cutoff. Rewinding hides later-created objects and objects with future anchors from both the chart and object editor.

## Indicators

Session VWAP, exact previous-session high/low, configurable opening-range high/low, VWAP deviation bands, and session boundaries support visibility, colors, and solid/dotted/dashed styling.

VWAP retains the v0.1 cumulative HLC3 × volume / volume definition. Bands use a stable incremental volume-weighted population variance of observed one-minute HLC3; deviations range from .25 to 5. Opening range starts at 09:30 ET and spans 1–120 minutes (default 30), with developing state preserved. Indicators on aggregated candles use their last available source-minute value.

The plotted previous high/low and analytics sidebar use the same snapshot fields. RTH previous extrema are calculated only after the original exact prior-candidate completeness and availability gates pass. No roll or skipped-date context is substituted.

## Replay and causality

- Speeds: 1×, 2×, 5×, 10×. Existing one-minute stepping remains available; Bar → advances one selected timeframe of observed minutes, capped at session end.
- HH:MM ET jumps resolve on the server to an observed-minute cursor, including the evening belonging to the selected futures session. The lookup returns a cursor, not future prices.
- Space plays/pauses, → steps a bar, F toggles fullscreen, Escape cancels drawing placement, and Delete removes a selected object.
- The existing SQL availability predicate filters completed one-minute observations before all aggregation, statistics, VWAP, bands, and opening-range calculations. Higher-timeframe developing candles contain only those completed source minutes.
- Chart, analytics, and Explorer continue to consume one atomic snapshot. Explorer follows the page containing the replay cursor. Stale selection requests remain aborted; jump requests are cancellable.

## Verification

- Research and source-boundary suite: **388 passed, 3 skipped**. The skips are the existing optional SDK/live-provider checks; no live test was enabled.
- Terminal backend: **32 passed** against the existing licensed sealed release. All 26 original backend tests are preserved, with six v0.2 regression tests added.
- Frontend: **TypeScript check passed** and **production Next.js build passed**.
- Browser suite against the production build: **5 passed**, covering the two preserved smoke tests, drawing projection/annotation availability, the full v0.2 real-data workflow, and unavailable local storage.
- Publication boundary check passed across all reachable history; whitespace/diff checks passed. The narrow terminal source allowances were recovered with v0.1; data/artifacts remain excluded.

New checks independently recompute deviation bands, opening-range extrema, and RTH previous-session levels from actual source/context rows. They test RTH daily aggregation, empty pre-RTH prefixes, replay cutoff equivalence, API parameter validation, indicator/snapshot consistency, and time jumps.

Browser coverage creates all six drawings, edits anchors, hides/deletes objects, changes timeframe and zoom, resizes panels without changing the saved chart range, reloads persisted state, switches Globex/RTH, checks annotation hiding on rewind, steps bars, jumps time, verifies Explorer's last visible candle, uses shortcuts/fullscreen, checks that a time jump brings the cursor into view, and restores collapsed panels. Original error recovery and 390px responsive checks remain passing.

Screenshots are generated under `terminal/web/test-results/`: `v02-workspace.png`, `v02-replay.png`, `v02-fullscreen.png`, and the preserved mobile screenshot. Delivered copies are linked from the completion message. They show the actual sealed historical release, not demo candles.

## Running and reproducing

See [README](README.md) for installation and the existing launcher. The local ignored `.env` points to the already-existing release; no market records are bundled. For a fresh build using the launcher's default ports, run `npm run build` without a custom `NQ_API_URL`.

```sh
python -m pytest tests terminal/tests -q
cd terminal/web
npm run typecheck
npm run build
# With frontend/API running (default http://127.0.0.1:3000):
npm run test:smoke
# Alternate preview port:
TERMINAL_URL=http://127.0.0.1:3102 npm run test:smoke
```

Historical backend tests require `NQ_DATA_ROOT`; existing browser executable overrides remain supported. Playback delay excludes API latency, as in v0.1. Retrospective eligibility is unchanged and remains distinct from strict historical certification.
