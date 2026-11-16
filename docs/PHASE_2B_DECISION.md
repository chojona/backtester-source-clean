# Phase 2B decision

**NO-GO for historical admission and execution on the existing archive.** The original contract selector cannot be reconstructed to a defensible point-in-time standard. Calendar and publication evidence are independently insufficient, and the original chronology cannot be established on an admitted sample. Historical strategy execution, holdout evaluation and any certification promotion remain outside this decision's authority.

| Path | Scientific validity | Effort and missing evidence | Expected usefulness and decision |
| --- | --- | --- | --- |
| A · Original point-in-time contract selector | Preserves the original research question if the roster, winning volume inputs and actual decision timing are evidenced at every included origin. | High evidence and integration effort. Requires an effective-dated venue roster and expiries, all-candidate preceding electronic volume or valid upper bounds, clock and revision evidence, exception schedules, frozen data-only eligibility and authority. | Potentially supports confirmatory research once the evidence and approval gates pass. **NO-GO with the current archive.** |
| B · Separately approved retrospective exploratory lane | Can support reproducible questions about pinned archived observations, conditional on its calendar, roll and proxy assumptions. Its scope cannot establish the original selector, executable fills or confirmatory point-in-time conclusions. | Moderate. Requires a separate approved protocol, explicitly defined fixed contract policy and price vintage, cash-grid and gap exclusions, proxy clock and fees, exposure exclusions, diagnostic scope and independent separation from confirmation. | Useful for data and pipeline QA and for formulating questions for fresh evidence. **NO-GO for execution in Phase 2B.** Eligible for separate review if the intended question is retrospective. |
| C · Additional historical evidence acquisition | Can close individual roster, coverage, calendar and timing gaps if original messages and versioned evidence are recoverable. A fresh archive download alone cannot recreate original local receipt or publication history. | High for full coverage. First establish availability and provenance of the evidence products, then price a bounded evidence pilot. Requires independent review of venue completeness and access to suitable custodian or provider records. | Best route to testing whether A can ever be admitted. **GO for acquisition feasibility and scoping only.** Paid retrieval and historical execution require separate authorization. |

Prioritize C if the objective still requires confirmation. Ask the exchange or data custodian for an effective-dated NQ outright definition feed and product schedule/status archive. Ask the provider which datasets preserve electronic trade receipts, channel continuity, corrections and bar publication. Seek contemporaneous user receipt or calculation logs if the approved model requires them. A bounded evidence pilot should span at least one roll, one holiday with reassignment and short and long expiry competitors. Require reconciliation of every candidate and predecessor segment, known receipt clocks and a revision trail before expanding. If those records are unrecoverable, report that gap to the protocol owner and consider B as a distinct exploratory question.

Before a future admission decision, the research and independent review owners need to record the approved selector, clock, calendars, coverage and policy exceptions, freeze a data-only sample with verified durations and exposure exclusions, resolve the protocol source, and establish independent holdout custody. The outcome of Phase 2B supplies no eligible date list for any historical experiment.

## Verification

The full offline Python regression suite passed with **436 passed and one provider integration test deselected**. The first run reached 435 passes and one Windows chart-template decoding failure under CP1252. The full rerun used Python UTF-8 mode and a writable temporary Matplotlib cache and passed without a source change. The source-boundary scanner passed on the base and was rerun against the Phase 2B deliverables. The [archive and pilot inventory commands](HISTORICAL_ADMISSION_FEASIBILITY.md) reproduced the documented seal, scope and coverage findings.

```powershell
$env:PYTHONUTF8 = '1'
$env:MPLCONFIGDIR = Join-Path $env:TEMP 'nq-phase-2b-matplotlib'
& $py -m pytest -q -m 'not integration' -p no:cacheprovider
& $py scripts/check_source_boundary.py
git diff --check c2abb43
```

The audit is confined to the seven reports in this branch. See [contract evidence](CONTRACT_SELECTION_EVIDENCE.md), [calendar reconciliation](CALENDAR_VALIDATION.md), [availability](DATA_AVAILABILITY.md), [sample inventory](SAMPLE_FEASIBILITY.md) and [amendment provenance](AMENDMENT_PROVENANCE.md) for exact source paths and commands.
