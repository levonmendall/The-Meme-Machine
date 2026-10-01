# Stage E housekeeping binding-work attribution

PAPER ONLY. Static inspection and arithmetic over preserved text only. Stage E: **RED**. Stage F: **NOT STARTED**. Material workload budget: **4/6 consumed; 2/6 unused**. Preparation overlap remains retired.

**Conclusion: the ordering mechanism is statically possible, and the supplied receipt-74 decision makes archive infeasible. The required runtime service/yield chain and safe preceding-turn counterfactual are not established by the evidence readable in this session. Capacity relevance: UNKNOWN.**

This is an evidence-insufficient attribution, not a finding that existing ordering is noncausal. No fix or candidate repair behavior is proposed.

## A. Pinned identities and evidence boundary

| Identity | Value |
| --- | --- |
| Repository | levonmendall/The-Meme-Machine |
| Production source | dc08f9064cf5e37b63f383f52aa709d0afc1723f |
| Production tree | 68736cf664169dee665762019800bf87ca0f1f67 |
| Prior attribution / inspected evidence base | ef262691f428d9e54934690077eb80b38d79ac01 |
| Evidence-base tree | 34263b86ba4bacdbf5aaa441c774457aa3135548 |
| Preserved ablation publication | 3eeb02f060b4623b6842d8f18853e5340dec0684 |
| Material execution commit / tree | 6e104c122dc495d75bd8828a5fea7237b48effdf / 084245305a1bbe49c522b99be20396d633add6e2 |
| Existing run / job / attempt | 36771603217 / 110079106497 / 1 |
| Existing artifact | 11124508037; 934,841 bytes |
| Bound artifact ZIP SHA-256 | 485a522b8e1ab820674528905fa87e953cb444eade31c77635f5ba8cce2cdec6 |
| Control summary SHA-256 in binding | f5c78eb11a5a0906280c124c707d1c4d523c1e43285035d1dd36e5984d05012a |
| Execution harness SHA-256 in binding | 4f6f751a8efb5e7593d3444212ab4638d7126cec4131ba29807e390472003aa5 |

