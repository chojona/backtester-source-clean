# NQ Quant Research Lab continuation

Base revision `514ca1c` defines H4 v1.0.0, a constructed opening-range acceptance experiment, and reserves the ten hypothesis slots. The registry continues to enable only H4 synthetic execution. The design tools below provide evidence for review and operate independently of the frozen hypothesis and its primary evaluation.

## Forward planning and locked holdout

`plan_forward` accepts a prequalified, strictly increasing sequence of unique session dates. It snapshots the input and every partition into tuples and gives the resulting versioned plan a SHA-256 identity. Training expands and validation advances in complete, non-overlapping windows. The optional gap counts eligible sessions and applies ahead of each validation window and before holdout. A fixed holdout start date partitions the eligible list even if that date itself is absent. An incomplete development tail is recorded explicitly. A caller must establish outcome-blind eligibility before calling the planner.

Run this rehearsal from one designated local custody store for the experiment:

```text
python -m backtester.experiments prepare-rehearsal results/foundation-custody
python -m backtester.experiments evaluate-rehearsal results/foundation-custody --confirm-binding <digest>
```

Preparation writes the canonical plan and binds it to the frozen protocol and implementation files. Evaluation requires the exact digest and prepared bytes. An exclusive filesystem claim consumes the scope before rule evaluation, including if evaluation fails after the claim. Repeating preparation leaves the existing binding and claim in place. The fixture is source-visible and exercises custody mechanics. A designated store provides the single point of coordination. Copying, deleting or redirecting the store falls outside this local control. Historical custody would require an independent custodian, access control, an auditable durable store and signed authorization. Historical evaluation currently fails before binding or filesystem access.

## Synthetic validation

```text
python -m backtester.experiments validate-synthetic
python -m backtester.experiments verify <existing-synthetic-run-directory>
```

The validation command records deterministic null, positive-shift, serially dependent and sparse cases under the existing stationary bootstrap. A single index path applies to every component in a panel. Sparse cases retain the rows where another component is observed and drop resamples with no eligible observations for the component being estimated. A zero outcome is an observation. A missing outcome is excluded.

Power uses constructed paired Gaussian AR(1) outcomes with declared marginal scale, serial correlation and between-component correlation. Both components receive the same shift and must clear the one-sided local threshold. The default threshold of 0.005 is the first Holm threshold at family alpha 0.05 with ten slots. Common resamples across the effect grid reduce simulation noise in comparisons, and each reported power point includes a Wilson interval for Monte Carlo uncertainty. The grid MDE is the first declared effect whose estimated power reaches the target. The simulated panel is dense and carries no historical calibration, costs or fill assumptions. Sample size, dependence, missingness, effect units and practical significance remain design inputs for future review.

The optional Hansen SPA diagnostic accepts complete paired losses with lower values preferred. It uses benchmark loss minus model loss, circular stationary bootstrap studentizers and lower, consistent and upper recentering. The empirical upper-tail convention includes ties and uses add-one smoothing. The diagnostic stays outside the primary H4 calculation and Holm decision. The verification suite compares the implementation against independently enumerated stationary paths on small constructed panels and tests reversed loss orientation. [Hansen, *A Test for Superior Predictive Ability*](https://bashtage.github.io/kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Hansen.pdf)

## Historical data-admission inventory

```text
python -m backtester.experiments inventory-pilot <external-evidence-root>
python -m backtester.experiments inventory-archive <external-export-root>
```

The pilot command targets the Phase 2 pilot and continuation package identified by the M0 audit. It reads fixed acquisition and calendar sidecars, checks the requested roster and declared counts, and streams SHA-256 over the fixed pilot response files. The archive command targets the reviewed cleaned outright export. It checks local seals, reconciles the observed roster and row counts, reads bar table footers, and projects date and eligibility only from the terminal's retrospective coverage table. It also inventories unresolved evidence from documentary calendar and completeness summaries. The CLI emits JSON on stdout for storage outside Git. [M0 reconciliation](../backtester/research_nq/M0_RECONCILIATION.md)

Required admission evidence includes an independently reconciled effective-dated contract roster, official session and exception coverage, minute-level data completeness and gap attribution, original publication and revision timing, exposure exclusions, independent review and a frozen eligible-session list. The inventory distinguishes declared response records, sessions supported by admission evidence and the unknown actual eligible count.

## Amendment decisions

The decisions below address the November 15, 2026 H1/H4/H6 hypothesis audit supplied with this review. They describe readiness for independent review. All six amendments remain pending approval in the frozen registry. EXP-001 A01–A12 follows its separate review process. [Frozen H4 registry](../config/experiments/h4.synthetic.v1.toml) · [Research review status](RESEARCH_REVIEW_STATUS.md)

| Amendment | Review decision | Evidence required before adoption |
| --- | --- | --- |
| A1 · As-of contract selection | Defer historical adoption. The archival roster and fixed-roll release describe retrospective observations. | Prove the effective-dated outright roster and expiries, available predecessor volume or defensible bounds for every selectable contract, initialization and tie handling, and fail-closed missing or roll treatment. |
| A2 · Cash grid, clocks and costs | Rehearse under the existing synthetic proxy. Defer historical adoption. | Bind the dated cash/Globex schedules, approve how verified no-trade minutes affect volume and eligibility, establish publication/revisions or approve an explicit proxy, and resolve fees and the paired late-fill exclusion policy. |
| A3 · H1 zero, predecessor and decomposition | Ready for protocol review. Historical implementation remains pending. | Freeze scheduled same-contract predecessor semantics, matched zero-signal scoring, diagnostic return and morning RV definitions, regression sample and rank policy. Exercise constructed holidays, rolls, missing predecessors and symmetric comparator costs. |
| A4 · H4 first eligible outside close | Existing frozen synthetic H4 behavior supports review of the proposed clarification. | Obtain sign-off on the inclusive 10:00–11:27 scan and one-tick threshold, the three consecutive valid closes, and the single consumed opportunity after rejection. Keep the synthetic definition and historical admission decisions distinct. |
| A5 · H6 moving anchor | Ready for protocol review. Historical implementation remains pending. | Freeze current and prior signed distances against their respective anchors, same-side contraction, lagged scale and equality/missing-input policy. Define momentum horizon and anchor-slope diagnostics, and test constructed moving-anchor and weighting cases. |
| A6 · Family, alignment and custody | Synthetic mechanics support review. Defer confirmatory adoption. | Freeze the ten-slot and untested-slot convention, per-hypothesis masks and common SPA sample, 20% rounding, month boundaries, inner folds and availability purging, and independent single-use custody. |

## GO / NO-GO

| Activity | Assessment | Basis |
| --- | --- | --- |
| Synthetic research and custody rehearsal | GO | Constructed fixtures, immutable split identity, one-shot claim and reproducible diagnostics |
| Read-only pilot and outright archive inventory | GO | Bounded metadata, coverage and checksum review |
| Admit historical sessions | NO-GO | Dated calendar, universe, coverage, original availability and admitted sample counts still require evidence |
| Historical strategy execution and holdout access | NO-GO | Admission and independent research authorization are unresolved and historical evaluation remains disabled |
| Certification, paper or live trading | NO-GO | Existing independent acceptance and certification gates remain in force |
