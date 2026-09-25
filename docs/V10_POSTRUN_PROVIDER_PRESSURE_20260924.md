# V10 Post-Run Provider Pressure Audit — Run 36077647211

## Scope

This repair/audit follows the completed engineering-valid paper campaign `36077647211`
on runtime `7b3674dd7b4381f20bb1ccf3dfd7194d818a6719`.

No market workflow is authorized or launched by this work. Frozen strategy economics,
target-market definitions, evidence freshness/finality, position sizing, portfolio/accounting
rules, provider ceilings, and paper-only authority remain unchanged.

## Pons — public eth_getLogs HTTP 429

Observed in the accepted hour:

- 5,198 logical `eth_getLogs` reads;
- 5,012 routed to the official Robinhood public RPC;
- 186 routed to authenticated Alchemy;
- 36 HTTP 429s, all attributed to `eth_getLogs`;
- no broad provider switch and no routine-discovery migration to Alchemy.

Repair: `public-log-method-adaptive-retry-v1`.

For public-RPC `eth_getLogs` only:

1. retain the existing <=10-block discovery range and existing 2 RPS ceiling;
2. after a public HTTP/RPC 429, apply a short method-specific cooldown;
3. honor a short `Retry-After` value when it is <=1 second, otherwise use 0.6 seconds;
4. retry the identical range once on the same official Robinhood public endpoint;
5. only if that same-range retry still fails, use the existing exact-range authenticated
   Alchemy recovery path;
6. reduce only the public log pacer after a 429 and cautiously recover by 0.1 RPS after
   20 successful public log reads, never above 2 RPS;
7. preserve exact cursor/range semantics: the caller does not advance its canonical
   sequencer cursor until the read or its exact recovery succeeds.

New bounded telemetry records public 429 count, same-endpoint retry success/failure,
cooldown seconds, effective public log RPS, exact Alchemy recoveries, and unrecovered ranges.

The exact Pons prepared-tree source diff after this repair is:

`d11bfe346004d8fc027d3344146e6c4962cab7485f1bcd3e68d60968c9fee143`.

## Pump — getSignaturesForAddress pressure

Accepted-hour evidence:

- 925 logical `getSignaturesForAddress` calls;
- 20 HTTP 429s, all on `getSignaturesForAddress`;
- 18 shared-governor queue deadlines;
- zero provider-failed Pump candidates;
- one natural Pump settlement completed and reconciled.

The shared Solana governor already had method-specific 15/30/60-second backoff for
`getSignaturesForAddress`, but it also applied an additional 8-second provider-wide
cooldown after every method-scoped 429. In this hour all Solana rate errors were isolated
to `getSignaturesForAddress`; unrelated methods showed zero rate errors.

Repair: `method-scoped-signature-cooldown-v1`.

When a 429 is attributable only to `getSignaturesForAddress`, the existing method
cooldown remains authoritative, but the additional provider-wide 8-second stop is omitted.
Other methods retain the prior provider-wide behavior. The shared physical request ceiling
remains 2 RPS / 0.5-second minimum interval. This does not increase provider throughput.

## Meteora — reconstruction and observation-close audit

Accepted-hour evidence:

- 1,134 discovered pools;
- 22 authenticated triggers;
- 19 reconstruction-complete trigger states;
- 12 unique reconstruction-incomplete classifications;
- 27 `pending_at_observation_close`;
- 8 complete economic vectors;
- zero provider-failed candidates;
- zero entries and zero open positions.

The 27 observation-close cases are not an acquisition bug. They map to the frozen
`campaign_window_insufficient_preentry_time` rule: the lane intentionally requires
162 seconds of trigger/warmup/evidence reserve before beginning a new pre-entry sequence.
Finishing those sequences after the one-hour discovery window would contaminate the block.

The remaining reconstruction-incomplete cases retain explicit fail-closed authenticated
reasons, including unsupported/mixed liquidity mutations and bounded signature/transaction
reconstruction pressure. No evidence supports relaxing the strategy clock, reconstruction
authority, transaction capacity, or provider limits.

Conclusion: no Meteora code/economic relaxation is justified from this block. Preserve the
existing classification and count these cases as observed infrastructure/structural evidence.

## Cohort identity

Because Pons execution/certification code changed, the next prospective cohort identity is:

`prospective-four-lane-v10-provider-pressure-20260924`.

Pump/Meteora strategy source identities remain unchanged. The integration SHA will change
because the shared certification governor and Pons overlay changed.

## Authorization

This work is deterministic/non-market only. It does not create a market authorization,
does not dispatch a market workflow, and does not grant live-money authority.
