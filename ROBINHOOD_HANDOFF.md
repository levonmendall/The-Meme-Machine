# Robinhood handoff — partial foundation; protocol gates remain

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
