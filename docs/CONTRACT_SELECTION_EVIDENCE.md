# Contract selection evidence

**NO-GO for the original as-of selector.** A candidate belongs to the decision roster based on its dated outright identity, activation, expiration and applicable monotonic expiry state. The origin is the preceding completed Globex boundary under the proposed A1 policy. Available electronic volume over that exchange trade date ranks the roster, with nearest expiry proposed for ties. Initialization, tie detail and expiry handling still require protocol authority. After selection, target coverage can disqualify the date.

## Feasibility matrix

| Scope | Roster, expiry and mapping evidence | Predecessor Globex volume evidence | Decision status |
| --- | --- | --- | --- |
| Whole cleaned archive, 2010–2026 | 69 observed identities and 78 requested. `contracts.json` gives first/last observation, while `request-scopes.json` binds raw symbol and UTC request interval. For example, source 0 maps `NQM0` to `NQM10` for the retained interval. Neither endpoint is an exchange listing boundary. | Outright OHLCV supports retained sums when grouped over verified intervals. Uneven requests, absent labels, missing receipts and unavailable all-candidate bounds leave as-of totals unknown. | Actual rosters and winners cannot be reconstructed across the archive. |
| 2022-06-02 through 2022-11-21, 120 origins | Nine expected per date, with 1,080 matching retrospective effective-dated definition identities in the per-origin register. Full as-of venue book remains unproved. | 328 retained positive lower bounds. Of 752 unknowns, 731 were outside complete segment requests and 21 requested cells had no retained bar. 88 dates have six unknowns, 32 have seven. Cleared volume is numeric in 575 cells, with zero received by the origin. | 0 of 120 independently established. |
| 2022 front-three follow-up | Three nearest quarterlies under a distinct rule with a lexical tie break. | 88 conditional observed ranks before remediation. Bounded acquisition added three positive cells and 17 provider-stream zeros, with 12 provider gaps remaining. 108 retrospective ranks after remediation. | Zero strict as-of ranks. The follow-up does not establish the nine-contract result or the A1 rule. |
| 2023 documented 258 target labels | `contract-evidence.csv` uses provisional session labels and carries nine symbols even on the 29 labels from Nov 20 onwards. The dated CME expansion requires ten expected symbols for those labels. | 1,586 missing cells across 258 labels **under the legacy nine-symbol audit**, including 1,562 outside retained request scope and 24 requested without bars. The later 24-cell audit resolved none. No count was established for the added contract cells under the correctly dated rule. | No full-roster decision established by this evidence. |
| Jan 4, 2023 pilot target with Jan 3 provisional predecessor | Expected `NQH23, NQM23, NQU23, NQZ23, NQH24, NQZ24, NQZ25, NQZ26, NQZ27`. All nine map in the 1,695-record definition response. All nine carry multi-year `partial` flags. The definition report traces each raw symbol, instrument ID, activation and expiry. | One OHLCV request for six mapped symbols over Jan 2 23:00 to Jan 3 22:00 UTC returned zero records with coverage unresolved. Nine-symbol trades and status were never started. The OHLCV scope concerns the target's predecessor and the separate pilot used a provisional 22:45 UTC origin. | No origin-available all-candidate volume, proved zero or winner. |

## Effective-dated roster rules

| Effective trade dates | Published NQ futures listing rule | Expected count |
| --- | --- | ---: |
| Immediately before May 23, 2022 | Five consecutive March-cycle quarterlies. Earlier effective start unverified in this audit. | 5 |
| May 23, 2022 through Nov 19, 2023 | Five quarterlies plus four additional Decembers. | 9 |
| Nov 20, 2023 through Mar 8, 2026 | Six quarterlies plus four additional Decembers. | 10 |
| From Mar 9, 2026 | Six quarterlies plus two additional Junes and four additional Decembers. | 12 |

