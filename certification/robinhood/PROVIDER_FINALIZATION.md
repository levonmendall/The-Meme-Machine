# Robinhood authenticated-provider finalization

Starting branch: `architecture/robinhood-evidence-plane-20260925`.
Starting and refreshed remote SHA: `dc8705bf266082c2cce0b6092ee4ed30574f98ce`.
No pull request exists for this branch at the initial refresh. The active market
certification branch remains `c9308774ad80edcaaea0a8e62bdf61668f9214c7`.

## Pre-edit requirement classification

| Requirement | Baseline assessment | Smallest necessary work |
|---|---|---|
| A: one authenticated authority | Needs change | Reject non-Alchemy primary and divergent DLMM aliases; preserve explicit diagnostics |
| B: shared endpoint governor | Needs change | Existing 0.5-second SQLite admission is optional; make canonical clients share it obligatorily |
| C: discovery separation | Mostly satisfied | Preserve public/sequencer discovery; add role and canonical-consumer regression guards |
| D: authenticated WSS | Verify/document only | No authenticated streaming is required by current exact-block HTTP consumers |
| E: exact HTTP state semantics | Already satisfied | Preserve existing block/hash/finality keys and frozen validation |
| F: broker bypass protection | Needs focused coverage | Extend existing runtime coalescing/fencing tests with provider-role and shared-store checks |
| G: credential isolation | Partially satisfied | Existing errors/fingerprints are sanitized; remove raw endpoint handles from acquisition context and tighten unknown failures |
| H: shared usage accounting | Needs change | Complete one endpoint-level view of wire attempts, logical demand, reuse, retries and estimated CU |
| I: fail-closed continuity | Mostly satisfied | Bind validated canonical identity across sessions and refuse alternate authority |
| J: health telemetry | Partially satisfied | Expose existing queue/backoff/retry/cache/storage signals without a new policy framework |

The durable Candidate Broker, lane projectors, route preflight, native financial
authority, restart fail-closed behavior, strategy economics and policy hashes are
preserved. No historical opportunity-loss reanalysis or live provider probe is
needed. Final certification uses the existing manual non-market harness. Local
SQLite work runs on reliable local temporary storage; prior failed workspace/WAL
certification evidence remains preserved.

## Final configuration and topology

`MM_ROBINHOOD_READ_RPC_URL` is the sole canonical authenticated configuration:
`https://robinhood-mainnet.g.alchemy.com/v2/<key>`. HTTPS, exact host, key path,
no userinfo/query/fragment, and Robinhood chain 4663 are required. No separate key
or authenticated WSS variable is used. Default HTTPS port and a trailing slash
normalize to the same provider fingerprint.

`MM_ROBINHOOD_DLMM_RPC_URL` is optional and may only identify that same endpoint.
A divergent alias fails closed before a canonical client is created. Discovery
configuration remains observation-only; an Alchemy discovery URL is bypassed in
favor of the official public RPC. Sequencer WSS remains public observation.
Shadow and QuickNode compatibility aliases remain explicit diagnostics only.
Pons's existing bounded public-observation gap repair uses the same canonical
Alchemy authority; it does not promote public data into authenticated evidence.
There is no automatic alternate canonical provider.

Authenticated WSS is **unnecessary**: discovery already supplies ordering and
candidate nominations; HTTP supplies exact authenticated receipts, headers,
block-pinned calls/code, current execution evidence and bounded repair. Existing
finality, freshness, hash-pinning and mutable-state non-reuse rules are unchanged.

Canonical clients require the existing SQLite endpoint admission governor and
shared immutable cache. Defaults live under `MM_ROBINHOOD_STATE_DIR`, otherwise
`~/.local/state/the-meme-machine/robinhood`. Both lanes must use the same durable
state directory. Existing certification provider/cache paths remain supported and
the current runtime composition already supplies the same paths to both lanes.
If only one path is provided, its shared sibling is derived. Production candidate
state also uses this common location. Missing/unwritable/corrupt storage fails
closed. This is single-host shared storage, not a distributed governor.

