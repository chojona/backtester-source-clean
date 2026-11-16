# Historical admission feasibility

November 15, 2026 · NQ Quant Research Lab Phase 2B · Base `c2abb43` · Branch `codex/historical-admission-phase-2b`

**NO-GO for point-in-time historical admission.** The archive establishes reproducible retrospective observations. The inspected evidence establishes zero admissible historical sessions under the original selector. The actual eligible count is unknown. Even the best documented decision windows lack complete, origin-available electronic volume across the eligible roster. Date-specific calendar evidence and original bar availability independently block admission.

| Gate | Evidence | Disposition |
| --- | --- | --- |
| Archive identity | Six cleaned members and two terminal coverage members match their local seals. The cleaned outright footer has 6,784,828 bars, with 69 observed contracts, 78 requested contracts, 232 request scopes and 81 source IDs. First and last UTC bar starts are 2010-06-06 22:00 and 2026-10-06 20:59. | Pass for local byte identity and retrospective inventory. |
| Selector | Per-origin evidence exists for bounded 2022 and 2023 groups. A dated CME expansion omitted by the prior 2023 audit adds an expected candidate on 29 labels. Missing volumes, incomplete venue roster proof and unrecorded original availability prevent winner certification. | [Blocked](CONTRACT_SELECTION_EVIDENCE.md) |
| Calendar and gaps | Four ordinary regimes, bounded dated support and unresolved product exceptions. The archive completeness ledger has 23 unresolved calendar candidates and 130 unresolved boundary observations. | [Blocked](CALENDAR_VALIDATION.md) |
| Availability | OHLCV interval labels and archive vintages are reproducible. First publication, revision history and strategy ingestion are unproved. | [Blocked](DATA_AVAILABILITY.md) |
| Sample and custody | 1,557 retrospective terminal-eligible dates across 4,262 candidates. No approved selector calendar or exposure-adjusted split. | [Blocked](SAMPLE_FEASIBILITY.md) |
| Protocol authority | A1–A6 remain pending. The A01–A12 source is unresolved after a local search. Independent acceptance remains open. | [Blocked](AMENDMENT_PROVENANCE.md) |

## Reproduction and evidence scope

Run commands from `C:/Users/johnn/Desktop/backtester-source-clean`. In all seven reports, `../NQ-Export` resolves to `C:/Users/johnn/Desktop/NQ-Export`. Documentary source paths are relative to the repository root unless stated otherwise. For this Windows run, `$py` was the bundled Python 3.12.14 executable at `C:/Users/johnn/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`, with the pre-existing dependencies directory below.

```powershell
$py = 'C:/Users/johnn/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$env:PYTHONPATH = '.venv-experiment-deps'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
& $py -m backtester.experiments inventory-archive ../NQ-Export
& $py -m backtester.experiments inventory-pilot ../NQ-Export/backtester-public
```

The commands hash fixed input files, read market table footers and project only dates and eligibility from the terminal coverage table. Other checks in this report use documentary registers and timezone arithmetic. Historical data is kept in the external archive. The audit used no strategy signals, returns, trade simulations, performance tables or holdout outcomes. See the [decision and regression results](PHASE_2B_DECISION.md).
