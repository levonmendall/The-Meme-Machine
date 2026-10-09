# Pons event-driven long-hold PAPER trial runbook

Status: **IMPLEMENTED_SHADOW_ONLY / PROVIDER_SHADOW_NOT_RUN / QUOTE_SUPPRESSION_NOT_ENABLED**.

Branch: `engineering/pons-event-driven-paper-20261009`, based on
`engineering/pons-held-efficiency-20261009`.
The original Current/Survivor entry, quote, partial/full exit, trailing,
position-only recovery, max-hold and exceptional-winner rules are unchanged.
There is no real-money authority and no new service, subscription, history
backfill, Alchemy account, Droplet or resource entitlement.

## What exists in code

- `NativeHeldCoverage`: bounded receipt-independent, canonical numeric
  boundary checks surrounding two complete, provider-filtered log acquisitions:
  indexed Pons V4 PoolManager/hook pool events and the corresponding global
  manager/hook controls. Exact RPC endpoint fingerprint and chain authority
  must match the existing owner. Failed/partial intervals cannot become quiet.
- `PaperHeldShadow`: a capped, ephemeral, PAPER-only observation inside the
  existing native position controller. It is invoked **after** the normal
  protective decision, sale/partial settlement and optional scale work.
  Positions with pending actions, stale quotes or near protective thresholds
  incur no optional observation work.
- Current postgraduation and Survivor controllers record native price/gas-
  adjusted proceeds on **every ordinary protective evaluation**, then use a
  small sample of separately authenticated logs to compare consecutive
  quote outputs under event-quiet intervals. A silent quote delta suspends
  further sampling. Missing evidence remains INCONCLUSIVE.
- The existing `held_quote_wakeup` candidate can identify hypothetical
  quiet intervals when *separate* fee/token/hook proof is assumed. No runtime
  caller grants that certification, publishes fake fresh marks, or acts on
  hypothetical omissions. A hypothetical count is **not verified savings**.
- No cross-process probe-sharing assumption is credited. Same market observed
  by multiple regimes may lead to duplicated optional probes; compare fully
  metered aggregate work.

## Activation for a separately authorized bounded PAPER run ONLY

Do not set these flags on the deployed system until the regular PAPER
bootstrap/continuation authority and original resource envelope are confirmed.
They do NOT themselves start a service or grant funding.

```bash
MM_PONS_HELD_PAPER_SHADOW=1
MM_PONS_HELD_SHADOW_MAX_SAMPLES=8
MM_PONS_HELD_SHADOW_EVERY_TICKS=10
```

Default without the flag: zero additional provider reads. With these flags,
each Pons position-owning process may perform at most eight optional samples,
roughly every tenth eligible, successful HOLD turn. Sampling resets in memory
on restart; original finite provider budget must always remain authoritative.
Only existing funded PAPER positions are observed. They are never reopened or
resized by the shadow. The first PAPER lifecycle still has its existing
allocation, phase and time limits; those must not be enlarged to fit a study.

Each sample covers at most forty block heights between *two consecutive native
quotes*, and the existing log-window reader splits into supported ten-block
subranges unless the exact credential/filter capability is verified. Upper
reference at forty blocks: eight filtered `eth_getLogs` logical elements
(two filters x four ten-block pages) and four header elements, about 560
diagnostic CU before retries, session authentication, cache hits and failures.
This is NOT the complete bill. Approximate eight-sample allowance per process:
4,480 modeled CU, 96 logical elements. The optional shadow is capped to a
two-second acquisition deadline and permanently suspends itself if an overrun
is observed. Original exit readiness takes priority at every turn.

## Measurements to collect from native PAPER telemetry

- `held_paper_shadow.enabled`, sample count, quote/mutation parity,
  `silent_net_quote_differences`, `unsafe`, optional probe time.
- Existing native before/after executable quote observations and all original
  hard-stop, trailing, partial, creator/demand and time-based exits.
- Method-specific billed CU, logical RPC elements, HTTP physical requests,
  delivered WS bytes (if streams are separately authorized), actual body
  bytes, governor pacing, queue latency, failed and repaired work.
- Shared overall CPU/RSS/storage, Pons Current and Survivor concurrency,
  protected owner clock and restored pending exits.

## Mandatory stop/go rules

Stop optional shadow work at first unexpected native economic discrepancy,
unproven canonical interval, original risk/exit latency breach, provider
governor backlog, budget pressure, restart inconclusiveness or any unhealthy
native/ledger state. Existing original PAPER owner continues to protect
exposure using fresh quotes; if the original owner is unhealthy, use its
existing exit/recovery handling, not this observer.

An actual reduction in producer requests is not claimed during this trial:
the shadow intentionally buys baseline native quotes AND optional coverage.
Do not report lower Alchemy billing simply because a historical counterfactual
could have omitted a quote.

**To proceed to the next, optimized PAPER trial:** independently establish
positive authenticated static hook/token/fee behavior, complete event
delivery/gap recovery, acceptable provider byte costs and zero worse
protective exits in side-by-side baseline vs candidate replay. Then explicitly
review a guarded quote-skip activation: same original 3s Survivor/5s Current
safety clock, mandatory fresh exact-quantity execution, prompt fallback on
unknown events/fees/reorgs, no quote reuse to fabricate risk/HWM, no liquidity
writeoff by missing transport, no automatic holding-policy extension and no
increase of the original usage allowances.

The intended operating economics are event-driven price-first holding rather
than continuous full economic requalification. Production access and activation
stay separately gated by objective measured evidence, not optimistic modeled
70-95% reductions.
