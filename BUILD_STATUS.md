# Build status / continuation

## Repository and authority

Repository: `levonmendall/The-Meme-Machine` (public). Canonical base `main` remains
`54712c4c6470cc4dc267888f934bd693aac030d0`. Implementation branch is
`feat/pump-directional-paper`; PR #1 remains open and unmerged.

Do not merge, deploy, purchase services, enable signing/submission/live money, add
DLMM/other venues, or alter predecessor repositories/services without separate
authorization. The shared paper portfolio remains $500. `continuation-v1` is frozen
while qualification evidence is accumulated.

## Current implemented boundary

The only implemented trading surface remains Pump.fun bonding-curve trading on Solana
mainnet, including ordinary native-SOL curves and native-SOL Mayhem Mode. Cashback and
non-native quote assets remain fail-closed. The disclosed Mayhem agent wallet cannot
scout or count as independent demand. DLMM remains disabled.

The connected paper lifecycle is:

wallet scouting -> unchanged `Engine.qualify` (`continuation-v1`) -> shared allocator
-> reservation -> delayed finalized fill -> monitoring -> exit -> settlement ->
restart-safe reconciliation.

The forced real-data canary at
`d724bc8d6fdbc3f239b311bad0cb20baecdca865` already proved the downstream mechanics
against live Pump observations. It forced only paper authorization in isolated
state and is not strategy/performance evidence. Its true unchanged policy result was
`exit_liquidity`.

## Point-in-time evidence and resource bounds

The complete 60-second market-history requirement is supplied by one finalized
Pump-program `logsSubscribe` stream. Nomination authority starts only after a full
uninterrupted 60-second warmup. Disconnect, parse loss, time inconsistency, or tape
capacity loss fails closed and requires a fresh warmup. The tape retains 75 seconds
and at most 50,000 decoded trades.

Concentration retrieval first uses the same public RPC with a compact finalized
`getProgramAccounts` mint-filtered 8-byte amount scan. The existing top-five <=35%
policy input is unchanged; `getTokenLargestAccounts` remains fallback.

Storage/memory longevity is separately bounded. Journal bodies rotate at 4,096 rows
back to 2,048 while preserving a verified chain anchor. Repeated identical unresolved
exit marks are still polled every five seconds but durably recorded at most once per
60 seconds; real failed exit attempts remain immediately durable. The accelerated
24-logical-hour soak at 1,200 decoded events/minute passed every plateau assertion:
DB+WAL stabilized near 1.96 MB, RSS at 30,232 KiB, tape occupancy at 2,400, RPC cache
at 128 entries, and durable writes remained 780/hour rather than accelerating. This
is a logical-runtime boundedness proof, not a true 24-hour wall-clock residency proof.

## Frozen-policy qualification research milestone

The qualification research implementation was added after the longevity milestone
without modifying `Engine.qualify` itself. The current `engine.py` qualification
behavior remains the same frozen `continuation-v1` authorization path; research code
lives separately in `meme_machine/research.py` and is never called by `Engine.consider`.

For every **natural, already-admitted, post-warmup nomination** that reaches complete
point-in-time evidence, the shadow validator now records a complete qualification
vector in addition to the canonical first decision returned by `Engine.qualify`.
The vector contains:

- canonical unchanged `actual_reason`;
- all simultaneously measurable rejection reasons, not only the first one;
- concentration bps and margin to the current 35% gate;
- real SOL exit liquidity and margin to the current 10 SOL gate;
- evidence-event count and margin to the current 100-event cap;
- independent buyer-group count and margin to the current minimum of 3;
- independent net buying and margin to the current 1 SOL minimum;
- current/scout price-extension bps and margin to the current 120% cap;
- exact-size modeled round-trip loss bps and margin to the current 5% cap;
- allocator result and structural evidence validity;
- one-threshold-at-a-time **research-only** counterfactual sensitivity values.

The nearby counterfactual grid is intentionally non-authoritative:

- concentration max: 30%, 35% (current), 40%, 45%;
- real exit liquidity min: 5, 7.5, 10 (current), 12.5 SOL;
- evidence-event cap: 75, 100 (current), 125, 150;
- independent groups min: 2, 3 (current), 4;
- independent net buying min: 0.5, 1.0 (current), 1.5 SOL;
- price-extension max: 110%, 120% (current), 130%;
- modeled round-trip loss max: 3%, 5% (current), 7%.

These numbers are observation scenarios only. They do not alter `Engine.qualify`, do
not authorize reservations, and must not be used to manufacture a paper trade.

The natural live diagnostic can evaluate up to four unique nominated mints per bounded
session. Each live run writes one `qualification-report.json` and the workflow stores
it as a uniquely named 90-day GitHub Actions artifact using the pinned
`actions/upload-artifact` v4.6.2 commit. Repeated workflow attempts therefore accumulate
separate evidence instead of overwriting one report.

`tests/analyze_qualification_vectors.py` aggregates those reports (or artifact ZIPs),
deduplicates repeated observations by nomination ID, ignores non-natural/canary rows,
and reports:

- canonical first-reason counts;
- all-rejection counts and sole-vs-multiple rejection attribution;
- current-policy qualified count;
- one-threshold-at-a-time pass counts and pivotal-rejection counts.

The default minimum review sample is **50 unique complete natural nominations**. Until
that threshold is reached, analysis returns
`insufficient_sample_for_threshold_revision`. The intended research window is 50-100
unique complete nominations before any human decision about revising a threshold.
No automatic threshold optimization or promotion exists.

## Verification

Qualification research code through
`92493ce0b6602145cdbb9ec74ab521345e561b00` passed the deterministic unit phase with
**69/69 tests**, including explicit regressions that:

- a fully qualifying synthetic candidate still returns `qualified` under frozen
  `Engine.qualify`;
- a concentration rejection remains a concentration rejection even when the
  research sensitivity shows a looser counterfactual would pass;
- multiple simultaneous failures are visible after the canonical first rejection;
- aggregation deduplicates nomination IDs and excludes non-natural rows;
- sample size below the minimum cannot become a threshold-revision conclusion.

Normal resource and connected synthetic lifecycle checks remain required on every
head. Intermediate `[qualification-build]` commits intentionally suppress the live
network diagnostic so code edits do not waste public RPC capacity.

## Exact continuation

Next action is evidence accumulation, not policy editing:

1. run the bounded finalized-stream diagnostic on the final research head;
2. preserve each report artifact;
3. continue collecting natural complete qualification vectors without changing
   `continuation-v1`;
4. once at least 50 unique complete natural nominations exist, run
   `tests/analyze_qualification_vectors.py` over the accumulated artifacts;
5. review rejection attribution and sensitivity before considering any policy change;
6. if the sample is below 50, preserve `continuation-v1` unchanged.

Do not count forced canaries, synthetic fixtures, pre-admission scout activity,
incomplete evidence, or repeated nomination IDs toward the sample.

## Reproduce

```sh
python -m pip install -r requirements.txt
python -m unittest discover -v
python -m tests.resource_check
python -m tests.make_tape
python -m meme_machine --mode synthetic --config config.synthetic.json --db /tmp/meme-fresh.db --tape tests/fixtures/synthetic_lifecycle.jsonl
python -m tests.prospective_stream_qualification
python -m tests.analyze_qualification_vectors --min-sample 50 <artifact-or-report-paths...>
```

The 24-logical-hour storage/memory proof can be repeated with:

```sh
python -m tests.longevity_soak --hours 24 --events-per-minute 1200 --writes-per-minute 12
```
