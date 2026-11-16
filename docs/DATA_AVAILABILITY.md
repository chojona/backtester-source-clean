# Data availability

**NO-GO for a measured historical as-of replay.** The strongest supported archive-wide model is a reproducible retrospective snapshot with interval-end ordering. An exploratory protocol would need explicit approval to use an assumed availability clock.

| Clock or evidence | Meaning and finding |
| --- | --- |
| Underlying trade event | The venue event time of a trade is distinct from the provider's receipt of that trade. The cleaned OHLCV panel does not preserve either per-trade clock. |
| Bar label `t` | `timestamp_utc` represents the start of the one-minute aggregation interval. Databento documents OHLCV `ts_event` as an inclusive aggregation start based on trade message `ts_recv`. The bar label supplies neither an underlying trade event time nor aggregate publication time. [Databento OHLCV schema](https://databento.com/docs/schemas/ohlcv) |
| Nominal bar close `t + 1 minute` | This is interval completion for a full-minute statistic. It puts a lower limit on when the final-minute contents can be treated as complete in a replay. The final predecessor minute can end exactly at the scheduled decision origin, leaving zero assumed processing time. |
| Definition and statistics receipt | The bounded 2022 definition and statistics records retain provider receipt timestamps. Cleared-volume messages in that register arrived after the decision origin in every observed cell. Their receipt times do not timestamp electronic OHLCV, and their quantities measure a different statistic. |
| Aggregate emission and user receipt | The clean panel has only `timestamp_utc, contract, open, high, low, close, volume`. No first bar emission, provider finalization or contemporaneous local receipt is retained there. The October 22 bounded timing review found acquisition timestamps and no contemporaneous strategy input receipt or calculation log in its inspected package. |
| Batch acquisition and seals | Acquisition ledgers date historical downloads and seals identify retained bytes. Together they can anchor possession of a documented historical snapshot at or after acquisition. They do not backdate it to the original trading session. |

## Revisions

The cleanup report documents 537,806 exact outright overlap duplicates and zero conflicting OHLCV keys in its scanned inputs. Overlapping retained copies can detect a disagreement if distinct acquisition vintages cover the same effective instrument and minute and preserve both versions. The cleanup uses deduplication and carries source coordinates in the provenance sidecar. Equality of retained copies establishes agreement of those copies, with no evidence about earlier overwritten values, later corrections or first publication. A seal detects byte drift from the sealed snapshot. Reproducing the seal does not detect revisions outside that snapshot.

The bounded 2022 statistics investigation retained 589 pairs of cleared-volume `NEW` messages with distinct event and receipt times and no observed quantity changes inside the request. That permits a limited revision check for that schema and window. There is no complete OHLCV version ledger, original-first-publication record or trade-break/revision timeline for the requested research span.

## Defensible replay model

Use pinned archive bytes, unadjusted contract identity, a verified session grid and observed bars only. Treat values as retrospective and enforce `available_no_earlier_than = t + 1 minute` for a completed-bar dependency. This is an ordering constraint. True historical availability remains unknown. Under separate approval an exploratory analysis could model `t + 1 minute + lag` with a declared deterministic lag and symmetrical sensitivity cases. A longer assumed lag changes the proxy and cannot establish first availability or recover original vintages.

The scheduled next-minute open is the first recorded trade price in the next bucket. It need not occur exactly at the bucket start or be executable by the research system. A close and next-open sharing a nominal timestamp need an explicit proxy ordering convention. Measured late data would require the frozen paired exclusion or delay policy. A historical tradability claim would require message-level evidence tied to feature availability, local receipt, order clocks and the applicable execution evidence.

## Sources and reproduction

- `../NQ-Export/results/nq-ohlcv-clean-v1/REPORT.md` overlap and conflict counts, and `../NQ-Export/results/nq-ohlcv-clean-v1/cleaned/{nq-ohlcv-1m.parquet,row-provenance.parquet,transformation.json,SUCCESS.json}`.
- `../NQ-Export/backtester/reports/nq-definition-statistics-acquisition-evidence.md` and `../NQ-Export/backtester/results/nq-causal-contract-selection-register.json` for separate clocks and bounded message evidence.
- `../NQ-Export/backtester-public/results/nq-strict-certification-evidence-2026-10-22/historical-availability-feasibility.md` for the earlier local-arrival search. Its scope is the named July/August candidate evidence package.

```powershell
& $py -m backtester.experiments inventory-archive ../NQ-Export
rg -n 'overlap duplicates|Conflicting OHLCV keys' ../NQ-Export/results/nq-ohlcv-clean-v1/REPORT.md
rg -n 'no observed quantity changes|ts_recv|decision origin' ../NQ-Export/backtester/reports/nq-definition-statistics-acquisition-evidence.md
```
