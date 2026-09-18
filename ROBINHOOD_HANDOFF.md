# Robinhood handoff — latency-repaired continuation-v1 sample

## Evidence acquisition latency: REPAIRED

Frozen policy hash:
`f363c234daa549365ca00ee5b33247deb1c591a1084b991263233ba9f3870e36`.

No strategy threshold, translation value, selection rule, or five-second freshness
boundary changed.

The repair:
- prewarms the global Pons event tape for >60 seconds;
- removes per-candidate serial historical log rescans;
- uses bounded JSON-RPC batching for candidate/header/receipt evidence;
- batches exact holder verification;
- runs holder concentration and prior-window authentication concurrently;
- keeps exact point-in-time evidence and logical provider budgets unchanged.

Optimized unbiased rerun:
[35392529357](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35392529357)

Artifact `10565519564`, SHA256
`cfc713ab5907a4fa745f4ae9ba57bfa513d2ecfe3fd73b9171935179fc49ee15`.

Results:
- 19 natural enrollments;
- 11 fully evaluated;
- 10 complete frozen-policy vectors;
- **10/10 complete vectors decision-eligible inside the unchanged 5-second gate**;
- complete-vector ages: 2–5 seconds;
- median evaluation latency: 1.59 seconds;
- max evaluation latency: 4.00 seconds;
- median candidate-auth latency: ~0.59 seconds;
- median transport requests/evaluated row: 8, versus 121 for complete rows in the
  original latency-blocked run;
- 1 genuine natural frozen-policy qualifier.

Qualified natural candidate:
- token `0x5b5f72fd56ea273f603f4c68ca6ac89842692aaa`;
- curve `0x740e1ade8c93bf79dc8b367252d36d5b48c63624`;
- source tx `0x53d7a040252028896281de65eb19745f4919b78694fd0cb6c0607e58c8741e2a`;
- complete evidence age: 5s;
- concentration: 12.41%;
- real quote liquidity: 0.839048410250868462 ETH;
- evidence events: 95;
- independent buyer groups: 5;
- independent net buy: 0.102585276480156894 ETH;
- price extension: 105.06%;
- modeled round-trip loss: 2.99%;
- no frozen-policy rejection.

The qualifier's exact +60-second executable mark was -16.53% gross and -16.66% net
after modeled gas. That is one observation only and does not establish expected value.

The optimized runner produced 9 exact +60-second marks total. Rows that failed the
strategy remain in the sample; no outcome-based replacement occurred.

Eight enrollments were acquisition-incomplete:
- six invalid current-snipe states;
- two non-native quote assets outside the frozen ETH translation scope.

The live sample trigger is restored to its explicit push-marker guard.

Exact details:
`CONTINUATION_V1_ROBINHOOD_SAMPLE_STATUS.md`.

### Next causal boundary

The evidence-latency blocker is closed. Continue the **same frozen sample** until the
qualified cohort is large enough for meaningful forward-outcome analysis. Do not
change any threshold based on the current single qualifier.

---

# Robinhood handoff — continuation-v1-robinhood natural sample

## Unbiased natural sample executed

Frozen policy hash:
`f363c234daa549365ca00ee5b33247deb1c591a1084b991263233ba9f3870e36`.

Run:
[35385242146](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35385242146)

Artifact `10563828142`, SHA256
`4432632068013420dd55187bd828496fe88332eb321240a2a3e1a01388ff7540`.

The run enrolled the first previously unseen authentic Pons V2 buy after each prior
enrollment attempt completed. There was no economic ranking, future-outcome selection,
replacement, or threshold modification.

Results:
- 21 natural enrollments;
- 15 fully evaluated;
- 6 acquisition-incomplete;
- 13 complete frozen-policy vectors;
- 0 decision-eligible complete vectors under the existing 5-second Robinhood current-state gate;
- 0 live-qualified rows;
- 5/13 complete vectors met every frozen strategy threshold if the separate
  `stale_state_after_evidence` operational rejection is inspected descriptively.

Complete-vector evidence age was 19–33 seconds (median 22 seconds). Therefore the
current causal blocker is evidence-acquisition latency, not a reason to weaken
continuation-v1.

