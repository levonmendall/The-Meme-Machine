# Block-admission specification-conformance audit

**Finding: A — the admission implementation matches the pre-existing frozen block-admission contract for the categories examined.** No admission-policy repair or historical reclassification is justified by this audit.

This is a read-only audit of section 10 of the attached reconstruction brief. Its authority is the accepted runtime `1c6da29d08bfbe42e39ea1c8068933aae6b15cdb`, cohort `prospective-four-lane-v6-coverage-repair-20260924`, and the earlier commits below. The four audited files are also unchanged at the initially inspected checkout `2e9f97cb6f1627718a05516287e804242e6cbde2`. No P&L, winner/loser outcome, natural-run continuation, or proposed new threshold was used to choose this finding.

The result is deliberately scoped: **accepted under the frozen rule does not mean complete target-market coverage or sufficient evidence of profitability.** The existing assurance contract separates these claims.

## Pre-existing authority

| Authority | Exact location and meaning |
| --- | --- |
| `be411621086f84b28ba6a0c942325bbf76cd46c9` | Introduces `certification/profitability_protocol.json`, including `evidence_quality.maximum_infrastructure_censoring_fraction = 0.1`. The protocol forbids threshold tuning and outcome-dependent run selection during a cohort. It does not introduce a separate minimum evidence-completion fraction or maximum stream-gap fraction. |
| `3562d00b668e2fce64adb0e9b9f7d808d2845abd` | Introduces the carried executable rule in `certification/prospective_acceptance.py::_infra_fraction`: the four numerator classes are `unique_capacity_censored`, `unique_consumer_deadline`, `unique_local_budget_exhausted`, and `unique_provider_failed`; denominator is positive integer `unique_admitted`, falling back to positive integer `unique_evidence_requested`. |
| `f7e053a7dc4c91c506aaf2116a33e3ce4fbd22fa` | `certification/prospective_acceptance.py::_infra_fraction` adds the independently measured scan-censoring fraction and takes the maximum of scan and candidate fractions. The four candidate numerator classes remain unchanged. |
| `f24811098a39745ccc8734203bef46992949a704` | Introduces required market assurance in the protocol and `prospective_acceptance.py::{make_record,admitted}`. `make_record` requires matching runtime SHA, matching run ID and `operational_validity == 'valid'`. The same commit introduces `market_assurance.py` with separate operational and market-observation validity. |
| `f24811098a39745ccc8734203bef46992949a704` | `certification/MARKET_ASSURANCE_HANDOFF.md`, “Measured breadth and limits”: “No numerical breadth threshold was introduced. Existing infrastructure censoring remains the economic gate.” Its “Engineering changes” item 2 expressly separates operational validity, market-observation validity and economics. This is affirmative pre-existing authority, rather than an inference from today's code alone. |
| `e497aeea20d9b41df54e105ad90c93ca048a9bfd` | Advances `profitability_protocol.json` to the v6 coverage-repair cohort and changes frozen source-diff identities. It leaves the 0.1 gate, `_infra_fraction`, `make_record`, and `admitted` unchanged. Its `market_assurance.py` additions report pending-at-close and discovery-acquisition problems as coverage gaps without adding an admission threshold. |
| `1c6da29d08bfbe42e39ea1c8068933aae6b15cdb` | Exact accepted runtime inspected. The protocol still requires market assurance, 0.1 maximum infrastructure censoring, complete telemetry, unchanged freshness/finality, and no threshold tuning; see `profitability_protocol.json` lines 8–21 and 53–66. The executable gate is `prospective_acceptance.py` lines 62–73 and 396–425. |

The exact runtime Git blob identities are:

| File | Blob SHA |
| --- | --- |
| `certification/profitability_protocol.json` | `8584ff92408aadfa0ad3cbf254a27c9a4ee3895d` |
| `certification/prospective_acceptance.py` | `ab701adc8733bbdd892e3a5fb658f44133410698` |
| `certification/market_assurance.py` | `a5ea702fe77fd39f9a3914f3f3e05119a15c598d` |
| `certification/MARKET_ASSURANCE_HANDOFF.md` | `47d9adfde6a93e4675ca1eedb981435c0b98574a` |

## What the numerical rule actually measures

For a lane, the frozen implementation calculates:

1. `scan_fraction = infrastructure_censored_scans / (completed_scans + infrastructure_censored_scans)`, or zero when no scans are counted.
2. Candidate denominator `D = unique_admitted` when it is a positive integer; otherwise `unique_evidence_requested` when that is a positive integer.
3. Candidate numerator is the sum of the four nonnegative unique-class counts listed above, capped at `D`. If no valid candidate denominator exists, the function returns `scan_fraction`.
4. The lane's infrastructure fraction is the maximum of the scan fraction and the capped candidate fraction. Admission requires each lane's fraction to be finite, nonnegative and **at most 0.1**.

These are unique counts within each reason, not a newly computed union of all failed candidate identities. The cap and summation behavior are themselves part of the existing executable rule; this audit does not change them or reinterpret the denominator as the entire discovered market.

