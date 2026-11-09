# Continuous NQ chart series v1.0.0

Continuous files are derived chart artifacts, stored outside this repository.
Original cleaned contract files, research v2.0.0 files and certification gates
are never written. The terminal adds **NQ1! Raw** and **NQ1! Adjusted** alongside
its existing outright contract selector.

## Policy and source binding

`nq-v2-fixed-monday-v1` freezes the v2.0.0 policy exactly: switch at the session
open on the Monday before the nominal third Friday. The date-only function is
independent of retained bars, volume, open interest or subsequent market prices.
The builder compares every session's selected contract and transition flag to
that function and compares the resulting transition dates/contracts to the
sealed roll manifest. It refuses a changed policy rather than migrating it.

All 66 transition dates are Mondays, so their decision boundary is Sunday
18:00 America/New_York, including DST. This rule is a retrospective adoption of
a fixed calendar policy, not proof of an official historical lead designation
or that this particular policy was declared before the historical period.
The existing ordinary-calendar restrictions and retrospective QC flags remain.

The v2 release seal binds all consumed research artifacts. Its input bindings
also bind the cleaned outright Parquet and its seal. Every selected OHLCV record
is reconciled field-for-field against the cleaned `(timestamp, contract)` record.
No independently unreviewed hash seal is promoted to strict certification.

## Overlap and adjustment convention

`prior-overlap-close-v1` uses the latest synchronous positive-volume old/new
one-minute bar before the roll's decision boundary, within seven calendar days.
Its bar close must be strictly before that boundary. The latest five paired
observations must be consecutive minutes, finite and positive; otherwise the
roll remains unresolved. No fallback to a different timestamp convention,
settlement, interpolation or assumed zero spread is permitted. Evidence records
include all five timestamp/price/volume pairs and their SHA-256.

The gap is `new reference close - old reference close`. Backward adjustment adds
that gap to every earlier OHLC in its adjustment block. All four OHLC fields use
exactly the same offset; volume and timestamps stay unchanged. Example: old close
100 and new close 110 imply +10 to the earlier segment and zero to the newer one.
It removes the documented reference spread, not every subsequent price move.

An unresolved roll splits the series into independently anchored blocks. Each
block's newest segment has offset zero; supported spreads accumulate backward
within that block. This is a local price coordinate, not an invented adjustment
across the unresolved link. `global_adjustment_offset` remains null for earlier
blocks that cannot be reconciled to the latest overall anchor. The adjusted
chart explicitly retains/marks these unresolved discontinuities. A single fully
adjusted history cannot be honestly constructed across those links.

Adjustment manifests distinguish local offset, global offset, block ID and
status. Adjusted files are **retrospective**, because historical prices use
subsequent roll information. Adjusted replay and `as_of` requests fail explicitly;
use Raw for causal observed-bar replay. The terminal disables adjusted replay.

## Files and reproducibility

The version directory contains:

- `raw.parquet`: every observed v2-selected minute, including ineligible sessions,
  with untouched OHLCV, original contract, segment/roll IDs and zero offset.
- `adjusted.parquet`: identical observations/volume plus additive OHLC, raw OHLC,
  adjustment status, offset, block ID and nullable global offset.
- `rollover-manifest.json`: frozen policy, exact input hashes, code/runtime
  identity, decisions and overlap evidence for every transition.
- `adjustment-manifest.json`: convention and per-segment local/global offsets.
- `quality-report.json`: source reconciliation, exclusions, missing intervals,
  unresolved overlaps, independently anchored blocks and limitations.
- Original `session-eligibility.parquet` and `selected-gap-intervals.parquet`
  copied into the external derived directory to bind query-time classifications.
- `SUCCESS.json`: deterministic build identity and output file hashes.

The builder stages a new directory and publishes it by rename. It refuses to
write beneath this source repository, the original release or the cleaned input
root. An existing matching build is verified and reused; changed inputs/code or
damaged output require a different directory. It checks source hashes again at
the end of construction. No market artifacts belong in Git.

```sh
python -m terminal.continuous \
  --release /external/nq-ohlcv-research-v2/build \
  --cleaned /external/nq-ohlcv-clean-v1/cleaned \
  --output /external/nq-continuous-v1.0.0
```

