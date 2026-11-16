# Historical NQ outright roster sources

Phase 2C evidence plan · Base `f2ef963` · 2026-11-15

## CME evidence hierarchy

| Evidence | Verified source and use | Remaining proof |
| --- | --- | --- |
| Listing policy | SER-8975, Table 1, increases the listing schedule from five March-cycle quarterlies to five plus four additional Decembers, effective for May 23, 2022. SER-9275, Table 1, increases five to six consecutive quarterlies and retains four additional Decembers, effective Sunday Nov 19 for trade date Nov 20, 2023. SER-9677 adds two additional Junes from March 9, 2026. | Retrieve dated Chapter 359 amendments and listings for any earlier scope. These notices establish scheduled policy and effective dates. The changes and subsequent replenishments still need instrument-level messages and effective timestamps. [SER-8975](https://www.cmegroup.com/notices/ser/2022/04/SER-8975.pdf) · [SER-9275](https://www.cmegroup.com/notices/ser/2023/10/SER-9275.pdf) · [SER-9677](https://www.cmegroup.com/content/dam/cmegroup/notices/ser/2026/02/ser-9677.pdf) |
| Individual last trade and expiry | Chapter 359 §§35902.G and 35903.A tie the normal termination to the Nasdaq open on the scheduled final-settlement day, ordinarily the third Friday, with holiday exceptions. The normal time is 08:30 Chicago local. Use historical chapter versions, contract-specific advisories, and Security Definition events 865=5 and 865=7 with 1145 UTC event times. | Bind scheduled activation, actual last eligible trade, expiration and settlement as separate fields. Obtain dated definitions and modifications for each expiry boundary, including any unscheduled change. [CME Rulebook Ch. 359](https://www.cmegroup.com/rulebook/CME/IV/350/359/359.pdf) · [MDP Futures Security Definition](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457327569/) |
| Complete roster at the cutoff | CME MDP Instrument Replay plus uninterrupted Incremental Futures Security Definitions with SecurityID, product/class, maturity, activation, last eligible trade, update type 980 and update time 779. For a replay baseline reconcile loop count 911, channel, capture time and sequence coverage. The CME Security Definition Flat File describes instruments for the next trading day. | Obtain a contemporaneous pre-cutoff baseline and all subsequent changes through cutoff. A next-day flat file needs original issuance and change history to prove prior state. CME DataMine's Market Depth FAQ identifies historical definition files as an inquiry route. Historical CME Reference Data is another inquiry, subject to as-issued versions. [Instrument Recovery](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457704421/) · [Support Services](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457572789/) · [DataMine FAQ](https://www.cmegroup.com/market-data/files/cme-group-market-depth-faq.pdf) · [CME Reference Data](https://www.cmegroup.com/market-data/browse-data/catalog/reference-data.html) |
| Preceding-session volume | CME MDP Electronic Volume, entry type `e`, measures session contracts traded on Globex for an instrument. Preserve session resets, recovery, spread participation, revisions and clocks. Keep the dated NQ outright SecurityID crosswalk with every volume record. | Get historical messages or a complete, timestamped, as-issued electronic-volume ledger with the same semantics. CME documents cases where spread legs get Electronic Volume but no leg Trade Summary. A normalized outright trade sum and later cleared-volume statistic require separate validation against the approved metric. [Electronic Volume](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457672472/) · [Trade Summary](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457418925/) · [Session Statistics Reset](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457096006/) |

Identify NQ quarterly futures by security type, exchange and dated identity. Resolve raw symbols and numeric IDs within their effective intervals. Apply monotonic expiry and tie rules only after the protocol owner resolves initialization, skips and boundary semantics. Require explicit treatment of separate transaction codes under Rule 35906. Bar presence or absence supplies no listing evidence.

## Audited 2022 decisions

The 120 audit targets span June 2–November 21. Predecessor labels span June 1–November 18. All 1,080 rule-derived cells have a matching retained definition with effective fields and first recorded Databento definition receipt by the modeled origin. Those per-contract matches leave the completeness of the venue roster unproved. The counts below project membership, coverage and clock fields from the pinned register.

| Target month | Decisions | Expected cells / retained definition matches | Retained positive volume observations | Outside requests covering all segments | Requested all segments, volume unknown | Full roster / full as-of volumes proved |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| June | 20 | 180 / 180 | 52 | 125 | 3 | 0 / 0 |
| July | 20 | 180 / 180 | 50 | 120 | 10 | 0 / 0 |
| August | 23 | 207 / 207 | 69 | 138 | 0 | 0 / 0 |
| September | 21 | 189 / 189 | 57 | 132 | 0 | 0 / 0 |
| October | 21 | 189 / 189 | 58 | 126 | 5 | 0 / 0 |
| November | 15 | 135 / 135 | 42 | 90 | 3 | 0 / 0 |
| **Total** | **120** | **1,080 / 1,080** | **328** | **731** | **21** | **0 / 0** |

88 dates have six unknown volumes and 32 have seven. All 575 numeric later cleared-volume cells lack receipt by origin. An empty response is an unresolved cell until its scope, status and continuity establish a zero for the approved metric. The front-three work used a different roster and tie policy. [Phase 2B contract audit](CONTRACT_SELECTION_EVIDENCE.md)

## Late-2023 coverage matrix

These are the 29 **audit target labels** affected by the target-date expansion. The predecessor column reproduces legacy labels for tracing the volume gaps. Calendar and listing boundaries can change the actual candidate comparison.

- **A** target roster expected from the schedule is `NQZ23 NQH24 NQM24 NQU24 NQZ24 NQH25 NQZ25 NQZ26 NQZ27 NQZ28`.
- **B** target roster expected after Dec expiry is `NQH24 NQM24 NQU24 NQZ24 NQH25 NQM25 NQZ25 NQZ26 NQZ27 NQZ28`.
- The row counts concern the nine-column audit. For every row the one added target-schedule cell is **unaudited**. The CSV records a by-origin definition for the legacy selected contract on each row. It does not establish the full date-specific venue book. Original bar receipt and a complete origin-time comparison are unproved on every row.

| Target | Legacy predecessor | Target roster | Added expected cell | Legacy retained / unknown | Boundary to resolve |
| --- | --- | --- | --- | ---: | --- |
| 2023-11-20 | 11-17 | A | NQH25 | 3 / 6 | Friday cutoff predates the Sunday effective listing. Check actual activation and approved origin eligibility. |
| 2023-11-21 | 11-20 | A | NQH25 | 3 / 6 | First audited predecessor under the expanded schedule. |
| 2023-11-22 | 11-21 | A | NQH25 | 3 / 6 | |
| 2023-11-23 | 11-22 | A | NQH25 | 3 / 6 | Nasdaq closed. CME Equities assigns Thursday trading to Friday. |
| 2023-11-24 | 11-23 | A | NQH25 | 3 / 6 | The CME Equities schedule indicates Nov 22 as the preceding completed exchange trade date. Verify NQ mapping. |
| 2023-11-27 | 11-24 | A | NQH25 | 3 / 6 | Predecessor spans Nov 22–24 with a halt and early close. |
| 2023-11-28 | 11-27 | A | NQH25 | 3 / 6 | |
| 2023-11-29 | 11-28 | A | NQH25 | 3 / 6 | |
| 2023-11-30 | 11-29 | A | NQH25 | 3 / 6 | |
| 2023-12-01 | 11-30 | A | NQH25 | 3 / 6 | |
| 2023-12-04 | 12-01 | A | NQH25 | 3 / 6 | |
| 2023-12-05 | 12-04 | A | NQH25 | 3 / 6 | |
| 2023-12-06 | 12-05 | A | NQH25 | 3 / 6 | |
| 2023-12-07 | 12-06 | A | NQH25 | 3 / 6 | |
| 2023-12-08 | 12-07 | A | NQH25 | 3 / 6 | |
| 2023-12-11 | 12-08 | A | NQH25 | 3 / 6 | |
| 2023-12-12 | 12-11 | A | NQH25 | 3 / 6 | |
| 2023-12-13 | 12-12 | A | NQH25 | 3 / 6 | |
| 2023-12-14 | 12-13 | A | NQH25 | 3 / 6 | |
| 2023-12-15 | 12-14 | A | NQH25 | 3 / 6 | Expiring NQZ23 may be live at origin and end before target cash coverage. Verify fixed-winner expiry rule. |
| 2023-12-18 | 12-15 | B | NQM25 | 2 / 7 | Verify NQZ23 termination and NQM25 activation at Friday cutoff. |
| 2023-12-19 | 12-18 | B | NQM25 | 2 / 7 | |
| 2023-12-20 | 12-19 | B | NQM25 | 3 / 6 | |
| 2023-12-21 | 12-20 | B | NQM25 | 3 / 6 | |
| 2023-12-22 | 12-21 | B | NQM25 | 2 / 7 | One of the seven unknowns is in the retained requested/no-bar audit. |
| 2023-12-26 | 12-22 | B | NQM25 | 3 / 6 | Confirm NQ Christmas closure and Monday evening assignment to Dec 26. |
| 2023-12-27 | 12-26 | B | NQM25 | 3 / 6 | Confirm holiday reopen and complete preceding segments. |
| 2023-12-28 | 12-27 | B | NQM25 | 3 / 6 | |
| 2023-12-29 | 12-28 | B | NQM25 | 3 / 6 | |
| **Total** | | | **29 unaudited target-schedule cells** | **84 / 177** | 176 legacy unknowns outside the retained scope and one requested without a retained bar. |

The 261 legacy cells and 29 added target-schedule cells are planning counts. A true origin-based audit can change the denominator, the preceding window and individual cell classifications. In particular, an announced contract has a known future listing schedule before it becomes eligible to trade. Reconcile what was known and what was effective separately. [Thanksgiving schedule](https://www.cmegroup.com/trading-hours/files/thanksgiving-day-2023.pdf) · [Christmas schedule](https://www.cmegroup.com/trading-hours/files/christmas-day-2023.pdf) · [Nasdaq 2023 Trading Calendar](https://www.nasdaqtrader.com/content/technicalsupport/2023tradingcalendar.pdf)

### Internal evidence references

- `../NQ-Export/backtester/results/nq-causal-contract-selection-register.json`, recomputed SHA-256 `2cc2954a467f7fecd12ac8bf4e46eab83ff14611504d56a4f94f398920e49d77`. The Phase 2B report omitted the `d` after `fec` when transcribing this digest. Group `dates` by month of `target_trade_date`. Read `candidates` identity, request and availability fields. Compare each `definition_first_provider_receipt_utc` with its parent `decision_origin_utc`.
- Under `../NQ-Export/backtester-public/reports/`, use `nq-phase2-2023-evidence-v1.0.0/contract-evidence.csv`, SHA-256 `2985edfec2c30ab8a637fe2b23c64181aef200e5ceecb18610a987a79cff345a`. Filter `trading_date >= 2023-11-20` and count semicolon-delimited `contracts_with_observed_predecessor_volume` and `expected_roster_without_observed_volume`. Cross-reference `nq-phase2-2023-retained-raw-24-audit-v1.0.0/cell-register.csv` on `target_trade_date` and `contract`. The matching subset contains one requested/no-bar cell. The target-schedule columns are derived from the SERs and expiration schedule.
