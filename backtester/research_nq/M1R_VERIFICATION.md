# M1-R verification evidence

Status: M1-R IMPLEMENTED PENDING INDEPENDENT ACCEPTANCE

Environment: Python 3.12.13, `pytest==8.4.2`, `jsonschema==4.26.0`, extras `.[test]`.
No historical market-price datasets opened. No EXP-001. Trust roots unchanged.

## Before / after synthetic counterexamples

| Counterexample (independent review) | Before (M1) | After (M1-R) |
|---|---|---|
| Manifest with wrong digests validates shape-only | accepted | shape still validates; **adapter bind rejects** digest mismatch |
| Unrelated bytes hashed to claimed digest | N/A / admitted without reconcile | **rejects** — bars must decode from verified bytes |
| Duplicate JSON `dataset_sha256` keys | last-key wins | **`ManifestError: Duplicate JSON key`** |
| `synthetic_constructed` + Databento/`GLBX.MDP3` bar | complete observations accepted | **rejects** provider/dataset identity |
| Missing minute inside window | accepted | **rejects** (`missing_intervals`) |
| Duplicate timestamps | accepted | **rejects** |
| Unsorted timestamps | accepted | **rejects** |
| Off-grid open | accepted | **rejects** |
| Outside manifest interval | accepted | **rejects** |
| Halt / out-of-session | accepted | **rejects** |
| Mixed RTH + POST_RTH window | accepted | **rejects** |
| Empty window | accepted `()` | **rejects** |
| Assumed close before verified publication | accepted as observed | **rejects** until verified publication; provenance explicit |
| Caller override earlier than bar close | accepted | **rejects** |
| Caller-declared availability in complete observations | accepted | **rejects** |
| `UNKNOWN` / `UNVERIFIED` published volume | classified `observed` | **`unresolved`** |
| `"no materialization..."` substring | classified `materialized` | **`observed`** (exact token required) |
| Unresolved no-trade evidence | classified `provider_inferred_no_trade` | **`unresolved`** |
| Mutable list `coverage_evidence` | post-lock reclassify possible | **rejected / snapshotted** |
| Python vs schema parity holes | disagree / non-ManifestError | **aligned `ManifestError`** (+ documented ordering-only schema limit) |
| Contiguous bound observed RTH window | accepted | **still accepted** (positive control) |

## Command results

1. Focused M1-R regressions:
   `pytest tests/test_research_nq_manifest.py tests/test_research_nq_adapter.py tests/test_research_nq_m1r_counterexamples.py`
   → **55 passed**

2. Full offline suite:
   `pytest -q`
   → **363 passed, 4 skipped** (databento import ×2, live API opt-in, matplotlib)

3. Source-boundary checker:
   `python scripts/check_source_boundary.py`
   → **passed, 99 blobs across reachable history** (pre-commit count; post-commit expect `.py`/`.md` only under `research_nq/`)

4. Production trust-root regressions:
   - `PRODUCTION_MANIFESTS == {}`
   - `require_strict_dataset` → `Strict certification NO-GO: no independent production acceptance`
   - `config/approved_evidence.json` → empty capture/ledger lists
   - adapter trust-root test + hardening suite → **passed**

5. Synthetic execution guards:
   `pytest tests/test_synthetic_execution.py` (with hardening) → **passed**
   Licensed Databento/`GLBX.MDP3` bars remain rejected by Step 7A synthetic marking rules.

## Known failures

None in the required suites above.
