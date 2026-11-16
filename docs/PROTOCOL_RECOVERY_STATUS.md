# EXP-001 v0.2.0 protocol recovery status

Phase 2C · 2026-11-15 · Search base `f2ef963`

**Recovery incomplete.** The original protocol, A01–A12 register and the 12-member verification manifest were not recovered from the accessible evidence. The earliest repository record is `69ac1f7`, which reports that all 12 indexed files matched their SHA-256 digests. It records the following digest for the **protocol file**. The archive digest, manifest digest and individual register digest are absent from that record. The recorded independent **REVISE** disposition applies to the original proposal. The amended handoff was prepared and independent disposition remained pending in the recorded review. [Research review status](RESEARCH_REVIEW_STATUS.md)

```text
ffb6145e3472bf04388cbae4416b42cceaddf9e98f591f2f50a6d75ba824dd47
```

## Search and candidate disposition

| Evidence examined | Result |
| --- | --- |
| Source repository refs, remote-tracking refs already on disk, reflogs, path and content changes, and local Git object store | `git log --all --reflog -G 'EXP-001'` and searches for the digest prefix, amendment span and filenames led to status and audit references. The synthetic `backtester/experiments/protocol.py` is implementation source. SHA-256 over the exact bytes of all 344 local Git blobs, including unreachable blobs, found zero protocol digest matches. One unreachable text blob referred to the separate pending review in an earlier continuation draft. |
| Windows Desktop, Documents, Downloads, OneDrive, Codex visualization and attachment directories, and this chat's attachment inventory | Targeted bundle, protocol, register, manifest and artifact-ID filename searches found no review-bundle candidate. The Mac locator and its corresponding Windows visualization directory were absent. Some unrelated Documents subdirectories denied enumeration. No saved attachment was listed in this chat. |
| Local NQ export and discovery documents | Searched NQ report and documentation text, and export SHA-256, manifest and index files for the protocol name, digest prefix, register span and artifact locator. The export's similarly named acquisition amendment concerns the 2023 data package. Discovery references describe EXP-001's separate pending review. Neither yielded indexed EXP-001 source bytes. The exported backtester directories and discovery checkout tested here had no accessible Git history of their own. |

Supporting files were independently hashed for this review. The 2022 causal contract selection register, late-2023 contract-evidence CSV, October 22 historical availability feasibility report and dated NQ regime ledger matched their entries in `../NQ-Export/SHA256SUMS.tsv`. The discovery `HYPOTHESIS_AUDIT.md` matched the recorded SHA-256 `296bee47838574d503520ff2bc02be149b3a211797a42b2b604b51f3abc56a29`. Those matches support the evidence planning and the provenance of A1–A6. No bytes were available to reverify the protocol, register or complete review bundle. [Roster evidence](HISTORICAL_ROSTER_SOURCES.md#internal-evidence-references) · [Amendment provenance](AMENDMENT_PROVENANCE.md)

The search covered accessible local evidence and repository objects. The original Mac, other hosts, cloud backups and external custodians were unavailable to this search. No sealed holdout content was inspected. Conversation text and the recorded review summary supply leads only. A01–A12 cannot be compared item by item with A1–A6, so a crosswalk is deferred.

## Exact retrieval request for the research owner or original custodian

Please retrieve the original, byte-for-byte `EXP-001-v0.2.0-review-bundle.zip` from the Mac or its original backup. Check this recorded locator and any artifact export tied to it.

```text
/Users/jonathancho/.codex/visualizations/2026/11/02/01a19e58-20bf-7a40-a596-5cc62e01becf/EXP-001-v0.2.0-review-bundle.zip
```

Transfer it through an access-controlled location outside Git. Include the original manifest and all 12 indexed files, with exact relative paths and recorded SHA-256 values. Identify the protocol and A01–A12 register paths, the original independent REVISE artifact and the amended handoff. Supply the original archive or manifest checksum or signature if recorded, its source, and any subsequent attributable reviewer disposition tied to a specific version. Record the custodian, source host or backup, original object or version identifier, transfer date and any known custody gap. If the ZIP is lost, supply the original member bytes, original manifest and independent evidence binding them to the reviewed handoff. If only part survives, identify each missing file and the backup or custodian searched.

On receipt, preserve the original bytes, verify any separately recorded archive or manifest digest or signature, and verify all indexed members against the original manifest. Match the protocol independently to the digest above. Confirm the register and review artifacts belong to the same release. Only then extract exact clause and amendment references, compare against the pinned A1–A6 discovery audit, and record specification and evidence/policy disposition separately. A byte-integrity match alone supplies no review approval.
