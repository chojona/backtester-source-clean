# Calendar validation

**NO-GO for full historical calendar admission.** The ordinary CME regime rules and timezone conversions are consistent with the existing calendar in the reviewed cases. Dated holiday, shortened-session and halt evidence remains incomplete. A calendar grid defines expected opportunities for trading. A missing minute does not establish a bar, closure, feed loss or zero volume.

## Ordinary session reconciliation

All times are New York local. Intervals use inclusive starts and exclusive ends. Retain exchange trade date independently of civil date, and convert each local boundary to UTC with the applicable timezone rules.

| Historical regime | Reconciled ordinary boundary | Evidence and limitation |
| --- | --- | --- |
| Through 2012-11-18 | Prior weekday 16:30–17:30 segment belongs to the next trade date, followed by 17:30–18:00 maintenance. Sunday starts 18:00. Current trade date ends 16:15. | CME's 2012 before/after schedule distinguishes the prior next-date segment from the subsequent same-date extension. The strict bridge cannot express R1. |
| 2012-11-19 through 2015-09-20 | Open prior evening 18:00, pause 16:15–16:30, close 17:15. | The resumed segment now belongs to the same trading date. |
| 2015-09-21 through 2021-06-27 | Open prior evening 18:00, pause 16:15–16:30, close 17:00. | The 2015 notice shortened the close by 15 minutes and retained product open times. Its platform maintenance ended at 17:45 ET. The existing 17:00–18:00 field describes the nontrading span and should distinguish platform maintenance from the remaining time before the scheduled product open. |
| From 2021-06-28 | Ordinary 18:00 to next day 17:00, with 17:00–18:00 maintenance and no ordinary afternoon pause. | The dated 2021 CME notice explicitly includes NQ in the change. An ordinary session has 1,380 minute labels. |