The unchanged aggregate maximum is **2 physical requests/second**, with a minimum
**0.5-second** admission interval. Ramses retains its **1 RPS** local canonical
pacer; Pons retains **2 RPS**. Existing backpressure can only slow the shared
endpoint: 429 cooldown is 8 seconds; Ramses adaptive shared interval remains
0.5–2 seconds. Public/dedicated observation and shadow limits are not increased.
Existing safety/decision priority context and bounded fairness remain. Explicit
entry/confirmation and bounded repair scopes receive their corresponding classes.

## Evidence, credentials and telemetry

Canonical clients verify chain identity before accepting cached or new evidence,
and recheck configured provider identity on use. Session recreation cannot change
canonical authority. Pons acquisition and Ramses route evidence reject public-role
clients, including a public client that correctly reports chain 4663.

Acquisition contexts hold opaque `alchemy:<fingerprint>` references, resolved
inside provider construction. Candidate and evidence stores persist digests,
never raw credentials. Unknown provider failures become constant failure classes;
responses that echo a credential fail closed. Tests inspect SQLite/WAL, provenance,
JSON reports, archived files and rendered exception/crash output using synthetic
secrets. Legacy provider topology tests that required independent canonical
endpoints were replaced with the stricter configuration contract; strategy tests
and strategy assertions are preserved (synthetic endpoint fixtures were updated).

One shared endpoint ledger records initiated physical HTTP attempts, logical wire
members by method, batches/members, retry attempts, 429s, queue wait, latency,
repair/current-execution work, sanitized failures and cooldown/queue pressure.
Materialized counters are updated transactionally, avoiding full transport-history
reconstruction on each telemetry read. Per-lane attribution is a view of the same
ledger, not separate governors or competing counters. Consumer logical demand is
reported separately from wire logical calls. Exact-cache reuse reports zero
physical work. A batch records one HTTP attempt and N logical members.

An initiated attempt is persisted immediately before HTTP I/O. Process death
leaves an explicit unresolved attempt; whether it reached the provider is unknown,
not silently zero. Provider acceptance and actual billed CU cannot be proven from
client telemetry alone. Completed attempts retain sanitized result classifications.
CU is estimated only from the repository's unchanged frozen method schedule;
unpriced methods remain unpriced. Historical pre-instrumentation physical totals
remain UNMEASURABLE.

Candidate telemetry retains unique-candidate denominators and adds observation
arrival counts, generation totals, claimed jobs, fenced obsolete completions,
complete canonical decisions and DB/WAL sizes. Existing lane transition/state
counts retain complete, rejected, deferred and censored classifications. Shared
cache telemetry exposes hits/coalescing, in-flight work and conflicts. These
counts and per-lane endpoint usage support future efficiency ratios without
claiming historical physical-request or profitability improvements.

## Certification and deferred scope

The existing manual Robinhood non-market harness now derives explicit provider
gates from actual passing native tests (no duplicated provider-validation runner).
It retains all component, supervisor, replay, crash/restart, integrated lifecycle,
resource and source/policy checks. Failed local test evidence is retained. The
final certificate identifies its exact runtime SHA; no pass is asserted by this
document before that certificate exists.

Frozen sources remain Pons `3de3d376847531ccb90e260cfcc96c37587ccb23` and Ramses
`41b5f263efc31bedf9b39039a9f66bed264b70d3`. Strategy/policy/economics, accounting,
position-controller authority, freshness/finality and paper-only controls remain
unchanged. Adapter/configuration identity changes fail closed on incompatible
pre-existing candidate interpretations; they never reconstruct missing native
financial state or create a portfolio.

Prospective coverage/censoring, actual HTTP totals and CU, CU per complete decision,
429 behavior, provider latency/throughput, sustained market load and overall
opportunity-loss acceptance remain **deferred**. No authenticated streaming is
introduced, so no authenticated-stream operational validation is claimed.
No workflow, trigger, dispatch, continuation, deployment or protected branch is
modified by this implementation.
