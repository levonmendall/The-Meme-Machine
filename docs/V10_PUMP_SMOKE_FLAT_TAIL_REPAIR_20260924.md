# V10 Pump Smoke Flat-Tail Repair — 2026-09-24

Incident: market run `36070948268` completed the required 600-second smoke observation window, but GitHub sent SIGTERM at approximately 1,178 seconds while Pump remained alive in its configured follow-up window. No repository-controlled cancellation, competing market run, or configured timeout caused the termination.

Final live evidence showed Pump healthy and flat: zero open positions, zero pending/reserved/basis, recent progress, covered public stream, zero stream gaps/capacity losses, and no HTTP/RPC provider errors. The extended runtime was therefore not a lifecycle hang.

Root cause of avoidable runner exposure: Pump's smoke execution reused the normal campaign follow-up allowance. V10 already prevented new post-graduation admission after the discovery boundary, but the process still waited through the remaining follow-up interval even when no pending entry or open paper position required it.

Repair `smoke-flat-tail-v1`:
- in smoke only, after the 600-second discovery boundary, Pump exits immediately when both pending entries and open positions are empty;
- an already-reserved entry still retains its original fill-delay/fill-timeout behavior;
- an already-open position still retains its exact frozen lifecycle and can use the existing follow-up window;
- hourly/campaign runtime behavior is unchanged;
- strategy economics, thresholds, target scope, provider ceilings, evidence requirements, position sizing, finality/freshness, and paper-only authority are unchanged.

Focused deterministic proof covers immediate flat exit and preservation of the existing final-second 900-second position-lifecycle regression.

The Pump exact source-diff identity after repair is:
`c2e446c9a4f18869831b20471c8f48d86195a678f0de07fb751e0e2c19663e42`.

The prior failed smoke is not reused as an economic block. A fresh prospective cohort identity is used because integration/certification code changed.