The documented 2023 register therefore understates the rule-derived universe for part of its scope. For example, on Nov 20 the additional expected quarterly is `NQH25`. The late 2026 archive also spans a broader listing schedule than the 2022 audit. For Oct 6, the rule implies `NQZ26, NQH27, NQM27, NQU27, NQZ27, NQH28` plus `NQM28, NQM29, NQZ28, NQZ29, NQZ30, NQZ31`, subject to the actual origin-time venue definitions. These are schedule-derived examples. The audit could not reconcile exact activation edges, special expiry or delisting exceptions, independent venue roster completeness or origin-available volume for all dates. The published regular termination is 08:30 Central on the third Friday. [CME SER-8975](https://www.cmegroup.com/notices/ser/2022/04/SER-8975.pdf) · [CME SER-9275](https://www.cmegroup.com/notices/ser/2023/10/SER-9275.pdf) · [CME SER-9677](https://www.cmegroup.com/content/dam/cmegroup/notices/ser/2026/02/ser-9677.pdf) · [CME NQ specifications](https://www.cmegroup.com/trading/equity-index/files/emini-nasdaq-100-futures-options.pdf)

### Per-origin evidence examples

| Origin UTC and target | Verified retained mappings and expiry examples | Rule-derived roster and observed electronic lower bounds |
| --- | --- | --- |
| 2022-06-13 21:00 → Jun 14 | `NQM2 → NQM22` expires Jun 17 13:30 UTC. `NQU2 → NQU22` expires Sep 16 13:30 UTC. | NQM22 387,941, NQU22 610,767, NQZ22 268. NQH23, NQM23, NQZ23, NQZ24, NQZ25 and NQZ26 unknown. |
| 2022-09-12 21:00 → Sep 13 | `NQZ2 → NQZ22` expires Dec 16 14:30 UTC. `NQH3 → NQH23` expires Mar 17, 2023 13:30 UTC. | NQU22 313,361, NQZ22 367,205, NQH23 135. NQM23, NQU23, NQZ23, NQZ24, NQZ25 and NQZ26 unknown. |

Known values here include the retained row counts, source scopes, definition fields and publication times for the observed statistics messages. A retained sum bounds observed electronic activity from below under the documented retained-feed interpretation. An origin-time upper bound must constrain the same electronic metric, calendar segments and data vintage and account for ties. No such bound was established for the unresolved competitors. Provider-stream zeros in a bounded follow-up have a narrower meaning than exchange-wide or origin-available zeros. Any cell without adequate scope, status or timing remains unknown.

## Lookahead channels

The legacy rule first gates candidates on **target-date** bar presence, imputes absent prior volume as zero, then ranks using retained prior observed-date totals and a lexical tie break. The 2022 audit found nine candidate removals caused by target-day absence and 11 zero imputations. Agreement on the two illustrated rolls, or a 120/120 legacy replay, leaves the missing comparisons unresolved. A previous observed date can also skip a scheduled predecessor. The terminal's fixed calendar roll assigns contracts differently from the original volume rule. Using retrospectively adjusted prices, later cleared totals or a replacement chosen after observing target coverage would introduce different information or change the experiment.

## Sources and reproduction

- `../NQ-Export/results/nq-ohlcv-clean-v1/cleaned/{contracts.json,request-scopes.json,row-provenance.parquet,SUCCESS.json}`.
- `../NQ-Export/backtester/results/nq-causal-contract-selection-register.json`, SHA-256 `2cc2954a467f7fec12ac8bf4e46eab83ff14611504d56a4f94f398920e49d77`. Its `dates` array supplies the 120 decision timestamps, exact predecessor segments, expected rosters, raw symbols, activation and expiry fields, request references, volume and evidence status for each candidate. The companion reports are `../NQ-Export/backtester/reports/nq-causal-contract-selection-register.md`, `nq-causal-contract-universe-audit.md`, `nq-definition-statistics-acquisition-evidence.md` and `nq-w1-front-three-feasibility-after-acquisition.md` in the same reports directory.
- Under `../NQ-Export/backtester-public/reports`, use `nq-phase2-2023-evidence-v1.0.0/contract-evidence.csv`, `nq-phase2-2023-contract-acquisition-v1.0.0/inventory-summary.json`, `nq-phase2-2023-retained-raw-24-audit-v1.0.0/cell-register.csv`, `nq-phase2-2023-definition-investigation-v1.0.0/per-symbol-coverage-register.json` and `nq-phase2-2023-pilot-continuation-execution-v1.0.0/acquisition-ledger.json`. The bounded pilot checksum checks are reproduced by `inventory-pilot`.

```powershell
$p = '../NQ-Export/backtester/results/nq-causal-contract-selection-register.json'
Get-FileHash $p
$r = Get-Content -Raw $p | ConvertFrom-Json
$r.dates | Group-Object { $_.unknown_electronic_volume_contracts.Count } | Select-Object Count,Name
$cells = $r.dates.candidates
$cells.Count
($cells | Where-Object definition_identity_valid_at_origin).Count
($cells | Where-Object electronic_source_requested_all_segments).Count
($cells | Where-Object { $_.retained_electronic_volume -gt 0 }).Count
($cells | Where-Object { $null -ne $_.later_cleared_volume }).Count
($cells | Where-Object later_cleared_available_by_origin).Count
$contracts2023 = '../NQ-Export/backtester-public/reports/nq-phase2-2023-evidence-v1.0.0/contract-evidence.csv'
$affected = Import-Csv $contracts2023 | Where-Object { $_.trading_date -ge '2023-11-20' }
$affected.Count
$quarters = 'HMUZ'
$affected | ForEach-Object {
  $original = $_.expected_roster -split ';'
  $front = @($original[0..4])
  $lastQuarter = $front[-1]
  $next = $quarters.IndexOf($lastQuarter[2]) + 1
  $year = [int]$lastQuarter.Substring(3) + [int]($next -eq 4)
  $front += 'NQ{0}{1:00}' -f $quarters[$next % 4], $year
  $december = $year + [int]($next % 4 -eq 3)
  $additional = 0..3 | ForEach-Object { 'NQZ{0:00}' -f ($december + $_) }
  [pscustomobject]@{Date = $_.trading_date; Expected = ($front + $additional) -join ';'}
}
$r.dates | Where-Object { $_.target_trade_date -in '2022-06-14','2022-09-13' } |
  Select-Object target_trade_date,decision_origin_utc,rule_derived_roster,candidates |
  ConvertTo-Json -Depth 8
```

The original private rebuild scripts may write into their export trees. These commands read the preserved evidence registers directly.
