# M1-R Independent Review Handoff

**Status:** M1-R IMPLEMENTED PENDING INDEPENDENT ACCEPTANCE

Do not self-approve or merge. This handoff is for an independent acceptance pass.

## Scope

Remediation of the six independently rejected findings against M1 commit
`e195a419b0c30052f89b32936cefdaa513c33a0a` / merge
`07e400f1c7a70befeeef64aed74fd6fb743ef8cd`. Production certification, live
execution, historical research outcomes, and protected evidence were not
modified.

## Defect-to-test traceability

| Finding | Defect | Permanent regression(s) |
|---|---|---|
| 1 Hash binding | Digests were shape-only; unrelated bytes / duplicate keys / spoofed provider identity admitted | `test_digest_mismatch_rejected`, `test_unrelated_bytes_with_matching_digest_still_require_reconciliation`, `test_synthetic_mode_rejects_licensed_provider_identity`, `test_load_manifest_rejects_duplicate_json_keys`, `test_binding_positive_control_matches_calendar_and_dataset_bytes` |
| 2 Complete observations | Missing/duplicate/unsorted/off-grid/out-of-range/halt/mixed-session/empty windows accepted | `test_complete_observations_reject_structural_failures`, `test_complete_observations_reject_bar_outside_manifest_interval`, `test_complete_observations_reject_mixed_session_window`, `test_complete_observations_reject_empty_window`, `test_complete_observations_positive_contiguous_rth_window` |
| 3 Causal availability | Assumed close and early caller overrides treated as publication evidence | `test_assumed_close_before_verified_publication_is_visible_not_publication_evidence`, `test_caller_override_cannot_establish_earlier_availability`, `test_caller_declared_availability_rejected_for_complete_observations` |
| 4 Classification | `UNKNOWN`/`UNVERIFIED` promoted to observed; substring materialization; unresolved no-trade inferred | `test_unknown_and_unverified_do_not_become_observed`, `test_no_materialization_substring_does_not_classify_as_materialized`, `test_unresolved_no_trade_evidence_not_promoted_to_inferred`, `test_exact_materialization_token_required`, `test_classify_preserves_four_way_distinction` |
| 5 Immutability | Mutable `coverage_evidence` changed classifications post-construction | `test_mutable_coverage_evidence_rejected_and_snapshots_are_stable`, `test_adapter_is_immutable_and_non_certifying` |
| 6 Schema parity | Python vs JSON Schema disagree; non-`ManifestError` failures | `test_adversarial_manifest_rejection`, `test_python_and_jsonschema_parity_accept_and_reject`, `test_python_validator_parity_without_jsonschema` |
| 7 Guards (previously PASS) | Must remain intact | `test_source_boundary_trust_roots_untouched`, hardening + synthetic execution suites |

## Binding contract

See `BINDING.md`. Successful adapter construction proves:

1. `sha256(dataset_bytes) == dataset_sha256` (+ `content_sha256` when present)
2. `sha256(calendar_bytes) == calendar_sha256`
3. Bars reconcile field-for-field with decoded dataset records
4. Source provider identity matches; `synthetic_constructed` rejects `GLBX.*`

## Remaining limitations

- Calendar holiday certification is still the weekday template warning; dated
  holiday pins are out of M1-R scope.
- `start < end` ordering is enforced in Python; JSON Schema alone cannot express
  cross-field ordering and accepts lexicographically valid inverted ranges.
- Independently verified publication currently requires
  `PROVIDER_AVAILABLE` + integer `source_ts_event_ns`; richer publication
  receipts are not modeled.
- Licensed historical datasets remain out of tests and committed artifacts.

## Independent acceptance checklist

1. Focused M1-R regression tests
2. Full offline test suite
3. `scripts/check_source_boundary.py`
4. Production trust-root regression tests
5. Existing synthetic execution guards

Confirm every former FAIL counterexample now rejects, and the positive bound
controls still pass, without opening historical market files or changing trust
roots.
