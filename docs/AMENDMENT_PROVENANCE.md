# Amendment provenance

**A01–A12 provenance UNRESOLVED.** The expected authority is the original EXP-001 v0.2.0 review bundle and its amendment register. [Repository review status](RESEARCH_REVIEW_STATUS.md), introduced in `69ac1f7`, reports prior verification of 12 indexed files and identifies the protocol SHA-256 as `ffb6145e3472bf04388cbae4416b42cceaddf9e98f591f2f50a6d75ba824dd47`. It records an independent **REVISE** decision on the original proposal and no reviewer disposition on v0.2.0. The digest and prior verification are documented provenance claims. Phase 2B could not verify the original bytes or locate the register on this machine.

The user supplied this unverified Mac locator:

```text
/Users/jonathancho/.codex/visualizations/2026/11/02/01a19e58-20bf-7a40-a596-5cc62e01becf/EXP-001-v0.2.0-review-bundle.zip
```

Local checks found the Windows status file at `C:/Users/johnn/Desktop/backtester-source-clean/docs/RESEARCH_REVIEW_STATUS.md`. The Mac path did not resolve from Windows. Name searches across accessible Desktop, Documents, Downloads, Codex visualization and attachment paths, targeted content searches across the NQ export and discovery documents, and reachable Git paths yielded no authoritative copy. Search coverage is limited to accessible local files and repository refs.

## Comparison with verified A1–A6

The discovery source is `C:/Users/johnn/Desktop/New folder/gpt-researcher/nq-alpha-research/HYPOTHESIS_AUDIT.md`, SHA-256 `296bee47838574d503520ff2bc02be149b3a211797a42b2b604b51f3abc56a29`. [Synthetic foundation](SYNTHETIC_RESEARCH_FOUNDATION.md) summarizes readiness. The [frozen H4 registry](../config/experiments/h4.synthetic.v1.toml) lists all six as pending. EXP-001's review summary identifies broad review domains, including authority, registries, source/calendar admission, availability/revisions, power and custody. Without the register, item-level correspondence, contradictions against the EXP-001 wording and approval status for A01 through A12 are all unresolved. Matching digits provide no evidence of equivalence.

| Verified discovery proposal | Concrete conflict or unresolved definition in the accessible evidence | Explicit decision required |
| --- | --- | --- |
| A1 · Candidate universe and selector | A1 proposes as-of eligible volume, nearest-expiry ties and monotonic expiry. The legacy selector uses target-day bar presence and lexical ties, and the terminal uses a fixed calendar roll. | Approve the dated universe, cutoff, volume metric and origin-available upper bounds, initialization and monotonic state after gaps, exact tie behavior, expiry and roll exclusions, and fixed-winner missing-target policy. |
| A2 · Cash grid, clocks and costs | A2 requires observed valid cash bars, while a confirmed no-trade minute can sometimes support a zero in volume arithmetic. The archive does not establish equal-time ordering. The provisional fee is $5 round trip, while the example config's $2 commission plus $1 exchange fee per side totals $6. | Approve cash and CME calendar authorities, early-close policy, no-trade treatment, actual or proxy clock, paired late-data handling and fee authority. Example values provide no measured historical fee. |
| A3 · H1 predecessor and decomposition | An immediately preceding scheduled cash date with the same valid outright differs from the preceding retained observation, which can skip dates. Zero paired arms differ from charging a comparator cost on an abstention. | Approve the predecessor and zero policy, raw diagnostic return and morning RV definitions, regression sample and rank-deficiency handling. |
| A4 · H4 first outside close | Synthetic behavior supports the inclusive 10:00–11:27 scan, one-tick threshold and three consecutive valid closes. A literal crossing rule could reject a 10:00 outside close, and retrying after failed confirmation changes the opportunity set. | Approve left-boundary qualification, confirmation and missing-input handling, and the single consumed opportunity. |
| A5 · H6 moving anchor | A1–A6 audit uses each close's own anchor. Comparing both closes with today's anchor can admit a different contraction. | Approve signed-distance formulas, lagged scale, equality and missing-input policy, anchor slope and momentum horizons. |
| A6 · Family, alignment and custody | Ten confirmatory slots differ from a three-rule family. Per-hypothesis eligibility masks and common SPA intersection address different sample definitions. Synthetic one-shot custody does not supply independent historical control. | Approve the family and untested slots, joint sample alignment, 20% rounding, calendar-month and inner-fold rules, embargo and purge, MDE/power plan, exposure register and independent holdout custody. |

If the bundle is supplied, verify each manifest member and the protocol digest, identify the original reviewer artifact and v0.2.0 handoff, trace each A01–A12 entry to its exact source section, and obtain an attributable disposition on specification and evidence/policy acceptance. The authority owner must resolve any conflicts and record the approved protocol version before historical admission. Phase 2B grants no amendment approvals.

## Reproduce the source search

```powershell
git show 69ac1f7:docs/RESEARCH_REVIEW_STATUS.md
git grep -l -i -e EXP-001 -e ffb6145e c2abb43
git log --all --name-only --pretty=format: |
  Sort-Object -Unique | Select-String 'EXP.001|amendment|protocol'
$roots = @("$env:USERPROFILE/Desktop", "$env:USERPROFILE/Documents",
  "$env:USERPROFILE/Downloads", "$env:USERPROFILE/.codex/visualizations",
  "$env:USERPROFILE/.codex/attachments")
foreach ($root in $roots) {
  if (Test-Path -LiteralPath $root) {
    rg --files --hidden --no-ignore $root -g '!**/.git/**' -g '!**/node_modules/**' `
      -g '!**/.venv*/**' -g '*EXP-001*' -g '*review*bundle*' -g '*amendment*register*'
  }
}
Get-FileHash '../New folder/gpt-researcher/nq-alpha-research/HYPOTHESIS_AUDIT.md'
```
