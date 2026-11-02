# Exploratory Manifest Schema & Dataset Adapter Specification (M1)

## Lane contract

| Field | Value |
|---|---|
| Lane | `exploratory` |
| `strict_eligible` | always `false` |
| Certification | never |
| Live / paper trading | not authorized |
| Trust roots touched | none |

## Manifest schema (`research-nq-exploratory-manifest-v1`)

Required fields:

- `schema_version` — const `research-nq-exploratory-manifest-v1`
- `dataset_id` — stable exploratory identity string
- `dataset_sha256` — lowercase 64-hex digest of the dataset bytes/identity binding
- `instrument` — const `NQ`
- `contract` — e.g. `NQZ26`
- `time_range.start_utc` / `time_range.end_utc` — explicit UTC, start < end
- `source.provider` / `source.locator` / `source.acquisition_mode`
  - modes: `synthetic_constructed` | `local_licensed_readonly` | `provider_capture_readonly`
- `coverage_classifications` — non-empty unique subset of
  `observed`, `provider_inferred_no_trade`, `materialized`, `unresolved`
- `calendar_identity.calendar_id` / `calendar_identity.calendar_sha256`
- `strict_eligible` — const `false`
- `lane` — const `exploratory`

Optional: `content_sha256`, `calendar_kind`, `limitations`, `source.notes`.

Authoritative validator: `backtester.research_nq.manifest.validate_manifest`.
JSON Schema mirror (Python-embedded for source-boundary safety):
`backtester.research_nq.schema.EXPLORATORY_MANIFEST_SCHEMA`.

## Bar availability taxonomy

| Class | Meaning |
|---|---|
| `observed` | Published traded bar with positive volume |
| `provider_inferred_no_trade` | `NO_TRADE` under `PROVIDER_AVAILABLE` without materialization |
| `materialized` | Explicit previous-price grid fill (`materialization` evidence) |
| `unresolved` | Anything else; not promoted to no-trade |

Complete-observation analyses may consume **only** `observed`
(`COMPLETE_OBSERVATION_ALLOWED`). Other classes fail closed.

## Read-only adapter

`ReadOnlyExploratoryAdapter(manifest, bars, available_at_by_timestamp=None)`

- Immutable after construction.
- Does not download, regenerate, or rewrite historical captures.
- Default `available_at` = bar open + duration (bar close).
- `bars_available_at(decision_utc)` — records with `available_at <= decision_utc`.
- `require_complete_observations(decision_utc, start_utc=, end_utc=)` — observed-only;
  rejects unavailable, inferred no-trade, materialized, and unresolved bars in-window.
- Every record / `describe()` output sets `strict_eligible=false`.

## Non-goals (explicit M1 stop)

No trading signals, model fitting, historical strategy backtests, or holdout selection.