[CME 2012 hours change](https://www.cmegroup.com/rulebook/files/ser-6465_Equity_Index_Futures_Options_on_Equity_Index_Futures_20121114.pdf) · [CME pre-2012 comparison](https://www.cmegroup.com/content/dam/cmegroup/education/files/eq-trading-hours.pdf) · [CME 2015 close and unchanged opens](https://www.cmegroup.com/tools-information/lookups/advisories/electronic-trading/20150914.html) · [CME 2021 pause removal](https://www.cmegroup.com/notices/electronic-trading/2021/06/20210621.html)

The timezone check covered 32 DST changes inside the calendar span, from November 7, 2010 through March 8, 2026. For transition Fridays, Sundays and Mondays it compared equal New York and Chicago local schedules for the ordinary open, close and cash boundaries. For example, the 2022 post-transition Monday sessions convert to March 13 22:00–March 14 21:00 UTC and November 6 23:00–November 7 22:00 UTC. Expected ordinary cash labels run 09:30 through 15:59 ET, yielding `[13:30,20:00)` UTC in daylight time and `[14:30,21:00)` UTC in standard time. These are clock checks. Each holiday and shortened cash date still needs a dated cash-market schedule, reconciled with CME product-specific active intervals.

## Date exceptions and minute attribution

| Scope | Reconciliation | Outstanding |
| --- | --- | --- |
| Four 2022 workbooks | CME equity-product rows assign the combined Sunday/Monday and Monday/Tuesday segments to May 31, Jun 21, Jul 5 and Sep 6. For each Tuesday, active intervals are Sunday 22:00–Monday 17:00 UTC and Monday 22:00–Tuesday 21:00 UTC. The Monday 17:00–22:00 halt/pre-open is outside the active grid. The latest prior evidence review ties these to the workbook trade-date headers and matching hashes. | Jun 22, Jul 6 and Sep 7 have ordinary-rule support only in the cited W1 review. Oct 10–12 and Nov 9–11 remain provisional there. Settlement and clearing notices supply no product-specific hours at those boundaries. |
| 2023 calendar supplement | Ten labels retain 2,595 calendar-question minutes. Equity-family windows support candidate early closes or halts, including Good Friday 08:15 CT, Jul 3 and Nov 24 12:15 CT, and midday stops on several holidays. | Product-specific evidence remains missing in this supplement for Jan 16, Feb 20, Apr 7, May 29, Jun 19, Jul 3–4, Sep 4 and Nov 23–24. Jan 2 and Dec 25 are unverified there. A separate 45 provider/feed-gap minutes require activity and continuity evidence. |
| Broad completeness audit | 33 of 56 scoped calendar candidates classified as closures in the retained review. 130 retained off-ordinary-grid observations remain unresolved, including 79 at the ordinary halt or pre-2012 close, 42 at ordinary closes from 2012 onward, two at pre-2012 maintenance start and seven one minute before opens or reopens. | Preserve original timestamps and keep such observations out of the assumed grid pending status and timestamp evidence. The 23 unresolved broad dates are listed below. |
| 2026 bounded evidence | Calendar file identifies Sep 14–25 and Oct 6 as reviewed regular (11 weekdays total). It also carries eight unresolved 2026 holiday windows. Effective Jun 19, CME assigns trades executed on a Friday U.S. holiday to the next valid clearing trade date. | Named holiday windows and rule prose leave early close, reopen and trade-date assignments unresolved unless an effective-dated product schedule supplies them. No archive-wide exchange status or emergency-halt inventory was established. |

[CME holiday and status definitions](https://www.cmegroup.com/trading-hours.html) · [CME February 2026 notice](https://www.cmegroup.com/notices/electronic-trading/2026/02/20260209.html)

The broad ledger's 23 unresolved dates are 2012-11-22; 2013-01-21, 02-18, 05-27, 07-04, 09-02, 11-28; 2014-01-20, 02-17, 06-12, 06-13, 09-23 through 09-25, 12-31; 2023-12-25; 2024-01-01, 03-29, 12-25; 2025-01-01, 04-18, 12-25; and 2026-01-01. This ledger and the 2023 focused supplement use different scopes. Their counts cannot be added. The calendar's federal holiday and neighboring-date guard, including additional dates 2018-12-05 and 2025-01-09, is an exclusion flag. It cannot establish a closure.

Across requested contract-minutes the completeness ledger classifies 8,333,518 absent candidates as 160,935 closure, six confirmed no-trade and 8,172,577 unresolved. Zero minutes were established as confirmed missing source data by that ledger. Exact contract status and complete venue or provider trade evidence are required to distinguish halts, active/no-trade minutes and data gaps. A proved no-trade minute can support zero volume under an approved volume policy, while the proposed full cash-grid rule still requires an observed valid bar.

## Sources and commands

- `../NQ-Export/backtester/calendars/nq-history-v3.json`, SHA-256 `574338f6869a59bba4f61d84009cfa725d69e6a74eaaef5f9127e3dec889a62f`, and `../NQ-Export/backtester/calendars/sources/nq-history-v3-evidence.json`. The source-clean [dated bridge](../backtester/providers/coverage.py) only loads expressly reviewed regular dates in supported regimes. Its calendar pin maps are empty.
- `../NQ-Export/backtester/reports/nq-w1-final-calendar-readiness.md` identifies the exact product rows, sheet cells and source SHA-256 values for the four preserved 2022 workbooks in `../NQ-Export/backtester/reports/evidence/cme-2022/`. All four local hashes matched those references.
- `../NQ-Export/backtester-public/reports/nq-phase2-2023-calendar-v1.1.0/{summary.json,report.md,date-reconciliation.csv,source-register.csv}`.
- `../NQ-Export/results/nq-ohlcv-completeness-v2/final/{summary.json,calendar-date-review.csv,session-boundary-review.parquet}`. The boundary query below projects classification fields only.

```powershell
$cal = '../NQ-Export/backtester/calendars/nq-history-v3.json'
$review = '../NQ-Export/results/nq-ohlcv-completeness-v2/final'
Get-FileHash $cal
Get-ChildItem ../NQ-Export/backtester/reports/evidence/cme-2022 -Filter '*.xls' | Get-FileHash
Import-Csv "$review/calendar-date-review.csv" |
  Where-Object {[int]$_.unresolved_candidate_minutes -gt 0} |
  Select-Object date,classification,unresolved_candidate_minutes
@'
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import pyarrow.parquet as pq
from collections import Counter

root = Path("../NQ-Export")
scope = json.loads((root / "backtester/calendars/nq-history-v3.json").read_text())["scope"]
lo, hi = (date.fromisoformat(scope[f"{key}_trading_date"]) for key in ("first", "last"))
ny, ct = ZoneInfo("America/New_York"), ZoneInfo("America/Chicago")
day, changes = lo + timedelta(days=1), []
while day <= hi:
    if datetime.combine(day, time(18), ny).utcoffset() != datetime.combine(day-timedelta(days=1), time(18), ny).utcoffset():
        changes.append(day)
        for local_day in (day-timedelta(days=2), day, day+timedelta(days=1)):
            for et, central in [(time(18), time(17)), (time(17), time(16)), (time(9,30), time(8,30)), (time(16), time(15))]:
                assert datetime.combine(local_day, et, ny).astimezone(timezone.utc) == datetime.combine(local_day, central, ct).astimezone(timezone.utc)
    day += timedelta(days=1)
print(len(changes), changes[0], changes[-1])
path = root / "results/nq-ohlcv-completeness-v2/final/session-boundary-review.parquet"
rows = pq.ParquetFile(path).read(columns=["classification", "boundary_pattern"]).to_pylist()
print(Counter((row["classification"], row["boundary_pattern"]) for row in rows))
'@ | & $py -
```