Configure ignored `terminal/.env` (retain existing `NQ_DATA_ROOT`):

```sh
NQ_CONTINUOUS_ROOT=/external/nq-continuous-v1.0.0
NQ_RESEARCH_DEMO=0
```

Launch with the existing `python -m terminal.launch`. The launcher reads this
local file. For separate API/frontend processes, export its variables first.
See README for dependency installation. No auto-download or rebuild occurs.

## Charting, missing observations and eligibility

The continuous symbol's session selector spans all 4,262 declared dates, including
missing/ineligible ones; its source contract changes transparently as dates are
navigated. The Continuous history selector offers one, 20, 120 or all sessions;
long ranges automatically select daily candles. Intraday requests are limited
to 200,000 source observations. Daily aggregation happens in DuckDB.

Every aggregate stays inside one source contract, session and segment, retaining
its roll ID and offset. VWAP and bands reset by session/source contract; indicator
lines break across session/contract/gap boundaries. No artificial roll return is
included in realized-volatility or strategy performance. Continuous realized
volatility is currently unavailable; chart prices are not portfolio returns.

Roll markers show old/new contracts and flag unresolved overlap. The hover
readout shows source contract, raw price, offset, retrospective block, roll ID and
research eligibility. Ineligible candles are muted. Expand the quality notice for
rolls, missing intervals and exclusion reasons. One-minute gaps have whitespace;
higher-timeframe aggregates report source-minute counts without inventing absent
minutes. A missing session produces no candle. Higher-timeframe candles can have
internal omissions; consult the explicit gap/exclusion metadata rather than
interpreting an aggregate as proof of completeness.

Up to 2,000 exact missing intervals are included per snapshot (UI expands the
first 100); `gap_count`/`gaps_truncated` disclose truncation. The paginated endpoint
below exposes remaining exact intervals. Metadata for expected trailing absences
is included in completed historical views; replay reveals it only up to cutoff.
Causal Raw replay covers one selected session at a time; navigate to the next
date to cross a transition. It strips overlap evidence and never fetches backward
adjustment factors. Original drawings and chart controls remain available.

Continuous construction does not grant research eligibility. Both files set
`strict_eligible=false` and `performance_eligible=false`. A convenience
`same_contract_log_return` is populated only for consecutive eligible minutes on
the same source contract and trading date; gaps, rolls and session boundaries are
null. It is not a strategy return series. Research rejects continuous symbols
before reaching the unchanged strict certification gates. Select a separately
certified outright contract for strategy execution.

## API

Existing snapshot/bars/indicators/statistics routes accept the two exact symbols.
`GET /api/snapshot` additionally accepts `history_sessions` (continuous only).
`GET /api/sessions` accepts up to 5,000 dates; continuous sessions retain original
selection/exclusion metadata. Existing outright behavior remains unchanged.

- `GET /api/continuous/intraday` pages by declared trading date on either side
  of an exclusive `anchor`. Pass the exact continuous symbol, direction
  (`older` or `newer`), intraday timeframe and chart settings. The default is
  10 sessions and the maximum is 20. The response identifies its release,
  symbol and session dates, including dates with no bars. Requests with a
  replay cursor or `as_of` are rejected.
- `GET /api/continuous/manifest`: build specification, rolls and quality report.
- `GET /api/continuous/gaps?start=YYYY-MM-DD&end=YYYY-MM-DD&offset=0&limit=500`:
  exact intervals; optional aware `as_of` returns completed intervals only.
- `GET /api/rolls?contract=NQ1!%20Raw`: full historical roll metadata.

Snapshot replay filters bars before aggregation/indicators, restricts decisions
to its cutoff and strips overlap evidence. Completed artifacts/manifest endpoints
are historical inspection tools, not a security boundary against someone opening
full history separately.

## Validation

```sh
python -m pytest terminal/tests/test_continuous_terminal.py -q
python -m pytest terminal/tests -q
cd terminal/web
npm run typecheck
npm run build
# With the API connected to the external continuous build:
npm run test:smoke -- continuous.spec.ts
```

