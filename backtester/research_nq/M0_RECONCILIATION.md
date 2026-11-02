# M0 Reconciliation Report — NQ Research Lab

**Workspace:** `backtester-source-clean-20261030` (implementation target)
**Original environment inspected:** `/Users/jonathancho/Desktop/Projects/backtester-public`
**Adjacent private checkout also present:** `/Users/jonathancho/Desktop/Projects/backtester`
**Sealed holdout outcomes:** not inspected

## Verdict

M0 prerequisites are satisfied for a **limited M1** additive exploratory lane under
`backtester/research_nq/`. Historical certification and live trading remain unauthorized.

## Historical data paths (verified, unmodified)

| Locator | Notes |
|---|---|
| `backtester-public/data/raw/databento/NQ/phase2-2023-exploratory-pilot-v1.0.0/` | Local licensed raw; git-ignored; mode 700 |
| `backtester-public/data/raw/databento/NQ/phase2-2023-pilot-continuation-v1.0.0/` | Local licensed raw; git-ignored |
| `backtester-public/data/synthetic_NQ_*.csv` | Synthetic only; safe offline reference |
| `backtester-public/calendars/nq-history-v3.json` | SHA-256 `574338f6869a59bba4f61d84009cfa725d69e6a74eaaef5f9127e3dec889a62f` |
| `backtester-public/calendars/nq-2026-09-validation.json` | SHA-256 `d90b937617bbf7f6317d2fa4f2eb67d274d29ed5c803fc06b8608b2edc3c89d8` |

No historical captures are present in the source-clean export (by design).

## Existing capabilities (do not replace)

Reusable from original / source-clean cores without reimplementation:

- Bar pipeline, Databento normalize/materialize policy, coverage assessments
- Session calendars / dated calendar bridge (pins empty in source-clean)
- Evidence registry + market certification fail-closed gates
- RV / BPV / HAR lag math (`volatility.py`, `quant_features.py`); VWAP in `features.py`
- Original NQ modules (`nq_exploratory`, `nq_har*`, `nq_research*`, audits) live in
  `backtester-public` and are **excluded** from this export by source-boundary rules
  (`backtester/nq_*` forbidden). M1 therefore adds `research_nq/` rather than restoring
  those modules into the public export.

## Trust roots (unchanged)

- `PRODUCTION_MANIFESTS = {}`
- `config/approved_evidence.json` empty and CI-enforced empty
- Calendar pin dicts empty in source-clean

## Unresolved questions (recorded, not invented)

1. Whether any additional local NQ raw folders beyond the two phase2 paths exist on other machines.
2. Independent re-adjudication of provider-inferred no-trade minutes outside prior W1 exceptions.
3. Calendar pin promotion into source-clean (requires separate reviewed change; out of M1).
4. Exposure exclusion list registration for Jul 7–Sep 4 2026 exploratory segment before any future independent eval.

## Blockers that stop M1?

None for synthetic exploratory scaffolding. Strict certification remains NO-GO (intentional).