The infrastructure fraction is only one required condition. `make_record` also requires an engineering pass, verified runtime freeze and chain binding, matching lane identity, reconciled accounting, complete telemetry, unchanged freshness/finality, no unexpected exit, no restart, no forced settlement, and valid identity-bound operational assurance. `admitted` requires the preserved passing flags, all four lanes, the relevant safety fields, and the bounded infrastructure fractions. No profit/loss field selects admission.

## Why the separately reported conditions do not establish B

| Reported condition | Existing treatment |
| --- | --- |
| `reconstruction_incomplete` | Added to `coverage_gaps` by `market_assurance.py::lane_report`; not independently added to `_infra_fraction`. A coincident provider/deadline/budget/capacity failure still counts through its existing numerator class. |
| `stream_coverage_loss` | Reported when stream gap, parse-failure, capacity-loss or creation-capacity-loss counters are positive. It changes coverage health, not automatically operational admission. |
| `coverage_degraded` | A market-observation status, separate from `operational_validity`. It is not a frozen automatic block rejection and has no separate numerical threshold. |
| Stale candidate evidence | Preserved through classifications such as `stale_before_evidence`; no standalone stale-count numerator is specified. The frozen freshness/finality checks remain mandatory. Correctly rejecting a stale candidate is different from authorizing a decision with invalid stale evidence; a demonstrated conformance or integrity violation is already an admission failure. |
| Pending discovery/evidence at observation close | Reported as a coverage gap under the v6 reporting additions. It is not converted by those additions into a new censoring threshold. Valid continuation semantics still require their separate engineering analysis. |
| Failed or unestablished strategy conformance; failed accounting proof; position invariant or continuity violation; unexpected process failure | Explicit operational admission failures, independent of coverage fractions. These must continue to fail closed. |

At the accepted runtime, `market_assurance.py` lines 272–293 separately construct coverage gaps and operational admission failures. Lines 387–398 preserve that split in the final report. `prospective_acceptance.py` lines 400–401 deliberately reads `operational_validity`, not `market_observation_validity`. This is consistent with the earlier written handoff.

The protocol's `telemetry_complete_required` and `freshness_finality_unchanged_required` do not state that every discovered candidate must complete full reconstruction. Valid early strategy rejections, unavailable historical evidence, pending work, and genuine acquisition failures need causal classification before a broader numerical admission policy can be designed. Relabeling all incomplete events as infrastructure failure would not be an implementation-only interpretation of the frozen contract.

## A, B and C disposition

- **A applies to the current audited rule:** the named censor classes, scan safeguard, 10% threshold, and separate operational assurance are supported by authority predating the accepted block.
- **B is not established:** no pre-existing requirement was found requiring all reconstruction-incomplete, stream-loss, degraded-coverage or stale-event counts to enter the censoring numerator or automatically invalidate a block. The explicit handoff points the other way.
- **C describes a possible future extension, not a reason to alter today's gate:** the frozen material does not specify an additional numerical standard for strategy-required evidence completion, recovered versus unrecovered stream gaps, or pending work at a measurement boundary. The present rule is specified; a broader rule needs an owner policy decision.

Accordingly, preserve classifications for censored run `35935431384`, accepted run `35949285193`, and `35956802640` or later blocks. This audit supplies no authority to rewrite them.

## Precise future owner-policy issue

If the owner wants preventable strategy-relevant reconstruction or stream loss to become an additional admission gate, a future cohort must freeze the following before its observation begins:

1. The unit and denominator: uniquely identified candidates that actually required full evidence under the strategy, including how revised candidate states and repeated requests are deduplicated.
2. Which causally proven failures count, with explicit treatment of valid early rejections, historical unavailability, recovered gaps, partial recovery, and candidates still valid at block close.
3. Whether stream loss is measured by unrecovered relevant events, required-evidence candidates, time intervals, or another defined quantity, plus how an unknown denominator is treated.
4. The allowed limit or categorical rejection rule, and how it combines with the existing infrastructure fraction without accidental overlap or double counting.
5. Attribution across block boundaries, durable carryover and successor identities, preserving append-only history and excluding incompatible revisions from a single cohort.

This audit recommends **no numerical value** and makes no policy change. Missing authority for that additional rule is not permission to derive a threshold from observed returns or retrofit current history.

## Read-only verification

Git history, blame and exact-runtime blobs were inspected; no source, admission record, workflow, market run or historical artifact was modified. Fifteen isolated assertions executed only the exact-runtime AST definitions of `_infra_fraction`, `_finite` and `admitted`, using in-memory, outcome-free fixtures. They verified the four included categories, the four separately reported categories' lack of independent numerical effect, scan fallback, evidence-request denominator fallback, numerator cap, the existing 10% boundary, rejection above it, required assurance failure and missing-lane rejection. All 15 passed. No application imports, provider requests, workflow dispatches or runtime database writes were required.