Tests cover fixed selection, chronology, overlaps and missing overlaps, source
OHLCV preservation, local/global adjustment arithmetic, no volume changes,
reproducible files, immutable inputs/output guards, replay restrictions,
indicator separation, eligibility, API integration and strategy-input rejection.
Browser checks cover full-history cross-contract charting, source metadata,
markers, Raw replay, Adjusted replay refusal and unchanged drawing geometry.

## Validated release — 2026-11-06

The completed historical construction retained **5,537,141 observed minutes** on
67 selected source contracts across 4,262 manifest dates, June 2010–October 2026.
The source research release's 2,141,265 eligible bars are unchanged; 3,395,876
additional observed bars remain explicitly ineligible for research. There are
132,766 inherited missing-interval records, with no fabricated replacement bars.

All **66** v2 roll decisions reconcile. **55** have supported overlap under the
fixed five-pair convention; **11** remain unresolved, producing **12 independently
anchored adjustment blocks**. In particular, no globally latest-anchored adjusted
history is claimed for the earlier blocks. The manifests expose every unresolved
link and its reason. This is a limitation of the retained evidence, not a reason
to assume a spread or silently relax the overlap convention.

Validation performed:

- Full Python/source and historical chart API regressions: **417 passed, 5 skipped**.
  Skips are optional Databento/JSON Schema/matplotlib dependencies and live-provider
  opt-in; no live calls were made. One upstream Starlette/httpx deprecation warning.
- All selected frontend regressions: **7 passed**, covering the continuous symbols,
  all 66 visible markers, full history, metadata, replay guards, indicator-line
  separation, original chart/timeframes, drawings/persistence, mobile layout and
  error recovery. No browser exceptions.
- TypeScript and production Next.js build: passed. Source boundary and pending
  source scans: passed. Certification code and production registries unchanged.
- Independent full builds produced identical build identities and every output
  file hash. Build identity:
  `293da8df59935a798eaaaf26aa72d59e80d0c9dd3fccb97e74395dde8e15b123`.
- Independent full-row SQL audit across all 5,537,141 observations found **zero**
  inconsistent OHLC offsets, volume changes, contract identity differences or
  non-null roll-crossing returns. Input files were hash-checked before/after build.

No event strategy research, holdout performance analysis or new historical
certification was performed. These are continuous chart artifacts, not evidence
of a trading edge.

## Chart usability update

The chart now reserves normal layout rows for the symbol/OHLC readout, source
metadata, indicator legend and drawing controls. Price overlays alone occupy
the plot. The header grows on narrow screens rather than covering the plot or
replay controls. The long inline diagnostic dump has been replaced by a native
modal dialog with summary counts, separate rollover/exclusion/gap tabs, pagination
and friendly descriptions. Exact source flags remain in row titles and the
provenance report. Missing intervals are fetched on demand through the existing
paginated endpoint.

Rollover overlays are off by default and can be enabled with **Rollovers**.
When enabled, boundaries are subdued; contract labels appear only when zoomed
in enough to read them. **Fit history** restores time and price autoscaling.
Year ticks display years; month/day labels appear as the user zooms in. Coverage
dates remain visible so yearly ticks cannot be mistaken for January-only data.
Data files, eligibility, adjustments and certification policy are unchanged.

Switching from full daily history to intraday starts with 20 sessions. Pan
near either edge to load 10 more declared sessions per request. The chart
deduplicates timestamps, retains up to 140 sessions and evicts the far edge
when the cache fills. The visible time anchor and drawing coordinates are
preserved across successful loads. If a request fails, **Retry history** keeps
the current chart in place. **D** restores the prior full daily range.

Incremental loading applies to retrospective Raw and Adjusted browsing. Each
mode has its own cache, scoped to the release and chart settings. Selection
changes and entry into replay cancel pending requests. The selected session
still controls replay, analytics, Explorer and the Data quality panel.
Empty sessions advance the date window without filling bars. Roll gaps keep
their separate adjustment blocks. Historical pages establish no decision-time
publication evidence. The 200,000-observation guard still applies to direct
snapshot requests.