Among the 13 complete vectors, after excluding only the independent freshness
rejection for descriptive analysis:
- independent-demand rejection: 6;
- round-trip-cost rejection: 6;
- translated real-liquidity rejection: 2;
- concentration rejection: 0;
- price-extension rejection: 0.

Five acquisition-incomplete rows used non-native Pons quote tokens outside the frozen
ETH translation scope; one failed the current-snipe evidence boundary. They remain
in the sample and were not replaced.

The run also produced 10 executable forward marks, but they were observed 67–350
seconds after enrollment because the initial runner processed marks sequentially.
They are **not exact +60s outcomes** and must not be used for +60s expected-return
inference. The runner has been relabelled to `forward_after_60s` so future artifacts
retain the actual delay semantics.

No profitability conclusion and no threshold change is authorized from this sample.

Exact details are in `CONTINUATION_V1_ROBINHOOD_SAMPLE_STATUS.md`.

Next: reduce evidence acquisition latency while preserving the exact frozen policy,
point-in-time evidence, 5-second state gate, and Pons/V4 adapter separation; then rerun
the identical sample. Do not lower thresholds to create qualifiers.

---

# Robinhood handoff — genuine natural Pons paper lifecycle

## Current milestone — 2026-09-18

Current implementation head before this handoff update:
`f8f2c32154d6603881444f7448addb5781761f8f`.

Branch remains `feat/robinhood-research-foundation`; PR #15 remains open/draft.
No merge, deployment, signing, transaction submission, live money, shared allocator,
or Solana strategy change occurred.

### Genuine natural Pons paper lifecycle: COMPLETE

Bounded mainnet run
[35382359016](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35382359016)
completed the connected paper lifecycle:

natural current Pons event
→ authenticated V2 curve/factory state
→ outcome-blind proof-only reservation
→ 2-second delayed current entry quote
→ natural paper fill
→ Store close/reopen + reconciliation
→ executable full-position monitoring
→ risk exit intent
→ 2-second delayed current exit quote
→ settlement
→ second restart reconciliation
→ zero residual exposure.

Artifact: `10562377925`.
Artifact SHA256:
`1e2f2da1d446baa033afce6801fe71f24599ddc3bf66df17469764946cd86df8`.

Natural candidate:

- token: `0x3808b3ce12d40938366dbbc698ce0ba50fa37c8e`;
- curve: `0x856f6971fe68300dfd182725bfae433a86bb5b7b`;
- source transaction:
  `0x62b3bf4c2db53fc4009c0ae8a9049e08d93d2c0485bc687b0be3483492b86bdb`;
- source block: `66452382`;
- decision freshness: **4 seconds** under the unchanged five-second gate;
- selection rule:
  `first_current_authenticated_pons_v2_curve_after_start`;
- selection authority:
  `bounded_lifecycle_proof_only`;
- Robinhood-native strategy policy remains **not established**.

Paper entry:

- reserved input: `0.01` native quote (`10^16` wei);
- delayed entry block: `66452458`;
- paper tokens:
  `1764611531808122961342365`;
- entry gas proxy: `12034254400000` wei;
- paper cost: `10012034254400000` wei;
- position successfully survived Store close/reopen with identical reconciliation.

Monitor and exit:

- first executable monitor block: `66452604`;
- full-position marked return after modeled gas: **-6671 bps**;
- fixed proof-only risk boundary: **-1000 bps**;
- exit reason: `risk`;
- delayed exit block: `66452638`;
- gross curve proceeds: `3520345598746922` wei;
- exit gas proxy: `12228861120000` wei;
- net proceeds: `3508116737626922` wei;
- realized paper P&L:
  `-6503917516773078` wei, approximately **-64.96%** of paper cost.

Final reconciliation:

- status: `settled`;
- token exposure: `0`;
- committed/reserved capital: `0`;
- open exposure: `0`;
- isolated paper genesis: `1 ETH`;
- final available paper capital:
  `993496082483226922` wei.

Provider for the successful lifecycle:

- 63 requests;
- 0 failures;
- 0 retries.

The result is deliberately **not profitability evidence**. This candidate was selected
to prove a natural lifecycle, not by an empirically established Robinhood alpha
policy. Its large loss is retained as real paper evidence and is not filtered out.

### Natural graduation carry: NOT OBSERVED IN THIS RUN