Read: [binding](https://github.com/levonmendall/The-Meme-Machine/blob/ef262691f428d9e54934690077eb80b38d79ac01/diagnostics/source-owner-ablation/BINDING.json), [control projection](https://github.com/levonmendall/The-Meme-Machine/blob/ef262691f428d9e54934690077eb80b38d79ac01/diagnostics/source-owner-ablation/CONTROL_ANALYSIS_LOG_PROJECTION.json), [preserved CI log](https://github.com/levonmendall/The-Meme-Machine/blob/ef262691f428d9e54934690077eb80b38d79ac01/diagnostics/source-owner-ablation/CI_JOB_LOG.txt), [preservation harness](https://github.com/levonmendall/The-Meme-Machine/blob/ef262691f428d9e54934690077eb80b38d79ac01/diagnostics/source-owner-ablation/harness.py), pinned production source, root `AGENTS.md` and `BUILD_STATUS.md`. The complete repository trees were compared by path, Git blob SHA and mode: **all 1,152 production blobs/modes match the inspected evidence base**, which contains 1,196 blobs. No production source modification is part of this task.

| Inspected production file | Git blob SHA |
| --- | --- |
| meme_machine/solana_maintenance_runtime.py | 73a2801136483d47e84e964435d11590f3ba0cdc |
| meme_machine/solana_evidence_plane.py | 34ef169e139baebfe12f9801b12f1774c94eaa05 |
| meme_machine/solana_evidence_control.py | 90628ffdbe98e24a758c320e8965a99a75326272 |
| meme_machine/solana_maintenance_arbiter.py | 337bb569ec5920497dd012c01a14c36fdea2518a |
| meme_machine/solana_maintenance_state.py | 92e7d69d4e5af4f5946aaad19ce4062563670976 |
| meme_machine/solana_evidence_service.py | a54d3ed1876f138a6b2db37ef917f414173869db |
| meme_machine/solana_retention_outcome.py | ab602323f7a1d2bbce91c12b0a79d9f388337018 |

**Access limitation:** the existing artifact download succeeded and returned a ZIP file reference. The exposed tools provide no local filesystem reader, shell or ZIP extractor. Its members and bytes were not read or independently hash-verified here. Repository branch/tree inspection found the prior attribution report, not the newer mature-receipt reconstruction described by the user. A repository path/ref for that newer reconstruction was requested during work; none was supplied before this report was prepared. No CI extraction job or diagnostic was started to work around this limitation.

The following members are bound in the preserved artifact; a hash binding is not inspection of their contents:

| Raw member | Bound SHA-256 |
| --- | --- |
| control/archive-cycles.json | 1cae2d97792a8d56fff7d4f535764971460ebe9d9286b2bb0f9a2f95f0a0952f |
| control/archive-cycle-decomposition.json | 4f3bf8bc6ea03a9e88136334f4a9d44fbcb3d31ef333e352c66a01899dc694f1 |
| control/source-batches.json | a03b1d85f19b1f09a21dcea445c200368b32d8c3a9b8176f4e39b0d87a524b84 |
| control/timeline.jsonl | 5906aa33d993790e28b740440c37acee0583b9632ff74d480c3c2ba1584b14ee |
| control/native-health.json | 948cfefaae724d61d5ecaa1ff5d753ee151d173a45311fdd6ad6de551c6bdde5 |
| control/terminal-ring.json | 2ab1e7ceb9535dfab5d524d972ab0ad234b2d0d4bc0725d21323f6fe7cbacf25 |

The projection contains six selected `analysis.sampled_points` and a terminal decision. These are not the complete native turn history. A nearby observer sample is not automatically a member of receipt 74 or 109.

The user's latest reconstruction is accepted as **supplied evidence**, separately from independently inspected source/text:

| Receipt / population | Supplied result |
| --- | --- |
| 74 | 3.393 s inter-slice gap; 12 retirement turns; 2.170 s source execution |
| 109 | 4.352 s ready-to-first-commit; 14 retirement turns; 3.057 s source execution |
| 36, representative | 0.152 s ready-to-first-commit; 0.144 s source execution |
| 85 mature receipts | No ready-receipt turn used the suspected one-second idle branch |
| 129 same-flight pending transitions | Resubmission composite peak 1.025 ms |
| One receipt-74 native decision | Archive ready; retirement ready; housekeeping remaining time 7.782 s; retirement the only legal side |

These supplied facts close the generic resubmission/idle investigation for this task. They do not provide native event identifiers, complete needs or housekeeping progress/outcomes.

## B. Relevant pinned source semantics

### A–B: housekeeping demand and the effective retirement deadline

[MaintenanceRuntime._demands()](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_runtime.py#L169) constructs ordinary retirement units as `retirement_eligible + continuity + int(floor_changed)`. Record safety uses oldest-record residence; nonrecord work uses its own service origin. At lines 202–210 it explicitly constructs:

```python
key = 'retirement', '__housekeeping__'
if observation.housekeeping:
    since = self._nonrecord_service_origin(key, now, wall_now)
    needs.append(Need(key[1], key[0], observation.housekeeping, 0,
        since + self.leases.drought, None, 0))
```

Thus housekeeping is **side = retirement; scope = __housekeeping__; records = 0; no recovery excess**.

[DebtAgeAdapter housekeeping observation](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_state.py#L337) counts at most three **nonempty-work witnesses**, one each for unreferenced `archives`, `hot_chunks` and `address_keys`. Housekeeping units are not a garbage-row count and do not measure the execution cost of a slice.

[_nonrecord_service_origin()](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_runtime.py#L124) persists first required work, consults only the matching scope/side's positive native progress timestamp, projects it with the existing clock, and uses the later of the persisted start and that progress. Another scope's retirement or archive progress cannot advance the housekeeping obligation. Observing no housekeeping work resolves the persisted nonrecord demand.

[MaintenanceArbiter.choose()](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_arbiter.py#L175) takes each active scope's minimum of safety, successful-service origin plus drought, and active recovery deadline; the side deadline is the minimum over all active scopes. Consequently housekeeping can tighten retirement's **effective** deadline. The housekeeping safety field itself represents a service obligation projected with clock uncertainty. A projection's `binding = safety` for housekeeping is not evidence of a separate record-retirement safety need.

With existing leases owner = 3 s, execution = 3 s, clock error = 3 s, worker = 15 s, drought = 45 s. A selected side requires its own deadline strictly after `now + 3`; every demanded peer requires its deadline strictly after `now + 9`. Clock error is already accounted for where projected; it must not be subtracted again.

### C–D: per-scope work precedes housekeeping and can yield before it

[EvidenceWriter.retain()](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_plane.py#L641) validates `1 <= max_records <= 1000`, resets committed-outcome accounting, rotates through cursor scopes, and performs per-scope record retirement, continuity deletion and floor updates before the housekeeping block at lines 728–746.

For each scope, record slices are at most 256 rows; the loop's per-scope record budget is `max_records`, not a global 1,000-record budget across all scopes. Continuity deletes have their own per-table `max_records` bounds. Before mutation, the native code rechecks hot-body floor, recent coverage, active interests, unresolved gaps, account floor and the prior floor; floor advancement is monotone. Only archived body-null records below the resulting floor can retire.

Per-scope record/continuity/floor work and its maintenance-progress entry commit together at lines 703–726. The `after_commit` callback updates `RetentionProgress` only after durability.

[_retention_transaction()](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_plane.py#L783) protects the bounded per-scope mutation with `_retention_atomic`, clears that flag after the transaction, records the committed outcome, updates the rotation hint and then evaluates the cooperative yield. An urgent request yields at that committed boundary. Normal source work can consume the two additional-slice allowance; a subsequent requested source yield raises `evidence_background_yield` and rotates before the next admission. Those raises unwind `retain()` **before its later housekeeping block**. An urgent yield is also possible in the no-op scope branch at lines 690–698.

[PriorityOwner._run()](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_control.py#L55) selects nonurgent source/background work by common FIFO sequence; urgent priorities retain precedence. Its SQL handler interrupts background work only for queued priority below 2 and does not interrupt atomic per-scope retention mutation.

The nested [yield_retention_boundary()](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_control.py#L112) returns `urgent` for queued priority below 2, `source` for queued priority 2 or 3, and no yield for an empty queue or priority at least 4. These source rules establish possible control flow, not that any particular preserved turn followed it.

### E: separate housekeeping durability and progress visibility

The housekeeping block uses bounded lookahead `max_records + 1` per garbage table, deletes at most `max_records` rows from each of the three tables, and writes:

```python
maintenance_progress(self, '__housekeeping__', 'retirement', removed)
```

in the **same transaction as the garbage deletions** ([retain() final garbage collection](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_plane.py#L728)). It retains immutable archive files. The existing block bounds operational garbage deletions by at most 3 × max_records, separate from record retirement. It uses ordinary `transaction()`, not `_retention_transaction()`; it does not acquire the per-scope atomic shield or participate in that helper's source-boundary allowance.

[maintenance progress ledger](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_state.py#L118) accepts progress only inside a transaction and updates the matching scope/side's cumulative units and timestamp only for positive units. Housekeeping records stay zero.

[_native_progress()](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_runtime.py#L244) compares cumulative ledger rows with the pre-turn observation. It emits record progress `dr` instead of total units `du` for a scope with currently required record retirement. Therefore per-scope continuity/floor work can be hidden by a zero record-progress result. **This ambiguity does not apply to __housekeeping__: it never belongs to record_required, so its entry exposes du.**

[turn()](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_runtime.py#L263) performs one fresh owner-entry observation/choice and at most one selected native side. Readiness is observed at execution. A retirement decision calls `self.state.retention()`; the `finally` block reads native progress, completes the arbiter and records both `durable_progress` and `durable_records` in the production event. Positive progress advances only its own arbiter service origin ([complete()](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_maintenance_arbiter.py#L217)).

[ServiceState.retention()](https://github.com/levonmendall/The-Meme-Machine/blob/dc08f9064cf5e37b63f383f52aa709d0afc1723f/meme_machine/solana_evidence_service.py#L749) calls `retain(..., max_records=1000, archive_first=False, checkpoint=False)`, catches recognized cooperative retention yields, and returns the already-committed partial `RetentionOutcome`. Accordingly:

- A retirement turn may return successfully with `interrupted = true` and `yield_reason = source/urgent/urgent_sql`.
- A native event reason `debt_surplus` or `peer_reservation`, and an absent outer error, do **not** exclude a cooperative yield inside retention.
- An empty `durable_records` map, an aggregate retired-record count, floor changes or continuity rows do not prove housekeeping service.
- A stage-retention error count is not a per-turn yield-reason ledger.

These semantics define the evidence test; they do not prove the runtime consequence.

## C. Receipt 74 retirement-turn timeline: unresolved native chain

The supplied offline reconstruction fixes the interval as the gap between the preceding and next archive slice for receipt 74, with 12 intervening retirement turns and approximately 3.393 s of elapsed delay. The published mature maximum summed inter-slice gap is 3.392566550 s; the identity association to receipt 74 comes from the user, not an independently inspected per-flight record.

**The complete native chain cannot be reconstructed from the readable projection.** Both archive-slice endpoints' clocks, every intervening native sequence, the native progress maps and retention outcomes are unavailable. The following inventory explicitly keeps all twelve reported turns unresolved. Ordinals are inventory slots, **not native sequences, timestamp estimates or synthetic decision records**.

| Reported retirement-turn slot | Native sequence | Timestamp | HK active / materially binding | Retention yield / reason | Housekeeping service classification |
| --- | --- | --- | --- | --- | --- |
| 1 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 2 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 3 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 4 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 5 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 6 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 7 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 8 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 9 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 10 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 11 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 12 | unavailable | unavailable | unknown | unknown | UNKNOWN |

At least one of these reported retirement turns had the supplied 7.782 s housekeeping headroom and only retirement legal; the ordinal of that turn is not supplied. Its service classification is **UNKNOWN**, not an inferred failure to service housekeeping.

Required fields remain explicit:

| Requested field for every receipt-74 turn | Evidence available here |
| --- | --- |
| Native sequence; timestamp | Not supplied; not in published per-flight/projection data |
| deadline_by_side | One supplied relative housekeeping bound; full per-turn maps unavailable |
| Native need ordering / scopes | Unavailable; preserved sampled needs elsewhere cannot be assigned to receipt 74 |
| Housekeeping units | Positive at the supplied constrained decision; exact units unavailable |
| Housekeeping absolute deadline / headroom | One headroom = 7.782 s; absolute deadline and progression unavailable |
| Retirement record debt by scope | Unavailable for the receipt-local turns |
| Continuity / floor work | Unavailable per turn; not inferred from retirement records |
| Original decision reason | Unavailable; selection of retirement does not distinguish debt_surplus from peer_reservation |
| Owner queue / execution | Receipt-local per-turn values unavailable; source interval aggregate = 2.170 s, supplied |
| Cooperatively yielded; yield reason | Unavailable |
| durable_progress | Unavailable, including __housekeeping__ |
| durable_records | Complete receipt-local maps unavailable |
| retention_outcome | Unavailable |

**Positive __housekeeping__ durable progress in this gap: undetermined.** No such native entry was readable here. That is an evidence-access statement, not a count of zero serviced turns.

## D. Second long-delay receipt and representative control

Receipt 109 is the supplied mature maximum ready-to-first-commit case: 4.352 s, 14 retirement turns and 3.057 s source execution. The independently readable cohort maximum is 4.352265500 s. The receipt identity and turn count are supplied; its raw flight was not inspected.

| Reported retirement-turn slot | Native sequence | Timestamp | HK active / materially binding | Retention yield / reason | Housekeeping service classification |
| --- | --- | --- | --- | --- | --- |
| 1 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 2 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 3 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 4 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 5 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 6 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 7 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 8 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 9 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 10 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 11 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 12 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 13 | unavailable | unavailable | unknown | unknown | UNKNOWN |
| 14 | unavailable | unavailable | unknown | unknown | UNKNOWN |

The ready marker, first archive-slice start, per-turn needs/progress and housekeeping demand are unavailable. It cannot be claimed that housekeeping was active in any or all of these fourteen turns, or that receipt 109 repeats the proposed mechanism.

Receipt 36 supplies a typical comparison: 0.152 s ready-to-first-commit with 0.144 s source service. It does not establish housekeeping state or service. The representative comparison is retained so the long-delay cases are not presented as the ordinary receipt behavior.

## E. Housekeeping demand, deadline and progress timeline actually readable

The entire six-point subset in the control projection is shown below. All decision clocks remain in their original process monotonic coordinate; observer elapsed and frame values are contextual samples, not clock replacements. Precision below reproduces preserved values, not uncertainty-free timing claims.

| Projection index | Observer elapsed / frame | Native choose at | HK units | HK effective deadline / headroom s | HK service deadline | Retirement side deadline | Earliest other retirement deadline | Archive ready | Selected / feasible sides |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | --- | --- |
| 0 | 180.311715368 / 664 | 220.082555712 | 0 | unavailable / unavailable | unavailable | unavailable | unavailable | true | none / none |
| 1 | 210.337256385 / 775 | 250.361638100 | 2 | 290.030663013 / 39.669025 | 293.039577384 | 290.030663013 | 291.947883368 | true | retirement / archive, retirement |
| 2 | 240.382641366 / 866 | 279.775119465 | 2 | 308.375113726 / 28.599994 | 311.394148074 | 307.933293581 | 307.933293581 | true | archive / archive, retirement |
| 3 | 270.441284530 / 985 | 310.622627686 | 2 | 345.013635635 / 34.391008 | 348.025638843 | 345.013635635 | 350.530355930 | false | retirement / retirement |
| 4 | 300.470607412 / 1096 | 340.539222717 | 1 | 381.812527657 / 41.273305 | 384.824501202 | 377.647711039 | 377.647711039 | false | retirement / retirement |
| 5 | 330.547304289 / 1209 | 370.701192604 | 2 | 381.812527657 / 11.111335 | 384.824501202 | 381.812527657 | 398.530355930 | true | archive / archive |

The no-demand sample at 220.082555712 is followed in this published subset by housekeeping demand at 250.361638100. This identifies the earliest **readable positive sample**, not housekeeping's first activation in the run. Demand might have appeared and resolved between these sparse samples; its persisted first-required timestamp is not supplied.

Housekeeping's effective deadline changes from 290.030663013 to 308.375113726 to 345.013635635 to 381.812527657. It then remains 381.812527657 at the later sample and terminal decision. Such changes can arise from matching durable progress or a resolved and later reactivated nonrecord obligation. They are not proof of positive housekeeping progress without the native entry. These samples do not establish one continuously active demand episode.

At 340.539222717 housekeeping is active but Pump record retirement has an earlier deadline. At 279.775119465 PumpSwap record retirement is earlier. Housekeeping therefore does not monopolize retirement pressure even in the readable subset.

At terminal `at = 371.906104644`, frame 1214:

| Field | Preserved value |
| --- | --- |
| Archive ready / retirement ready | false / true |
| Archive deadline / headroom | 377.53035593032837 / 5.624251286 s |
| Retirement deadline | 381.8125276565552 |
| HK units / effective headroom | 2 / 9.906423013 s |
| HK service deadline / headroom | 384.824501202 / 12.918396558 s |
| Earliest other retirement deadline | 398.53035593032837 (Meteora safety) |
| Selection / feasible set | none / empty |
| Error | EvidenceUnavailable:maintenance_cannot_reserve_both_sides |

The terminal refusal is not a ready-archive decision with housekeeping headroom below 9 s: archive is unready and its own deadline cannot reserve retirement followed by archive. This separate preserved failure cannot be relabeled as the receipt-74 housekeeping ordering mechanism.

Preserved retirement needs for **every positive-demand point in the published subset** follow. `units minus records` means `continuity + int(floor_changed)` for real scopes; its split is not preserved in this projection. It is not measured work performed by that turn.

At `250.361638100` (near observer elapsed `210.337256385`, frame 775):

| Retirement scope | Record debt | Units minus records | Safety deadline | Service deadline | Active recovery deadline | Effective deadline / component |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| program:meteora | 256 | 5 | 306.530355930 | 291.947883368 | unavailable | 291.947883368 (service) |
| program:pumpswap | 254 | 5 | 305.530355930 | 294.990683861 | unavailable | 294.990683861 (service) |
| __housekeeping__ | 0 | 2 | 290.030663013 | 293.039577384 | unavailable | 290.030663013 (safety) |

Deadline ordering **derived from the preserved needs and pinned sorting rule**, not a preserved native `Decision.scopes` tuple: `__housekeeping__` → `program:meteora` → `program:pumpswap`.

Preserved durable-record map: `{"program:meteora":256,"program:pumpswap":254}`. Owner queue delay: 0.164951442 s; execution: 0.103385415 s. Native sequence, original decision reason, retention yield/outcome and `durable_progress` are unavailable in this projection.

At `279.775119465` (near observer elapsed `240.382641366`, frame 866):

| Retirement scope | Record debt | Units minus records | Safety deadline | Service deadline | Active recovery deadline | Effective deadline / component |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| program:meteora | 3072 | 5 | 322.530355930 | 314.700679998 | 381.530355930 | 314.700679998 (service) |
| program:pump | 762 | 5 | 325.530355930 | 322.373111376 | unavailable | 322.373111376 (service) |
| program:pumpswap | 2550 | 5 | 321.530355930 | 307.933293581 | 382.530355930 | 307.933293581 (service) |
| __housekeeping__ | 0 | 2 | 308.375113726 | 311.394148074 | unavailable | 308.375113726 (safety) |

Deadline ordering **derived from the preserved needs and pinned sorting rule**, not a preserved native `Decision.scopes` tuple: `program:pumpswap` → `__housekeeping__` → `program:meteora` → `program:pump`.

Preserved durable-record map: `{"program:meteora":304,"program:pump":153,"program:pumpswap":55}`. Owner queue delay: 0.658548865 s; execution: 0.066155202 s. Native sequence, original decision reason, retention yield/outcome and `durable_progress` are unavailable in this projection.

At `310.622627686` (near observer elapsed `270.441284530`, frame 985):

| Retirement scope | Record debt | Units minus records | Safety deadline | Service deadline | Active recovery deadline | Effective deadline / component |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| program:meteora | 2304 | 5 | 350.530355930 | 354.142308502 | 418.530355930 | 350.530355930 (safety) |
| program:pump | 204 | 5 | 354.530355930 | 351.917750120 | unavailable | 351.917750120 (service) |
| program:pumpswap | 1102 | 5 | 350.530355930 | 353.236209878 | 422.530355930 | 350.530355930 (safety) |
| __housekeeping__ | 0 | 2 | 345.013635635 | 348.025638843 | unavailable | 345.013635635 (safety) |

Deadline ordering **derived from the preserved needs and pinned sorting rule**, not a preserved native `Decision.scopes` tuple: `__housekeeping__` → `program:meteora` → `program:pumpswap` → `program:pump`.

Preserved durable-record map: `unavailable`. Owner queue delay: unavailable s; execution: unavailable s. Native sequence, original decision reason, retention yield/outcome and `durable_progress` are unavailable in this projection.

At `340.539222717` (near observer elapsed `300.470607412`, frame 1096):

| Retirement scope | Record debt | Units minus records | Safety deadline | Service deadline | Active recovery deadline | Effective deadline / component |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| program:meteora | 384 | 5 | 381.530355930 | 380.098630905 | unavailable | 380.098630905 (service) |
| program:pump | 204 | 5 | 381.530355930 | 377.647711039 | unavailable | 377.647711039 (service) |
| program:pumpswap | 340 | 5 | 381.530355930 | 380.330413580 | unavailable | 380.330413580 (service) |
| __housekeeping__ | 0 | 1 | 381.812527657 | 384.824501202 | unavailable | 381.812527657 (safety) |

Deadline ordering **derived from the preserved needs and pinned sorting rule**, not a preserved native `Decision.scopes` tuple: `program:pump` → `program:meteora` → `program:pumpswap` → `__housekeeping__`.

Preserved durable-record map: `{"program:meteora":384,"program:pump":204}`. Owner queue delay: 0.181525254 s; execution: 0.128492620 s. Native sequence, original decision reason, retention yield/outcome and `durable_progress` are unavailable in this projection.

At `370.701192604` (near observer elapsed `330.547304289`, frame 1209):

| Retirement scope | Record debt | Units minus records | Safety deadline | Service deadline | Active recovery deadline | Effective deadline / component |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| program:meteora | 8704 | 5 | 398.530355930 | 412.157027410 | 457.530355930 | 398.530355930 (safety) |
| program:pump | 561 | 5 | 414.530355930 | 409.946082115 | unavailable | 409.946082115 (service) |
| program:pumpswap | 3798 | 5 | 405.530355930 | 411.295479037 | 467.530355930 | 405.530355930 (safety) |
| __housekeeping__ | 0 | 2 | 381.812527657 | 384.824501202 | unavailable | 381.812527657 (safety) |

Deadline ordering **derived from the preserved needs and pinned sorting rule**, not a preserved native `Decision.scopes` tuple: `__housekeeping__` → `program:meteora` → `program:pumpswap` → `program:pump`.

Preserved durable-record map: `{"program:meteora":368,"program:pump":144}`. Owner queue delay: 0.185692063 s; execution: 0.031767354 s. Native sequence, original decision reason, retention yield/outcome and `durable_progress` are unavailable in this projection.

These scope/deadline tables establish competing needs at the sampled decisions. They do not complete receipt 74 or 109's turn chain.

The required recurrence questions remain:

| Question | Supported answer |
| --- | --- |
| First housekeeping activation | Unknown; earliest readable positive sample at 250.361638100 |
| Continuous activation during receipt 74 | Unknown; at least one active, feasibility-determining decision supplied |
| Retirement turns while active in receipt 74 | Unknown among the 12 reported turns |
| Retirement turns while active in receipt 109 | Unknown among the 14 reported turns |
| Number servicing housekeeping | Unknown; no receipt-local positive __housekeeping__ entry read |
| Repeated source/urgent yields before the block | Not established |
| Eventual housekeeping service and timing | Unknown |
| Continuous late housekeeping across the whole mature cohort | Not established; sampled deadlines renew/change |

## F. Housekeeping service test and cooperative-yield attribution

A turn is **HOUSEKEEPING_SERVED** only when its preserved complete native `durable_progress` map has a positive `__housekeeping__` entry. For a not-served yield classification, the native zero/absent positive entry must be joined to preserved retention control flow showing a source/urgent boundary before the final housekeeping block. A generic error or interrupted outcome without the required progress evidence is insufficient.

| Classification | Minimum evidence needed |
| --- | --- |
| HOUSEKEEPING_SERVED | Positive native durable_progress.__housekeeping__ on the matched turn |
| HOUSEKEEPING_NOT_SERVED_YIELDED_BEFORE_BLOCK | No positive native HK progress, plus matched source/urgent pre-block yield evidence; preserve other committed work/outcome |
| HOUSEKEEPING_NOT_SERVED_OTHER_REASON | Native absence of HK service and a preserved different reason for failure to service |
| UNKNOWN | Progress, turn matching or reason insufficient |

For the supplied constrained receipt-74 decision the classification is **UNKNOWN**. In the readable sampled subset, retirement at 250.361638100 and 310.622627686 has housekeeping as its earliest obligation; both service classifications are **UNKNOWN**. The latter has archive unready, so it is not evidence of delaying an otherwise-ready archive. Retirement at 340.539222717 is not housekeeping-binding and is excluded from that binding-turn test. Archive-selected samples are not retirement service attempts.

The preserved control aggregate has 209 `stage.retention` calls and 176 stage errors. Those are whole-arm counts, not the identities/reasons of the 12 or 14 receipt-local calls. They cannot establish repeated yields, zero housekeeping service, wasted rollback, or the number of missed housekeeping opportunities in either receipt.

The preservation harness explains the limitation:

- [harness](https://github.com/levonmendall/The-Meme-Machine/blob/ef262691f428d9e54934690077eb80b38d79ac01/diagnostics/source-owner-ablation/harness.py) lines 108–132 reconstruct fresh native needs, deadlines and feasibility after the real choose call.
- Lines 421–433 keep that explanation in `G.latest`; they do not store native `Decision.sequence`, `reason` or `scopes` in it.
- Lines 344–370 append flight-turn submit/entry/exit clocks, readiness/pending booleans, selected side, error and `durable_records`. They omit `durable_progress`, per-turn needs/deadlines and `retention_outcome`.
- Observer lines 232–245 can preserve an immutable native observation, including cumulative progress, in raw timeline data, but deliberately remove the duplicate production arbiter ring from periodic `production_stages`.
- The terminal raw native health and terminal ring are separately bound members. Their contents and retained sequence coverage were not inspected here.

Therefore even an offline cycle/turn clock join alone would not satisfy the positive-housekeeping test. The existing native ledger/ring/observation entries must be read and matched where retained; any eviction gaps must remain unknown. No assertion is made that the required evidence is absent from the original artifact.

## G. Archive feasibility and bounded counterfactual

### The supplied constrained receipt-74 decision

Let `t` be that actual preserved decision time, without inventing its absolute value. Its supplied effective housekeeping headroom is 7.782 s. If housekeeping determines retirement's minimum, then:

```text
D_retirement = t + 7.782
archive's reserved peer finish = t + 3 + 3 + 3 = t + 9
required: t + 9 < D_retirement
result: false, by 1.218 seconds
```

Thus archive is infeasible under the existing reservation rule despite readiness. The supplied reconstruction states retirement was the only legal side; the exact native sequence and full archive deadline are not given. This establishes the arbitration consequence of the supplied deadline. It does not show what the selected retirement call durably serviced or why housekeeping persisted.

### Readable decisions with archive ready and housekeeping earliest

| Native decision time | HK determines retirement minimum? | Archive feasible with actual HK deadline? | Effect of hypothetically removing only HK |
| --- | --- | --- | --- |
| 250.361638100 | Yes; HK headroom 39.669024913 s | Yes | Retirement minimum would still be 291.947883368, Meteora service |
| 279.775119465 | No; PumpSwap service earlier | Yes | No change to minimum: 307.933293581 |
| 370.701192604 | Yes; HK headroom 11.111335053 s | Yes, and archive selected | Retirement minimum would still be 398.530355930, Meteora safety |

These are static **constraint-isolation calculations**, not preceding-turn service counterfactuals. There is no claim that a prior turn could lawfully delete housekeeping, or that it would change selection; pressure ranking can still choose retirement among feasible sides. None of these independently readable ready-archive points demonstrates HK-induced infeasibility. The supplied receipt-74 point does, but lacks the rest of its native state.

### Required preceding-turn counterfactual, without resetting clocks

For an actual preceding legal retirement turn whose arbiter completion uses its preserved monotonic clock `e0`, suppose its preserved native housekeeping transaction timestamp is wall `a0` and it makes positive HK progress. At the next preserved decision `t1`:

- If housekeeping is observed empty, its need disappears.
- If work remains, the existing housekeeping safety deadline becomes `max(project(persisted_first_required), project(a0)) + 45`.
- Its successful-service deadline is `e0 + 45` if the already-active origin is advanced by the positive native completion.
- Other scopes retain their actual safety/recovery clocks and only their own legitimately serviced progress origins.

Let `D_other_retirement` be the minimum of all other preserved retirement deadlines at `t1`. Then:

```text
D'_retirement = min(D_other_retirement, D'_housekeeping)
               or D_other_retirement if housekeeping is observed empty

archive feasible only if:
  archive ready at t1
  t1 + 3 < D_archive
  t1 + 9 < D'_retirement
```

No actual `e0`, `a0`, `t1`, `D_archive`, or complete receipt-local `D_other_retirement` is readable for the relevant receipt-74/109 turns. Therefore this formula cannot be evaluated into a supported “archive becomes feasible” answer for either receipt. It does not remove record pressure, replace deadlines with fresh clocks, promise selection, or treat a future worker as already ready.

## H. Fairness, retirement and bounded-work implications

The user permits a candidate behavior only if all six defect conditions are proved. They are not, so **no repair shape is proposed**.

Pinned source gives the following constraints on evaluating a possible future bounded ordering change; it does not provide a safety certificate for moving housekeeping:

| Obligation | Source requirement and unresolved implication |
| --- | --- |
| max_records | Preserve per-scope record limits, 256-record mutation slices, continuity-table limits, and bounded GC lookahead/deletes. HK witness units do not prove a cheap slice. |
| Source cooperative yield | Current allowance is shared across a call and protects at most two additional per-scope commits after source demand. Added work before those boundaries cannot simply receive an extra unaccounted source-service allowance. |
| Urgent work | Preserve urgent SQL interruption for GC and preemptible preparation; GC currently has no retention atomic shield. Protecting GC as if it were a record slice would change urgent behavior. |
| Per-scope retirement safety | Retain hot-body, recent-coverage, interest/gap/account floors and body-null retirement checks; do not delete referenced operational data. |
| Continuity / floor advancement | These remain required native work with their own progress; GC service cannot be reported as their service. |
| Fairness | Keep urgent rotation and source-driven rotation after the existing grant. Earliest-HK service cannot repeatedly displace required record retirement or erase another scope's drought. |
| Record deadlines | Use preserved competing deadlines at the preceding turn. The 240 s and 300 s samples demonstrate that record scopes can be earlier than HK; “HK active” alone is insufficient. |
| Execution lease | Observation, planning, mutations and return still fit the existing 3 s call lease, with cooperative SQL expiry and mandatory elapsed check. Row bounds do not prove this elapsed bound. |
| Owner lease | No new owner admission/executor or altered queue priority. Already-selected retirement work must remain within that admission's existing lease. |
| Source advancement | Do not move required source service out of the timeline or use fresh source clocks to relax latched recovery deadlines. |
| Progress accounting | Positive __housekeeping__ units in the native transaction; records remain zero. No cross-scope service credit or fabricated successful progress. |

No preserved earlier-turn deadline, urgent/source queue state, housekeeping slice cost or lease residual supports condition 6 here. Being a bounded existing garbage-collection block does **not** by itself prove it could precede record work without violating an earlier obligation.

## I. Estimated capacity relevance

**Capacity classification: UNKNOWN.** No positive delay saving is established. This is not a measurement of zero real impact and not evidence of a negligible mechanism.

The two supplied long waits provide a gross investigated envelope of approximately **7.745 s**: 4.352 s for receipt 109 plus 3.393 s for receipt 74. The independently published aggregate maxima sum to 7.744832050 s, but their receipt associations and interval endpoints are supplied rather than independently joined here. This entire envelope is a deliberately loose upper ceiling for those two selected waits, **not delay attributable to housekeeping and not recoverable owner capacity**.

If the supplied source service totals are already clipped to those exact wait windows, and that required source service stays in the windows, their nonsource complements are approximately:

| Receipt | Wait | Supplied source service | Conditional nonsource complement |
| --- | ---: | ---: | ---: |
| 74 | 3.393 s | 2.170 s | 1.223 s |
| 109 | 4.352 s | 3.057 s | 1.295 s |
| Combined | 7.745 s | 5.227 s | 2.518 s |

This is only a conditional numerical ceiling on a change that leaves that source occupancy fixed. Rounded source figures, uninspected endpoints, necessary retirement work, earlier deadlines, checkpoint holds, and the housekeeping cost itself prevent treating these complements as promised savings. A change to batching or source admission would be a different counterfactual requiring separate evidence.

The whole 85-flight mature cohort's published ready/inter-slice wait envelope is 50.117166711 s. No fraction of it can currently be attributed to HK, and it is not the same population as the capacity interval.

The coherent observed capacity interval is 210.337256385–300.470607412 elapsed seconds, spanning 90.133351027 s:

| Quantity | Preserved value |
| --- | ---: |
| Inferred eligible arrivals | 87,912 records |
| Durable archive drain | 74,176 records |
| Net added eligible debt | 13,736 records |
| Arrival rate | 975.354838 records/s |
| Drain rate | 822.958418 records/s |
| Control drain deficit | 152.396420 records/s |
| Required increase over observed drain | 18.5181% |

As a scale comparison only, keeping those archived rows fixed while compressing that same interval enough to match its observed arrival rate would require approximately **14.083080 s** less elapsed time. This is arithmetic, not a scheduler model or capacity guarantee. The two selected wait envelopes cannot establish that reduction, and their relationship to the exact capacity interval has not been inspected. Other receipts' recurrence and lawful service displacement remain unmeasured here.

The same capacity interval contains **73,844 durably retired records** in the published prior analysis. That service cannot be discarded when assessing any capacity recovery. No claim is made that housekeeping explains the entire approximately 152 records/s deficit.

Maximum archive delay actually attributable to the proposed mechanism: **undetermined**. A positive lower bound, recurrence rate and legal upper saving bound require the native service chain that is missing from the readable evidence.

## J. Exact conclusion and hard stop

| Required defect condition | Assessment |
| --- | --- |
| 1. HK binding or feasibility-determining | Supported for the one supplied receipt-74 decision; sampled binding elsewhere also established |
| 2. Retirement legally selected | Retirement-only legality supplied for that decision; no native sequence attached |
| 3. Other work commits, but a pre-block cooperative yield prevents HK service | Not established for that decision or its surrounding receipt turns |
| 4. HK remains binding on subsequent arbitration | Not established for the receipt-local chain |
| 5. That persistence keeps an otherwise-ready archive infeasible | One deadline's infeasibility is supported; causal persistence and avoidable delay are not established |
| 6. Existing bounded HK service could fit the preceding legal turn without violating an earlier retirement obligation | Not established |

**Neither a bounded ordering defect nor existing ordering's noncausality is proved.** The supplied 7.782 s observation warrants this attribution question; static source order alone and retirement/source aggregates cannot resolve it.

The missing evidence is concrete: the receipt-74 and 109 endpoint/turn clock records plus retained native per-turn needs/deadlines/progress and retention yield/outcome evidence, including positive or unchanged `retirement / __housekeeping__` ledger values and competing earlier retirement needs. Where original rings or observations did not preserve a turn, its service/reason must remain UNKNOWN. This identifies an evidence requirement; it authorizes no new measurement, CI extraction, implementation or material run.

Verification here was read-only source/schema/tree inspection and offline arithmetic over existing projections and supplied figures. No production service, tests, pressure workload, material variant, new CI diagnostic, Stage E/F run, M1/preflight repair, successor freeze or arbiter modification was performed. The durable output is this report only, on a documentation branch with push CI suppressed.

**STOP. PAPER ONLY. Budget remains 4/6 consumed; 2/6 unused.**

HOUSEKEEPING_ATTRIBUTION: EVIDENCE_INSUFFICIENT
