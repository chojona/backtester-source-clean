# Reusable Component Inventory (M0 → M1)

## Reuse in place (source-clean)

| Component | Path | M1 use |
|---|---|---|
| `Bar` / integrity | `backtester/data.py` | Adapter input; state validation |
| Coverage assessment | `backtester/providers/coverage.py` | Semantics aligned with provider-available vs unknown |
| Databento normalize materialize policy | `backtester/providers/databento.py` | Reference for materialized vs inferred distinctions |
| Market certification gates | `backtester/market_certification.py` | Left fail-closed; not bypassed |
| Evidence registry | `backtester/evidence_registry.py` | Production registry remains empty |
| RV / HAR / VWAP math | `volatility.py`, `quant_features.py`, `features.py` | Not redefined in M1 |
| Source boundary CI | `scripts/check_source_boundary.py` | `research_nq/` allowed; `nq_*` still forbidden |

## Reuse by reference only (backtester-public; not imported here)

| Component | Path | Why not imported |
|---|---|---|
| `nq_exploratory` / `nq_har*` / `nq_research*` | `backtester/nq_*.py` | Forbidden prefix in source-clean boundary |
| Pinned calendars | `calendars/*.json` | Excluded from export; local runtime only |
| Archival PIT schemas | `docs/nq-archival-pit-v1/` | Certification-class schemas; exploratory schema is separate |
| Prospective capture spool | `backtester/prospective/` | Live-adjacent; not authorized for M1 |

## New M1 / M1-R surface

| Component | Path |
|---|---|
| Package | `backtester/research_nq/` |
| Classifications | `classifications.py` |
| Manifest + schema | `manifest.py`, `schema.py` |
| Cryptographic binding | `binding.py`, `BINDING.md` |
| Read-only adapter | `adapter.py` |
| M1-R handoff / verification | `M1R_HANDOFF.md`, `M1R_VERIFICATION.md` |
| Synthetic test support | `testing_support.py` |
| Tests | `tests/test_research_nq_*.py` |