The held token did not graduate before the proof-only risk exit. Therefore this run
does **not** claim a natural Pons V2 → V4 held-position lifecycle.

The carry machinery is present and fail-closed:

- graduation must be authenticated by the already-proven factory
  `PoolGraduated` + hook `PoolRegistered` + V4 `Initialize` lineage;
- the paper position can transition only after that proof is stored;
- a V4 full-position exit path uses the official Robinhood V4Quoter deployment
  and validates its PoolManager wiring;
- unrelated V4 pools cannot route the position.

Historical/captured authentic V2→V4 lineage remains proven separately, but a **natural
held position crossing that boundary** remains an outstanding market-supplied proof.

### Natural-paper safety boundary

The default `Paper` API still rejects natural allocation. Natural positions can be
opened only when the experiment is explicitly constructed with
`natural_proof=True` and the immutable decision evidence says:

- `authority=bounded_lifecycle_proof_only`;
- `qualification=policy_not_established`.

Confirmed quote stamps still require the existing Finality ledger. The five-second
freshness gate is unchanged. Delayed entry and exit both require post-delay current
quotes. Impossible exits remain unresolved rather than fabricated.

### Durable captured regression

Committed evidence:

- `robinhood_tests/fixtures/pons_paper_lifecycle_35382359016.json`;
- `robinhood_tests/test_captured_natural_paper.py`.

The regression checks zero residual exposure, settlement accounting, exact
entry/exit/P&L arithmetic, the triggered risk condition, clean provider telemetry,
and the absence of a profitability claim.

### Verification

Exact-head deterministic CI before this handoff update:
[35382745215](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35382745215)
passed **88 tests**.

The live paper workflow is restored to its explicit
`[robinhood-pons-paper]` push-marker guard; ordinary commits cannot open another
proof position.

### Next causal boundary

The Pons directional mechanics now have a genuine natural paper
entry→monitor→exit→settlement proof.

Two distinct research boundaries remain:

1. obtain a **natural held Pons V2 position that the market itself graduates**, then
   carry it through authenticated V4 quoting and settlement if such a candidate is
   naturally supplied; do not force or retrospectively choose the event;
2. establish a Robinhood-native directional qualification policy from a meaningful
   natural sample before granting ordinary paper allocation authority.

The independent Ramses DLMM lane remains separate.

---

# Robinhood handoff — Pons protocol-native milestone

## Current milestone — 2026-09-18

Starting continuation head for this slice:
`9e557245963f64aaff7412cca72f9c2915a2a8ff`.

Branch remains `feat/robinhood-research-foundation`; PR #15 remains open/draft.
No Solana source, threshold, workflow, provider, paper authority, merge state or
deployment was changed.

### Authentic Pons V2 graduation -> Uniswap V4 lineage: PROVEN

Bounded mainnet lineage run
[35378762520](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35378762520)
completed with zero provider failures/retries. Artifact `10561890805`, SHA256
`97582b1ce347cd3e13650cc8c4c74571ad4d6406bdbc5cf9acb2ecbc41041353`.

The authenticated same-transaction proof binds:

- Pons V2 token: `0xf25cbd487fe0294dd0a39ba2955982bcff28fd72`;
- source-verified curve: `0xea069fb8e88e3e08b427f8a4d496f7b94a8215b2`;
- Pons factory `PoolGraduated`;
- Pons hook `PoolRegistered`;
- Uniswap V4 PoolManager `Initialize`;
- exact PoolKey-derived pool ID:
  `0x2075abed94de15d218a27b4da93541a974e23e131f1d2da32177b33634ac8da7`;
- position ID `2103714`;
- transaction
  `0x1d49a28a0e27ecdd952094c4aaa9de2105253a2d62924ec36e761c13e43493c9`.

Token appearance on V4 alone is not accepted. Pool ID, currencies, fee, tick
spacing, hook, factory state and all three protocol-native events must agree.

### Authentic Pons V1 -> Uniswap V3 provenance: PROVEN

The same bounded proof independently authenticated:

- Pons V1 token: `0xc4cb8a0167c77e36194f6affb6b71d931fab62c0`;
- pair token: `0x0bd7d308f8e1639fab988df18a8011f41eacad73`;
- exact V3 pool: `0x1e1779d5cf272a54ce27df5c9eb718ed5649d125`;
- fee: `10000`;
- position ID: `350747`;
- factory-record DEX ID: `0`;
- transaction:
  `0xb4731f87f0ed4f30e804d3aad492e2410ff6efffd953150ee833fd04584a68cc`.

The token creation height (`17661055`) was found with bounded historical-code
binary search. The proof then requires Pons V1 `TokenLaunched` and Uniswap V3
`PoolCreated` in the same receipt plus full agreement with the pinned Pons factory
record. An unrelated or substituted V3 pool fails closed.

### Captured-mainnet regressions

Committed fixture:
`robinhood_tests/fixtures/pons_lineage_35378762520.json`.

Committed regression:
`robinhood_tests/test_captured_pons_lineage.py`.

It replays both authentic lineage proofs and contains negative controls for an
unrelated V4 initialization and a substituted V3 pool. The compact fixture is tied
to the full Actions artifact/run/digest above rather than presented as synthetic
evidence.

### Five-second / finality boundary: UNCHANGED

The confirmed-evidence ledger from the prior protocol-verification work was not
weakened. Confirmed evidence still requires the ledger; the quote state must remain
within the existing five-second gate; displaced blocks invalidate dependent
evidence; later finalization preserves the original observation time; restart
recovery and canonical-hash disagreement remain tested.

### Bounded natural Pons observation: COMPLETED

The first live attempt exposed a real acquisition bug rather than producing a false
candidate: a state-changing `buy` eth_call from an unfunded research address
returned RPC -32000 and repeated events from the same curve wasted the bounded
budget. The repair did **not** widen freshness or provider limits: the observer now
uses the already source-verified buy arithmetic with the deployed curve's on-chain
`currentSnipeTaxBps` and evaluates each curve only once.

Repaired bounded run
[35379763812](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35379763812)
completed successfully. Artifact `10561613083`, SHA256
`08fd897af26c301d028a7789eabb91834e868de51d4da46089db911c400a3a04`.

Prospectively selected first authenticated current curve:

- token: `0x27fbf4f24a502b90eb40037c814099e3255f4134`;
- curve: `0xb844ddc0c0e4311a0890d075d2e3c6680ebc525e`;
- candidate block: `66436054`;
- state freshness at frozen quote: **2 seconds**;
- dependency status at quote: `confirmed`;
- frozen research input: `0.01` native quote units (`10^16` wei);
- source-verified quote tokens:
  `2691280098289079811502556`;
- current snipe rate: `0` bps;
- no paper order/reservation/allocation authority.

Fixed 60-second follow-up:

- 17 authenticated subsequent curve trade events;
- no graduation during the follow-up;
- full-position curve mark remained executable;
- gross marked return: **+1227 bps (+12.27%)**;
- gas was intentionally not modeled, therefore
  `after_cost_return=null` and profitability is **not established**;
- dependency remained `confirmed` rather than being backdated as finalized;
- provider: 119 transport requests, zero failures, zero retries.

This is a natural protocol/economic observation, not evidence that a Robinhood
trading policy is profitable and not authorization to trade.

### Verification

Exact-head deterministic CI before this handoff update:
[35379783167](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35379783167)
passed **81 tests**. The live natural job is restored to its explicit push-marker
guard; ordinary commits do not repeat it.

### Next causal boundary

Pons protocol identity, V2->V4 lineage, V1->V3 provenance, current confirmed
freshness handling, exact curve quoting and one natural 60-second observation are
now proven.

The next Robinhood work should return to the independent Ramses lane: complete the
range-specific pre-entry economic case against the already authenticated replay,
then obtain one valid approximately 60-second current Ramses observation without
weakening the 35-bps research hurdle. Separately, directional profitability still
requires a natural sample and a justified Robinhood-native qualification policy
before any paper allocation authority is enabled.

---

# Robinhood handoff — protocol verification continuation

Continuation starting SHA (fetched and verified before edits):
`7b1307c264d16c063ed1f19c13ecee02199bcef2`.
Starting branch: `feat/robinhood-research-foundation`; PR #15 open/draft; clean tree.
The original foundation handoff below remains as historical evidence.


