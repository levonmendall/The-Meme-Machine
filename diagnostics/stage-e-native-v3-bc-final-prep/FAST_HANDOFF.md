# Fast handoff: read back, verify, prepare, stop

PAPER ONLY. These commands never authorize, dispatch, reserve or execute A/B/C. Preparation needs independent review before any future use. Stage F remains NOT STARTED.

Copy `HANDOFF_PLAN_TEMPLATE.json` to an operator-owned plan outside this frozen package. Supply genuine immutable publication commit IDs and independently recorded transport manifest hashes, actual campaign-relative paths and preservation receipts, exact original declaration/inventory hashes, and independently trusted owner/allocation public key files. Bindings must identify real preserved bytes; nulls, unresolved objects and asserted verdicts cannot validate.

Populate `A_preflight.bindings` using `SHARED_INPUT_SCHEMA.json` and `SHARED_INPUT_BINDING_TEMPLATE.json`. These are references into the completed, published A-preflight package, including the original `FRAMES.json` bytes and real stat continuity. Import no physical tape. Preserve every signed allocation capability file in the envelope under its original basename and exact bytes. Set `budget_values` to all reviewed integer bounds named in `STORAGE_BUDGET.json`; the tooling recomputes feasibility and refuses a reported shortfall. Missing physical receipts remain `AWAITING_A_PREFLIGHT_PHYSICAL_INPUT` and stop dependent handoffs.

Prepare B/C `preview_config` with exact future workflow/run/attempt binding, complete approved-harness path map, separate short B/C registries, immutable tape/inventory/assembly paths inherited unchanged from A, and complete future storage bounds. The registry and cache/publication destinations must be fresh; the approved execution-time admission will recheck that. Preparation does not create them. Registry strings must keep every native socket path shorter than 108 bytes; `bind_preview` checks this without inspecting production paths. Plan records may reference a path without touching it.

Evidence transport is an envelope of unchanged campaign bytes and its external preservation receipt, sealed with a fresh `RAW_INVENTORY.json`. Its transport class/campaign/declaration SHA must match the original. Existing trial/campaign seals stay inside the envelope unchanged. `campaign_relative_path` identifies the nested actual campaign; `preservation_receipt_relative_path` identifies its genuine final receipt. Shared preflight envelopes use class `PREFLIGHT`; preserved predecessor envelopes use `PRESERVED`. A transport seal cannot replace an original preservation receipt.

For future publication of actual, already-sealed evidence, the prepared tool path is `preservation.stage_transport(source, fresh_staging, class_id=..., campaign=..., declaration_sha256=..., inventory_name=...)`, then `preservation.publish_transport(staging, fresh_evidence_branch, parent_commit=..., api=GitHub())`. This requires an authorized GitHub credential. Publication uses a fresh `diagnostics/stage-e-native-v3-evidence/` ref, emits a commit and manifest hash, and must be independently read back. These functions were exercised only against deterministic fixtures in this preparation task. No real campaign evidence was published.

After a genuine complete A capacity pass, use one bounded command:

```bash
PYTHONDONTWRITEBYTECODE=1 python diagnostics/stage-e-native-v3-bc-final-prep/handoff.py after-a --plan /path/to/actual-plan.json --output /path/to/fresh-after-a
```

It reads back A and completed A-preflight bytes, verifies raw A and preservation, recomputes shared receipt/storage bindings, fills all ten B prerequisite slots from verified A, constructs `B_PREVIEW.json`, re-verifies its A prerequisite, seals the handoff inventory and stops with `STOP FOR OWNER B AUTHORIZATION`. It creates no owner permit. If A is absent, partial, failed, invalid, incorrectly bound or unpreserved, no B preview is finalized.

After a genuine B pass, add its actual publication fields and use:

```bash
PYTHONDONTWRITEBYTECODE=1 python diagnostics/stage-e-native-v3-bc-final-prep/handoff.py after-b --plan /path/to/actual-plan.json --output /path/to/fresh-after-b
```

It independently reads back and re-verifies A/B/shared inputs, checks all six ordered trials, three complete pairs, workload/resource/executor equality and strict summed integer observer arithmetic, regenerates the qualification review, finalizes `C_PREVIEW.json`, seals the handoff inventory and stops with `STOP FOR OWNER C AUTHORIZATION`. The C preview has no capacity/observer credit or execution authority.

After C, add its genuine publication fields and the preserved supplemental raw bundle described by `RETAINED_INPUT_SCHEMA.json`, then use:

```bash
PYTHONDONTWRITEBYTECODE=1 python diagnostics/stage-e-native-v3-bc-final-prep/handoff.py after-c --plan /path/to/actual-plan.json --output /path/to/fresh-after-c
```

It reads back every actual package, re-verifies A/B/C and required C native safety, ingests preserved primary proof, recomputes all 47 approved gates and concrete inventory path/hash bindings, writes `QUALIFICATION_REVIEW.json`, `HANDOFF_RESULT.json` and `HANDOFF_INVENTORY.json`, and stops with `STOP FOR ASTRA/OWNER FINAL DISPOSITION`. A safe C overload remains separate from its failed/incomplete performance diagnostics. Missing retained primary evidence keeps corresponding gates unsatisfied; no summary is promoted to PASS.

Each output destination is exclusive. A failed operation leaves its partial output available for review; a subsequent verification uses a new destination. This is a parser/readback operation and never retries or replaces a material trial. Original retained and redundant locations required by the unchanged approved verifier must remain readable; signed origins and paths are not rewritten. No production-volume access is part of the current preparation.

The final report can contain only `STAGE_E_NATIVE_V3_QUALIFIED` or `STAGE_E_NATIVE_V3_QUALIFICATION_BLOCKED`. Until genuine validated A+B+C, complete preservation and all 47 gates exist, it stays Stage E RED, Stage F NOT STARTED. Stop for the named owner at every phase.
