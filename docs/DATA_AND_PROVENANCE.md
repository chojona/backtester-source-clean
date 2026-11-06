# Data, time, and provenance

The repository contains source and verification logic, not a distributable market-data release. Keep the Python CSV workflow, the exploratory adapter, and the terminal's sealed-release binding distinct.

## Input paths

| Workflow | Input and admission |
| --- | --- |
| Daily example | CSV with `date,open,close`; parsed by `backtester/engine.py` |
| Intraday engine/research | One- or five-minute CSV with raw constituent prices and dated contracts; validated by `backtester/data.py` |
| Provider-normalized input | Adapter-specific normalized data plus provenance/calendar sidecars; detected by the CLI |
| Exploratory NQ adapter | Manifest plus cryptographically bound dataset/calendar bytes and reconciled bar records |
| NQ terminal | Existing sealed NQ v2.0.0 release, verified artifact hashes, exact contract and retrospective full-session eligibility |

### Intraday CSV conventions

Required columns are `timestamp,open,high,low,close,volume`. Include `contract`, or supply the CLI's dated `--contract` fallback. If present, `symbol` must match the requested instrument. Additional declared provider/coverage fields are parsed by `CSVProvider`; arbitrary CSV labels cannot establish verified evidence.

Timestamps must be timezone-aware. `timestamp` is the **bar open**; a bar's completed information becomes available at its end. Inputs are checked for timestamp ordering, duplicates, OHLC consistency, finite values, volume, interval alignment, session boundaries, gaps, and tick conformity. The supported instrument definitions live in `backtester/instruments.py`.

Executable inputs must use raw constituent prices. Setting `input_price_basis` to an adjusted basis is rejected by the intraday CLI. Contract roll selection and any adjusted research representation are handled separately.

### Calendars and missing observations

`SessionCalendar` models trading dates, session segments, breaks, and supplied date overrides. Its default weekday templates are not certified holiday calendars. Review configuration and provider sidecars before treating scheduled closures, early closes, or session completeness as established.

Missing minutes, provider-inferred no-trade minutes, materialized bars, and unresolved observations are different states. Do not replace an unknown observation with zero volume or a previous price and then treat it as observed. CLI flags permitting gaps/off-tick inputs do not repair data or upgrade its provenance.

## Terminal release binding

`NQ_DATA_ROOT` points to an existing external build directory containing:

```text
SUCCESS.json
summary.json
input-bindings.json
research.parquet
session-eligibility.parquet
selected-observations-with-flags.parquet
contract-rolls.parquet
```

The store checks the release version and SHA-256 of all six consumed artifacts against `SUCCESS.json`. The seal itself is a local consistency reference, not an independent trust authority. The source release must remain immutable while the process runs; restart after a legitimate source change.

Every current-session query retains exact `contract` and `selected_contract` identity plus `eligible_full_session IS TRUE`. Observed counts must reconcile with the manifest. Previous-session levels use the manifest's exact prior candidate date and its complete-observation/boundary conditions; another date or contract is not silently substituted.

Missing or inconsistent artifacts fail with a dataset error. No provider acquisition, release builder, or synthetic terminal fallback is implemented by the launcher.

## Replay availability

A replay cursor counts **observed one-minute rows**, not wall-clock elapsed minutes. Before calculations, rows must satisfy `bar open + 1 minute <= as_of` when an explicit cutoff is supplied, and the selected observed-prefix length when a cursor is supplied.

The filtered prefix feeds candles, volume, VWAP and bands, opening range, statistics, and Explorer pagination. Higher-timeframe candles can develop while only some constituent source minutes are known; `available_at` identifies their current decision-time availability. The displayed bucket-open timestamp does not imply its developing values existed at that open.

Globex display uses the eligible ordinary-session observations. RTH display further restricts prices to [09:30,16:00) America/New_York and anchors aggregation there. The replay cursor continues to count the underlying ordinary-session observations even when the RTH display is empty before 09:30.

Session bounds and totals are metadata from retrospective selection. Prefix filtering prevents access to future prices through the replay snapshot; it does not prove historical publication timing of the source release or eligibility decisions.

## Indicators and annotations

VWAP is the OHLCV approximation `sum(HLC3 × volume) / sum(volume)`, not trade-level VWAP. Bands use volume-weighted population deviation of one-minute HLC3. Opening-range duration is configurable and remains developing until its end. Full definitions and API controls are in the [terminal guide](../terminal/README.md#causality-and-indicator-definitions).

Drawings store prices, UTC-time anchors, and a creation cutoff in browser-local storage. They are user annotations, not additions to source observations or certification evidence. Later-created/future-anchored drawings are hidden when replay is rewound.

## Eligibility versus certification

- **Integrity validation** checks structural/data consistency; it does not establish source authenticity or historical publication.
- **Terminal eligibility** is retrospective QC eligibility in the sealed release. It remains non-strict.
- **Exploratory admission** binds declared bytes, calendar identity, classification, and availability under the [exploratory specification](../backtester/research_nq/SPEC.md). Every output declares `strict_eligible=False`.
- **Strict certification** uses the separate gates in `market_certification.py` and the production evidence registry. This source export keeps the approved evidence registry empty; examples and exploratory manifests cannot populate it or bypass those gates.

The [binding documentation](../backtester/research_nq/BINDING.md) describes the exploratory adapter's exact requirements. Existing review/handoff documents retain their stated status; this guide does not grant acceptance or certification.

## Publication

Commit implementation, dependency metadata, documentation, reviewed configuration templates, and source-level tests. Keep historical records, provider responses, real calendars, private manifests/evidence, fitted outputs, generated examples, reports, and market-data screenshots outside Git. Credentials belong in local environment configuration, never documentation examples with real values.

The [source boundary policy](../PUBLIC_EXPORT.md) and its checker cover reachable history. `.gitignore` protects routine untracked output but does not remove previously committed content or prevent `git add -f`.
