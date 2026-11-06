# Exploratory Manifest Schema & Dataset Adapter Specification (M1-R)

## Lane contract

| Field | Value |
|---|---|
| Lane | `exploratory` |
| `strict_eligible` | always `false` |
| Certification | never |
| Live / paper trading | not authorized |
| Trust roots touched | none |
| Status | M1-R IMPLEMENTED PENDING INDEPENDENT ACCEPTANCE |

## Manifest schema (`research-nq-exploratory-manifest-v1`)

Required fields:

- `schema_version` — const `research-nq-exploratory-manifest-v1`
- `dataset_id` — nonempty stripped string, max 256
- `dataset_sha256` — lowercase 64-hex digest of the bound dataset bytes
- `instrument` — const `NQ`
- `contract` — e.g. `NQZ26`
- `time_range.start_utc` / `time_range.end_utc` — explicit UTC ending in `Z`, start < end
- `source.provider` / `source.locator` / `source.acquisition_mode`
  - modes: `synthetic_constructed` | `local_licensed_readonly` | `provider_capture_readonly`
- `coverage_classifications` — non-empty unique subset of
  `observed`, `provider_inferred_no_trade`, `materialized`, `unresolved`
- `calendar_identity.calendar_id` / `calendar_identity.calendar_sha256`
- `strict_eligible` — const `false`
- `lane` — const `exploratory`

Optional: `content_sha256` (string only; null rejected), `calendar_kind`,
`limitations` (list of stripped strings; null rejected), `source.notes` (string).

Authoritative validator: `backtester.research_nq.manifest.validate_manifest`.
JSON Schema mirror: `backtester.research_nq.schema.EXPLORATORY_MANIFEST_SCHEMA`.
Both share one acceptance set; failures always raise `ManifestError`.
Duplicate JSON keys are rejected by `load_manifest`.

Digest fields are shape-checked at validation time. Cryptographic binding of
supplied bytes is required at adapter construction — see `BINDING.md`.

## Bar availability taxonomy

| Class | Meaning |
|---|---|
| `observed` | Published traded bar, positive volume, `PROVIDER_AVAILABLE` coverage |
| `provider_inferred_no_trade` | `NO_TRADE` under `PROVIDER_AVAILABLE` with explicit inference evidence, without materialization |
| `materialized` | Exact materialization token / provider append form |
| `unresolved` | `UNVERIFIED` / `UNKNOWN` / unsupported / contradictory evidence |

`UNVERIFIED` and `UNKNOWN` never become `observed` solely because a bar is
published with positive volume. Complete-observation analyses may consume
**only** `observed` (`COMPLETE_OBSERVATION_ALLOWED`).

## Availability provenance

| Provenance | Meaning |
|---|---|
| `assumed_bar_close` | Default retrospective assumption (open + duration) |
| `caller_declared_unverified` | Caller override; cannot precede bar close; refused by complete observations |
| `independently_verified_publication` | `PROVIDER_AVAILABLE` + `source_ts_event_ns` |

Assumed and caller-declared times are never classified as observed publication
evidence. Every record exposes `availability_provenance` and
`retrospective_assumption`.

## Read-only adapter

`ReadOnlyExploratoryAdapter(manifest, bars, *, dataset_bytes, calendar_bytes, available_at_by_timestamp=None)`

- Requires bound dataset and calendar bytes (see `BINDING.md`).
- Remints immutable bar snapshots; rejects non-string `coverage_evidence`.
- `require_complete_observations` proves calendar/grid completeness via
  `data.validate` + `SessionCalendar.valid_bar`, rejects empty windows,
  `missing_intervals`, duplicates, unsorted/off-grid bars, out-of-range bars,
  halts, mixed sessions, unresolved calendar use, unsupported classes, and
  unavailable bars. Missing bars are never synthesized.
- Every record / `describe()` output sets `strict_eligible=false`.

## Non-goals (explicit stop)

No trading signals, model fitting, historical strategy backtests, holdout
selection, licensed capture regeneration, or production trust-root changes.
