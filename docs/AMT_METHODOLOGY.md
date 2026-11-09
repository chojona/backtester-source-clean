# Auction Market Theory methodology

Version `amt-ohlcv-v1`. The terminal computes descriptive statistics from
verified, sealed one-minute NQ OHLCV. Trade-level prices and event publication
timestamps are unavailable. `trade_exact` is reserved for a separately
validated provider. Every endpoint identifies the methodology, coordinate,
source, membership and observation cutoff. Strict historical certification
and execution eligibility remain false.

## Sources and observation admission

`NQ_DATA_ROOT` points to the sealed v2 release. `ResearchStore` reads
`research.parquet` and `session-eligibility.parquet` using the existing exact
contract, selected contract and full-session eligibility predicates.
`NQ_CONTINUOUS_ROOT` optionally provides `raw.parquet`, `adjusted.parquet`,
copied eligibility and gap tables and the bound roll/adjustment manifests.
The existing stores verify hashes at startup and AMT checks file stamps
before and after queries. See [continuous build policy](../terminal/CONTINUOUS.md)
and [Phase 1 verification](../terminal/PHASE1_VERIFICATION.md).
No chart pagination, aggregated chart candle, research engine or mutable
experiment store supplies AMT input.

Raw scopes may contribute only one source contract/segment. Adjusted scopes
may combine explicitly attributed source contracts within a single compatible
adjustment block. Multi-coordinate aggregation is rejected. The published
offset and roll lineage stay with each contributing session. An independently
anchored block has its own price coordinate. Gap records are clipped to the
elapsed interval; no absent minute is filled. Retrospective full-session
eligibility is an admission rule, even in replay. It does not establish that
eligibility or any source observation was known historically.

## Calendar, scopes and cutoff

Trading dates come from the release, not UTC dates or a weekday generator.
Ordinary Globex is 18:00 ET on the preceding calendar day through 17:00 ET
on the trading date. A 1,365-minute regime excludes [16:15, 16:30) ET.
RTH is [09:30, 16:00) ET. DST conversion uses `America/New_York`; arithmetic
on observations uses UTC. Other candidate regimes or dated exceptions are
not promoted to complete. Coverage is reported per declared date, with
excluded sessions distinguished from developing sessions. A calendar date
outside available release membership supplies no observations. A composite
only describes its admitted observations.

A selected session identifies the current trading date. The prior session
is the manifest's immediately preceding candidate date and must have ended
and reconciled in the same price coordinate for context comparison. Current
and previous weeks are Monday–Sunday trading-date intervals. Months use
calendar boundaries in trading-date space. Current week/month end at the
selected trading date. Range endpoints are inclusive, at most 31 calendar
dates. An optional UTC-aware `as_of` admits minute starts whose close is
at or before the cutoff. The default is the selected scope's display close
for retrospective browsing. Replay requires an explicit cutoff and adjusted
data rejects either causal option. Admission does not prove historical
publication. No full-session retrospective quality totals are returned for
a developing session.

## Integer ticks and profiles

A tick is 0.25 NQ points. Source OHLC must align to integer ticks (with a
floating-point tolerance of 1e-7 ticks); inconsistent OHLC is rejected.
HLC3 rounds the mean of the three integer ticks to the nearest tick. Uniform
allocation spans the inclusive low/high tick endpoints and uses exact rational
arithmetic. Output rows group globally aligned integer ticks in intervals
[lower, upper] of configured width. Zero-volume observations contribute no
profile weight. Exact rational accumulation preserves allocation; transport
uses integer millionths, distributed by largest remainder with lower tick as
tie-break. Row and work bounds fail explicitly.

POC maximizes weight, then minimizes distance to the occupied range midpoint,
then chooses the lower row. The value area starts at POC and adds one adjacent
row at a time, choosing the higher weight and then the lower price. Empty
interior rows have zero weight and are eligible for adjacency. Stop when the
included weight reaches the configured fraction (default 70%). VAL and VAH
are the inclusive low and high row boundaries. The same rules apply to TPO
counts. HVN/LVN use a centered moving mean over an explicit radius and local
prominence against both immediate smoothed neighbors as a fraction of the
smoothed peak. The edges are omitted and flat extrema are ignored. Sensitivity
compares both allocation methods on identical observations and row boundaries.

## Time Price Opportunity and Initial Balance

Each period is indexed from display open in UTC elapsed minutes, default 30.
Occupancy is the union of inclusive low/high rows from observed OHLCV minutes
in that period. A row counts once per period. Missing periods occupy nothing;
a partial period ends at the cutoff and reports elapsed/missing observations.
Block and letter representations are optional. Initial Balance is the observed
RTH high and low over the first 60 minutes by default. It reports developing
and incomplete status separately; an elapsed window alone cannot establish
completeness.

## VWAP and descriptive context

VWAP uses observed one-minute HLC3 without HLC3 tick rounding, weighted by
source volume. Deviation is the weighted population standard deviation, with
a configurable band multiplier. Zero-volume bars do not update moments;
there is no VWAP until positive volume. A manual anchor includes the first
minute whose start is at or after the supplied timestamp, even if the anchor
falls between minutes. An anchor price is a UI annotation. Session, week and
month resets use the scopes above. Calculation always starts at the scope
boundary or manual anchor and is independent of chart pages. Missing minutes
do not add weight. Disconnected observations are marked so the UI can break
the line across gaps. Points are timestamped at minute close; when rendering
an aggregate candle, use only values available by that candle's close.

Context reports developing value, overlap in inclusive ticks relative to the
prior value area, POC migration, value width, Initial Balance extensions and
last close's location in the observed range. Prior comparisons require
compatible coordinates and reconciled prior coverage. A flat range has no
normalized location.

## Identity and storage

An AMT request identity binds methodology version, verified release/build and
artifact IDs, symbol, display, scope, cutoff and calculation options. The
backend does not cache computed results. The browser cancels superseded
requests and checks response identity before rendering. Version 3 workspace
settings and manually selected UTC/price anchors are scoped to the verified
series, symbol, display and adjustment block. Replay only uses the current
snapshot cutoff and hides anchors outside that prefix.
