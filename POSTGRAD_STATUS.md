# Post-graduation milestone status

Base branch: `feat/pump-directional-paper` at `a65e2e6d3f827cd748b748b68058529579cdbeb8`.
Stacked branch: `feat/post-graduation-pumpswap-raydium`.

Scope remains read-only/paper-only: Pump.fun completed-curve handoff -> canonical PumpSwap or legacy Raydium-v4 identity -> exact-size quotes -> disabled prospective allocation -> synthetic/captured paper lifecycle using the shared Store/Allocator. `continuation-v1` is unchanged. No signing, submission, deployment, paid provider, live money, DLMM allocation, FOMO, or Robinhood work is authorized here.

The first live probe reached the completed Pump account but failed before pool resolution because the active bonding-curve decoder correctly rejects zero reserve state. That decoder remains unchanged for active strategy authority. The post-graduation handoff now has a separate immutable completed-curve decoder that accepts retired zero quote state and legacy pre-Mayhem 81-byte accounts while still requiring `complete=true`, zero real-token inventory, fixed mint authority/freeze semantics, valid supply bounds, SOL quote scope, and no cashback.

Deterministic regression coverage now includes retired and legacy completed-curve handoff. Prospective allocation remains hard-disabled until live/captured PumpSwap and legacy Raydium evidence both pass.
