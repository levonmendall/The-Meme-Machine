# Ramses DLMM Research Status

## Scope and release boundary

- Repository: `levonmendall/The-Meme-Machine`
- Draft PR: #15 (`feat/robinhood-research-foundation`)
- Starting continuation SHA: `5664863e1e3222edb015910754b059648687e705`
- Final Ramses implementation/evidence SHA: `832ecccbf4ace323799f8d123e12c2d921b91b9d`
- Temporary proof-trigger file was removed after the evidence run; documentation-only commits may follow the implementation SHA.
- Research only. Ramses allocation authority remains disabled. No transaction signing/submission, merge, or deployment was performed.
- Pons / `continuation-v1-robinhood` and Solana strategy/DLMM code were not modified.

## Verified deployed identity

The implementation continues to use the pinned exact Ramses deployment evidence already present on the branch:

- Verified source repository: `RamsesExchange/ramses-v3-contracts`
- Verified source revision: `c97cde6b6b782b617f77a1d12f30f066189166cd`
- Pool implementation: `0x4e857A78bcE4FcF41677f21Bfaf3e77890d5042b`
- Factory: `0xdcD5F77697914E27f56FD263EF82923C8524AbAc`
- Router: `0xd0019e86edB35E1fedaaB03aED5c3c60f115d28b`
- Quoter: `0xb722efaAbe807FAeA16068f595EaA9aa1a62CECD`

Pool admission requires factory membership plus exact authenticated CWIA clone runtime, token ordering and bin step. Nonzero hooks fail closed.

## Implemented mutation reconstruction

`robinhood_research/ramses.py` now reconstructs the Ramses state relevant to the range experiment from authenticated pool events and exact verified-source arithmetic:

- swaps, including exact per-bin traversal, LP/protocol fee split, active-bin movement and volatility updates;
- liquidity additions / share minting via `TransferBatch` + `DepositedToBins`;
- active-bin composition fees, including protocol exclusion and auto-compounded LP fees;
- liquidity removals / share burning via `TransferBatch` + `WithdrawnFromBins`;
- nonzero-to-nonzero share transfers without changing total supply;
- flash-loan protocol-fee effects;
- protocol-fee collection with source-native leave-one accounting;
- static fee parameter changes;
- forced volatility decay;
- zero hook-parameter events;
- oracle-length and approval events as non-economic mutations.

Every observed pool log must be receipt/header authenticated, unique/idempotent and represented in replay. Unknown events, nonzero hook changes, removed/reorg events, unpaired mint/burn event sequences, arithmetic disagreement, missing prestates, or terminal disagreement fail closed.

Modeled terminal components include bin reserves, bin total supply, pool reserves, protocol fees, active id, static fee parameters, variable fee parameters, bin prices, token ordering, implementation/factory identity and no-hooks state. Oracle ring contents and external LP owner balances are not needed for the hypothetical range economics and are not used to authorize or fabricate a result.

## Prospective range preparation

`robinhood_research/ramses_capture.py` is now prospective rather than retrospective:

1. authenticate chain, factory, implementation and router;
2. discover recent Ramses activity with bounded/batched RPC;
3. admit only an exact factory-authenticated Ramses pool containing the router's native asset;
4. capture a finalized point-in-time pre-entry state;
5. construct deterministic narrow / medium / wide ranges from the same prestate;
6. freeze the entire proposal set and SHA-256 proposal hash before observing the forward outcome;
7. only then observe an approximately 60-second finalized forward window;
8. replay every authenticated pool mutation and require exact terminal equality;
9. calculate hypothetical paper share ownership, event-time LP fee attribution, removal inventory and executable same-pool unwind evidence;
10. leave after-cost return unresolved if executable unwind or exact cost evidence is unavailable.

The paper overlay is explicitly non-impact/exogenous and has no allocation authority. A frozen proposal hash fails verification if range definitions are changed after the outcome.

The 35-bps research hurdle is unchanged. Comparison is exact: below / equal / above / unresolved.

## Tests and CI

The complete `robinhood_tests` suite passes with 121 tests, including the authentic captured 60-second Ramses replay and new regressions for:

- exact add-liquidity / share-mint event replay;
- exact remove-liquidity / share-burn event replay;
- active-bin composition fee and LP/protocol conservation;
- dynamic Ramses array events;
- variable-fee/forced-decay behavior;
- duplicate idempotence and removed/reorg rejection;
- unsupported mutation fail-closed;
- frozen range immutability;
- identical-prestate range alternatives;
- exact paper share ownership;
- untouched, partially touched and fully traversed ranges;
- executable and unavailable unwind paths;
- event-time paper LP fee attribution;
- exact 35-bps hurdle comparison;
- Ramses allocation authority disabled;
- preserved Pons / continuation test coverage.

Final evidence workflow: `35401048880` on implementation SHA `832ecccbf4ace323799f8d123e12c2d921b91b9d`.

## Mainnet proof result

Final bounded proof used `MM_ROBINHOOD_READ_RPC_URL` on exact implementation SHA `832ecccbf4ace323799f8d123e12c2d921b91b9d`.

Result:

- boundary: `no_factory_validated_native_pool_in_600_block_window`
- selected pool: none
- discovery window: 600 finalized blocks, same Ramses factory only
- proposal hash: none, because no eligible pool existed before the freeze point
- observation start/end blocks and times: not applicable
- forward event/transaction count: not applicable
- terminal equality: not applicable to a new prospective observation
- capital employed: not applicable
- fee capture: not applicable
- inventory outcome: not applicable
- unwind evidence: not applicable
- gas/cost accounting: not applicable
- after-cost P&L: null / unavailable
- after-cost return bps: null / unavailable
- 35-bps hurdle result: unresolved
- RPC logical requests: 72
- RPC transport requests: 12
- retries: 0
- failures: 0

Artifact:

- workflow run: `35401048880`
- artifact ID: `10570575863`
- artifact name: `robinhood-ramses-832ecccbf4ace323799f8d123e12c2d921b91b9d-35401048880`
- artifact SHA-256: `692b5168379677e7009ff488bcf7af320aabe93b0dbe74569c330d40e6ea3ad4`

An earlier prospective attempt correctly rejected factory-authenticated pool `0x64d852011abd1be6636b04983b472439a4380b79` because it did not contain the native quote asset. Candidate selection was then repaired to enforce the native-pair requirement before range freezing, without selecting on the future outcome.

## Remaining causal boundary

The requested fully valid natural observation cannot currently be manufactured honestly: within the final bounded 600-block Ramses discovery window there was no recent factory-authenticated Ramses pool containing the native quote asset.

This is the external/market boundary reached after completing the internally available mutation reconstruction, prospective range freeze, paper-share accounting, forward replay and unwind framework. No strategy threshold, source/identity check, finality rule, terminal-equality requirement or 35-bps hurdle was weakened to produce an observation.

If a qualifying native Ramses pool becomes naturally active in a later bounded run, the next proof should proceed from frozen prestate through the approximately 60-second replay. Exact hypothetical cost evidence must still be present before any after-cost return or 35-bps qualification is asserted.

## Net changed files for this continuation

- `robinhood_research/ramses.py`
- `robinhood_research/ramses_capture.py`
- `robinhood_tests/test_native_ramses.py`
- `RAMSES_DLMM_STATUS.md`
- `ROBINHOOD_HANDOFF.md` (handoff update only)
