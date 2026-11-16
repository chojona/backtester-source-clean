# Sample feasibility

**NO-GO for the original chronology.** The inspected evidence establishes zero admitted dates and the actual eligible count is unknown. A terminal coverage flag certifies an observed-grid check under that release's own retrospective fixed-contract policy. It cannot certify an A1 selector decision, actual cash schedule, same-contract predecessor, or data availability.

| Data-only inventory | Candidate scope | Evidence of eligibility |
| --- | ---: | --- |
| Proposed original selector | Full archive | **0 established**, total unknown |
| 2022 full-universe evidence register | 120 origins | 0 full-universe as-of winners |
| Scoped 2023 documentary evidence | 258 observed labels | 0 strict-ready in that report. Its nine-symbol metric counts 1,586 missing cells and omits the extra expected candidate on 29 labels. |
| Jan 2023 bounded pilot | One target | 0 established |
| Terminal retrospective coverage | 4,262 candidate dates | **1,557 terminal-eligible**, 2,705 terminal-ineligible. This inventory uses the terminal policy. |

| Year | Terminal-eligible dates |
| --- | ---: |
| 2010–2015 | 0 |
| 2016 | 2 |
| 2017 | 0 |
| 2018 | 72 |
| 2019 | 130 |
| 2020 | 195 |
| 2021 | 196 |
| 2022 | 212 |
| 2023 | 183 |
| 2024 | 183 |
| 2025 | 208 |
| 2026 through October 6 | 176 |

The discovery specification calls for expanding training spanning at least 12 calendar months, two or more consecutive nonoverlapping three-month development evaluation blocks and a final 20% covering at least six calendar months. It also calls for analogous inner splits when needed and purging data whose feature or label availability crosses the boundary. The primary ML split specifies a one-session gap. The three outer duration minima alone require at least 24 months across the ordered windows before any additional spacing. The repo's [count-based synthetic planner](../backtester/experiments/splits.py) demonstrates partition mechanics. It does not validate those durations.

## Date-only duration check

The terminal dates show that calendar span alone is plausible for a retrospective lane. Using whole calendar windows as an illustration, January–December 2019 contains 130 terminal dates, January–March 2020 has 41, and April–June 2020 has 55. On the retrospective terminal date column alone, the last 311 dates (floor of 20%) span 512 days and the last 312 dates (ceiling) span 515 days. Both exceed six elapsed calendar months. This calculation uses no frozen holdout partition, outcomes or designated holdout dates. It does not test an inner-fold policy, a minimum count in any window, absolute sample strength or an exposure-adjusted retrospective lane.

| Original requirement | Original selector conclusion |
| --- | --- |
| 12 months of training | Unestablished. No eligible training calendar. |
| At least two successive three-month development blocks | Unestablished. No eligible development calendar or approved month anchoring, partial-tail and purge rules. |
| Final 20% and at least six elapsed calendar months | Unestablished. No eligible date list, approved rounding, exposure exclusions or custodian-approved boundary. |
| 100 filled holdout sessions and adequate power | Untested and outside a data-only audit. Date counts measure input coverage, while fills and power require separately authorized evidence and analysis. |

For later admission, construct the date register from independently verified CME and cash calendars before inspecting outcomes. Carry dates with explicit exclusion reasons for unknown roster, expiry or volume, an unresolved predecessor, roll, incomplete observed cash grid, clock/revision limitations and known exposure. H1 additionally needs the immediately preceding scheduled cash date, matching selected outright and valid full cash data. H4 and H6 need their respective complete current-session inputs under the approved data clock. Do not classify rule events during admission. The M0 evidence names July 7–September 4, 2026 as a segment requiring exposure review. A complete signed exposure register is still missing, so the terminal duration check cannot establish holdout independence.

## Reproduction

Sources are `../NQ-Export/results/nq-ohlcv-research-v2/build/{session-eligibility.parquet,summary.json,SUCCESS.json}`, [M0 reconciliation](../backtester/research_nq/M0_RECONCILIATION.md), and `C:/Users/johnn/Desktop/New folder/gpt-researcher/nq-alpha-research/{experiments.md,IMPLEMENTATION_PLAN.md}`. Verify the terminal seal with `inventory-archive` first. This projection reads only the two coverage fields.

```powershell
@'
from collections import Counter
from datetime import date
from math import ceil, floor
import pyarrow.parquet as pq

path = "../NQ-Export/results/nq-ohlcv-research-v2/build/session-eligibility.parquet"
rows = pq.ParquetFile(path).read(columns=["trading_date", "eligible_full_session"]).to_pylist()
days = sorted(date.fromisoformat(str(row["trading_date"])) for row in rows if row["eligible_full_session"])
print(len(rows), len(days), dict(sorted(Counter(day.year for day in days).items())))
boundaries = (date(2019, 1, 1), date(2020, 1, 1), date(2020, 4, 1), date(2020, 7, 1))
for start, end in zip(boundaries, boundaries[1:]):
    print(start, end, sum(start <= day < end for day in days))
for n in (floor(len(days) * .20), ceil(len(days) * .20)):
    print(n, (days[-1] - days[-n]).days)
'@ | & $py -
```