Starting branch: `main`.
Starting SHA: `54712c4c6470cc4dc267888f934bd693aac030d0` (README only).
Dedicated branch: `feat/robinhood-research-foundation`.
The final published SHA, draft PR and exact-head CI are recorded in the PR handoff.
No Solana branch was merged into this branch. There is no Render service.

## Result

Delivered executable offline research/accounting primitives, deterministic and
captured-provider regressions, and a successful GitHub-secret mainnet read proof.
**The full requested natural-market milestone is not complete.** Pons current ABI
and graduation semantics remain unverified; Ramses has no verified deployment or
accounting here. Real protocol adapters fail closed. No profitability is claimed.

Solana strategy code, thresholds, tests, branches, shared capital authority and
experiments remain unchanged. Added code is under `robinhood_research` and
`robinhood_tests`; CI is a separately named workflow. Existing README is untouched.

Files added: `.github/workflows/robinhood-research.yml`, `.gitignore`, `AGENTS.md`,
this handoff; `robinhood_research/{__init__,provider,probe,evidence,protocols,keccak,
directional,outcomes,paper,liquidity}.py`, `robinhood_research/registry.json`,
`robinhood_research/README.md`; `robinhood_tests/{test_provider,test_foundation,
test_captured}.py` and `robinhood_tests/fixtures/mainnet_read_summary.json`.

## Starting repository and CI

