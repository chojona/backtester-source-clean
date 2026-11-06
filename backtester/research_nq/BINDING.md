# Exploratory NQ data and calendar binding contract (M1-R)

Status: M1-R implemented pending independent acceptance.

## Purpose

A syntactically valid SHA-256 hex string is not provenance. Before the
read-only adapter admits bars for exploratory analysis, the caller must supply
the exact byte strings those digests identify, and the bar sequence must
reconcile with the verified dataset bytes.

## Required inputs

| Input | Digest field | Decode / reconcile |
|---|---|---|
| `dataset_bytes` | `dataset_sha256` (and `content_sha256` when present) | UTF-8 JSON array of canonical bar records |
| `calendar_bytes` | `calendar_identity.calendar_sha256` | UTF-8 JSON `SessionCalendar` document |

## Canonical dataset encoding

`encode_dataset_bars(bars)` produces deterministic UTF-8 JSON:

- array of objects with fixed keys in `binding.CANONICAL_BAR_FIELDS`
- timestamps as explicit UTC `...Z`
- `coverage_evidence` must be a string or JSON `null` (mutable objects rejected)
- `json.dumps(..., sort_keys=True, separators=(",", ":"))`

Admission steps:

1. `sha256(dataset_bytes) == manifest.dataset_sha256`
2. if `content_sha256` present: same digest of the same bytes
3. decode JSON array
4. require caller `Bar` sequence length and field-for-field equality with decoded records
5. remint bars with immutable string evidence snapshots
6. require `bar.provider == source.provider`; reject `GLBX.*` datasets under `synthetic_constructed`

Hashing an unrelated file that happens to match a declared digest does not
satisfy step 4.

## Canonical calendar encoding

`encode_calendar_document(document)` produces deterministic UTF-8 JSON for a
document that `decode_calendar` turns into `SessionCalendar`:

```json
{
  "product": "NQ",
  "template": "equity",
  "eth_open": "18:00",
  "eth_close": "17:00",
  "rth_open": "09:30",
  "rth_close": "16:00",
  "breaks": [["16:15", "16:30"]],
  "overrides": {},
  "source": "weekday template; holidays NOT certified"
}
```

Missing or undecodable calendar bytes are rejected. Complete-observation
analyses use the decoded calendar with `data.validate` and
`SessionCalendar.valid_bar`.

## Manifest loading

`load_manifest` rejects duplicate JSON keys (same policy as
`market_certification._load_json`). Manifest validation checks digest *shape*
only; byte binding happens at adapter construction via `bind_inputs`.

## Non-goals

- Licensed historical captures are not committed or opened by tests.
- Binding success never implies production certification or trading authorization.
