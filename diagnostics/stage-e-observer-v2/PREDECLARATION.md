# Exact candidate observer v2 — blocked predeclaration

PAPER ONLY. Astra authorization: `AUTHORIZE_EXACT_CANDIDATE_OBSERVER`.
This is a durable blocked declaration, **not a valid execution ticket**.
No benchmark trial or pressure runtime has started. The declaration cannot bind
an actual full-cohort frame tape or executable benchmark driver without an
approved equal-byte source/clock binding. Its JSON records those fields as null;
configuration/source hashes must not be mistaken for actual execution-input hashes.

- Candidate S: `7a516a6a92be9347661ac0e7f560971c171a0931`.
- Candidate tree T: `9da7d1e1625ba04c1437c63606c90f5e293bdba7`.
- Reviewed assembly digest: `08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659`; all 1241 files matched.
- Plan SHA256: `6c40324250e0870a9207161a0b944d58272922c90bf6fce97c57c2bb3dda16df`.
- Input manifest SHA256: `d38f0ea0978ef629f5af57bc778a5ee77e3115ed5cb4c5dd0e35280f184bb983`.
- Observer contract SHA256: `9695ef0d1f039cc688d6a7b34d1d8e8e00a4d3df43a6b7cf14c9cb6c0eaf3e84`.
- Workload identity: `native-full-cohort-pressure-v2`.
- Blocked workload descriptor canonical SHA256: `ed24682f4ed9ac6bccae022f4161f07c1befc9d9ee5da9a41236a4f3aa9f3a6b`.
- Workload binding artifact SHA256: `a98075d753066c2481b051de5f3bc3688aa9f1137c5b000bb53c82fd24c334f7`.
- External static diagnostics harness SHA256: `25d07ce544b740eb359752d2173da9641ae9705672866cf90d2ae55885cd3a68`.
- Actual frame tape SHA256 / executable benchmark driver hash: UNBOUND.

The retained plan cohort is combined-1/2/3, each 2,223 frames, plus recovery-1,
4,445 frames. The 1,334-frame capacity-screen prefix is excluded. The intended
order is fixed below; these are planned identities, not executions.

1. `observer-v2-20261002-exact-7a516a6a-t01-p1-baseline` — pair observer-v2-20261002-exact-7a516a6a-p1, baseline; NOT STARTED.
2. `observer-v2-20261002-exact-7a516a6a-t02-p1-observed` — pair observer-v2-20261002-exact-7a516a6a-p1, observed; NOT STARTED.
3. `observer-v2-20261002-exact-7a516a6a-t03-p2-observed` — pair observer-v2-20261002-exact-7a516a6a-p2, observed; NOT STARTED.
4. `observer-v2-20261002-exact-7a516a6a-t04-p2-baseline` — pair observer-v2-20261002-exact-7a516a6a-p2, baseline; NOT STARTED.
5. `observer-v2-20261002-exact-7a516a6a-t05-p3-baseline` — pair observer-v2-20261002-exact-7a516a6a-p3, baseline; NOT STARTED.
6. `observer-v2-20261002-exact-7a516a6a-t06-p3-observed` — pair observer-v2-20261002-exact-7a516a6a-p3, observed; NOT STARTED.

The intended baseline disables qualification observation; the observed arm enables
it. Both must receive identical input bytes, source clocks, cadence, pauses, delays,
worker limits, source charge, urgent/control behavior and termination. All observer
setup, lifecycle reads, SQLite/held observation, computation, serialization,
persistence, and child/helper work must fall within the identical
`time.perf_counter_ns()` start/end boundaries. Complete elapsed times alone form
the measurement. Do not add overlapping internal timers or subtract observer cost.

The blocker is reproducible by static inspection in `STATIC_BLOCKER.json`.
`tests/test_run380_production_pressure.py` sets `self.start=time.time()`, then
`due=self.start+self.sent*.27`, then writes `int(due)` into each block.
`certification/run381_pressure.py` additionally retimes embedded economic log bytes
to that timestamp. Sequential arms therefore receive different bytes. Caching them
for the next arm leaves old timestamps under the unchanged source-lag/residence
limits. The approved fixed-clock v2 Run380 fixture is 240 frames and its builder
rejects indices >=240. It does not define the retained complete-cohort adapter.
An external wrapper is authorized; choosing an unbound source/clock adaptation
would not establish the requested exact workload identity.

`ENVIRONMENT.json` binds hostname, CPU count/affinity/quota, memory, filesystem,
resource limits, Python version/executable hash, SQLite, standard library,
websockets version/content and relevant safe environment variables. Its runtime
environment exactly equals the reviewed assembly environment. No scheduler or CPU
tuning was performed. `REVIEWED_ASSEMBLY.json` retains the original manifest;
outputs and separately hashed diagnostics stay outside that read-only assembly.
`STATIC_MODULE_ORIGINS.json` records static-preflight module origins. No workload
child was started, so no trial child-origin proof is earned.

The no-retry policy is exactly three pairs in baseline-observed,
observed-baseline, baseline-observed order, retaining invalid pairs. Any started
crash/disconnect/interruption, identity or workload mismatch, incomplete execution,
lost evidence, provider attempt, environment/origin drift, observer error/drop,
nonpositive baseline, or observed time below baseline invalidates the benchmark.
Each trial's raw evidence must be durably preserved before the next starts.
All six must have provider calls = 0 and provider attempts = 0.

Acceptance requires `numerator_ns*100 < denominator_ns` and the native
`certification.stage_e_native_v2.observer.verify` result. Equality fails; no manual
rounding is allowed. The existing native verifier rejects the diagnostic object
with zero raw pairs as `observer_raw_pairs_missing`. That is a diagnostic rejection,
not verification of a complete fresh measurement. No overhead result is earned.

The durable GitHub readback receipt will be recorded separately by commit and
content hashes. No trial may start from this blocked declaration. Stage E remains
RED and Stage F remains NOT STARTED. STOP FOR ASTRA.