Inspected directional tip: `4cef2aed3a9ebfce1a946bbbed007bf0fa74a507` (draft PR #14,
based on PR #12). Inspected DLMM tip: `6d9161b3e06fb2829f6d2766cf3ec353b012e336`
(draft PR #13, based on `research/dlmm-profitability-density-preflight-v2`).
Open stack: #1 Pump foundation -> #2 post-graduation; #3 natural proof and #4
Meteora foundation branch from #2; #5 market-native shadow -> #7 prioritizer ->
#8 active discovery -> #11 active paper -> #12 outcomes -> #14 economics.
#6 Fomo scaffold -> #10 Fomo offline; #9 natural sample branches from #8.
PRs #2–#14 were drafts; #1 was open, non-draft. All were left unchanged.
No Robinhood files were found in the inspected Solana tips, and no Robinhood
commit-message match was found in fetched history.

Solana `paper-milestone` CI runs tests and gated live experiments, with shared
Solana concurrency. It was not copied or altered. New `robinhood-research` CI runs
only this foundation's tests; its optional read proof uses independent concurrency.
Python is 3.12.14; no external Python dependencies were added.

## Provider and actual live evidence

Secret: **`MM_ROBINHOOD_READ_RPC_URL`**, the full HTTPS RPC URL added by the user.
The selected Alchemy connector separately returned quota errors; that finding does
not apply to the working GitHub-secret endpoint. There is no missing credential.

[First proof run 35364826427](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35364826427)
at `f17b7567f1c4779f3afa47c842f6fe1eab261655`: chain 4663; 15 RPC requests; no
failures; finalized blocks 66333840–66333849; 265 logs; three matching receipts;
historical code and eth_call succeeded.

[Second proof run 35365593031](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35365593031)
at `80d1c00e9dbd34c9b159fd0e72b90f90de40ef8f`: chain 4663; 15 RPC requests; no
failures; finalized blocks 66341500–66341509; 39 logs; three matching receipts;
historical code and eth_call succeeded. Both Pons factory/hook explorer ABI requests
returned unavailable. Provider-job success does not mean protocol verification.

[Raw second report artifact](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35365593031/artifacts/10556455600).
Its job-log summary is committed in `robinhood_tests/fixtures/mainnet_read_summary.json`.
Artifact download from this workspace returned HTTP 403. The committed capture is
a provider-summary fixture, not a raw contract-event replay fixture.

## Contract evidence actually obtained

All six candidate addresses had nonempty bytecode at both sampled finalized blocks.
Bytecode SHA256s are in the captured summary. **Names remain predecessor-code role
labels; code presence is not independently verified protocol semantics.**

| Candidate role | Address |
| --- | --- |
| Pons V1 active factory | `0xa5aab3f0c6eeadf30ef1d3eb997108e976351feb` |
| Pons V1 legacy factory | `0x0c37a24f5d23a486fa692d1500881d698b1f77a4` |
| Pons V2 factory | `0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e` |
| Pons V2 hook | `0xe5e702641ea86f4ae6cc3cdaed2b886f976be044` |
| Uniswap V3 factory | `0x1f7d7550b1b028f7571e69a784071f0205fd2efa` |
| Uniswap V4 manager | `0x8366a39cc670b4001a1121b8f6a443a643e40951` |
| Ramses DLMM | Unverified; no address configured |

Official [network](https://docs.robinhood.com/chain/connecting/) and
[finality](https://docs.robinhood.com/chain/transaction-finality/) references were
read. Pons documentation and Ramses DLMM documentation retrieval were unavailable
through the paths used. No remembered fee split became a Ramses accounting default.

## Supported and blocked surfaces

| Surface | Implemented | Unresolved |
| --- | --- | --- |
| Pons V2 curve | Synthetic candidate-layout decoder, identity guards, point-in-time features | Verified current ABI, raw captured replay, exact reserves/tax quotes |
| Pons V2 to V4 | Synthetic three-proof lineage, exact PoolKey hash, paper transition/restart | Authentic raw factory/hook/initialization decoders and natural graduation |
| Pons V1/V3 | Separate origin classification and discovery/quote interfaces | Verified launch/pool provenance and live venue adapter |
| Non-Pons V3/V4 | Speculative origin and asset-class exclusions, discovery interface | Verified launch mechanism and executable liquidity; Pools.trade unverified |
| Ramses DLMM | Gated structural adapter, synthetic bin/range/share/fee 60s harness | Mainnet identity, ABI/source, exact bin/dynamic-fee/share/claim accounting |
| Uniswap LP | Future interface | No LP economics or allocation |

Directional features include 5/10/30/60s flow, participant breadth and accelerations;
missing creator/concentration/LP fields are explicit. Outcomes freeze enrollment and
separate natural/prioritized/synthetic and V1/V2 statistics. The paper state machine
preserves unresolved exposure, validates delays, and recovers across restarts.
Natural paper policy is not established and cannot reserve capital.

## Tests and outcomes

Local command: `TMPDIR=/dev/shm python -m unittest discover -s robinhood_tests -v`.
**38 tests passed** before publication. The initial two commits also passed their
then-current five-test CI and bounded-read jobs. Exact final-head CI belongs in the
PR handoff; earlier green checks do not validate later files.

Coverage includes wrong chain, future/stale evidence, missing/duplicate/conflicting
logs, receipt gaps, removed logs, finality/reorg guards, atomic cursor rollback,
graduation identity, unrelated V4 rejection, impossible exits, restart/settlement,
provider/budget failures, storage caps, forward timestamps, range liquidity, bin
identity, share/add/remove behavior, variable-fee accounting, untouched/partly/
fully touched ranges, residual liquidation and unsupported mutations.

| Outcome | Evidence |
| --- | --- |
| Natural raw activity | Yes: bounded mainnet logs and receipts |
| Decoded/admitted natural candidate | No |
| Natural paper lifecycle completed | No |
| Synthetic paper lifecycle | Completed through graduation, restart, unavailable exit and settlement |
| Mainnet Ramses 60-second observation | No |
| Synthetic 60-second accounting | Completed; not Ramses mechanics or profitability |
| Profitability established | No |

## Resource limits and next causal boundary

Per-dataset retention is documented in `robinhood_research/README.md`. Default
10,000 immutable records; SQLite 64MiB page cap; 2MiB page cache; bounded provider,
discovery and replay batches; repeated failed exits coalesce. Existing evidence is
never deleted. Raw Actions artifacts expire after 30 days.

Next: current Pons verified ABI/source tied to deployed implementations/proxies,
followed by captured raw launch/graduation reconstruction and exact curve quotes.
No extra credential is requested: the repository RPC already works.

Captured finalized state lags latest, so it cannot pass the current 5s freshness
gate for prospective trading. Real-time research needs explicit sequencer-confirmed
acquisition, reorg invalidation and later finalization; never backdate finalized
history or weaken freshness just to generate observations.

Ramses needs verified Robinhood mainnet factory/pool identity, ABI/source and
captured swap/add/remove/claim accounting. Its adapter must remain disabled until
then. Keep the 35bps research hurdle and freeze range proposals before outcomes.
