# Run 380 preserved evidence and ongoing persistence repair

Run 380, workflow `36278710306`, ran exact certified runtime
`ee6523fb599f25e04e08fda67b7b14bbb7f9d2a6` on
`cert/single-market-ee6523fb-20260926`. Native run:
`e4a9e49e-5fd9-4b6f-b8bb-6ba8fff2783a`.

Full non-market certificate `36278007375` passed all eleven gates, 1,651 native
tests and 373 supervisor tests. Standard CI `36278007388` passed 707 tests
(12 skips). Certificate artifact `10918640216`, SHA256
`5ce3e7d169e6971650ec680ec07b78fd865e90e4b5338cb37cb796412c2dba6d`,
matches the runtime, prepared source identities and latest promoted policies.
The promoted strategy base remains `4ab66653a23475a72abe88bc96adf9f6e0b7fd9a`.

## Preserved identities

* Primary artifact `10918621171`, 1,236,375,119 bytes, SHA256
  `2ed8ce809cc7a19f56aefb80186aaef589ce115a0f05a0cbacb4ee62b3555abb`.
* Compact artifact `10917779057`, SHA256
  `7643724bdbdc64497e6d1545ac685c9e920356c4622a4871c3855f0357b87f14`.
* Read-only review `36279312523`, source
  `7f9b704f6cbdfb68891fc90b286c6b4d8638856e`, artifact `10917962022`, SHA256
  `3ec043253048059090aee900cf5dde0bd62f91fd68d044746ebf9ce0947ad59f`.
* Bounded replay extraction from the same primary archive: `36279709558`, source
  `1800bdc6b373f0bd0267fd036e7c71828efe2c13`, artifact `10917927234`, SHA256
  `f9650361a51405500fdb62e340eda3e38525f5b35f2e53aea0689e24a7e87bf0`.

Both reviews verified the primary archive digest and exact runtime identity.
Neither had provider credentials or performed fresh market acquisition.

## Confirmed result

Smoke failed. Pump exited at 156.83 seconds with
`meme_machine.provider.Unavailable: evidence_finalized_stale`; its observed
finalized lag was 81.65 seconds. Meteora remained alive through 601.43 seconds
but correctly reported the same evidence failure, with 86.40-second lag and 257
`infrastructure_evidence_unavailable` terminals. This was not strategy rejection.

Pons exited normally after its bounded terminal work at 668.19 seconds. Pons
Survivor completed 120 successful, admission-enabled steps with PAPER allocation
authority. Ramses exited normally at 600.32 seconds, completed its screen, and
rejected three pools for strategy reasons. All four books finished flat and
reconciled. No PAPER entry occurred. Shared-sleeve and policy identities remained
unchanged. Limited 429s are retained separately; no provider topology change is
justified by these responses alone.

The authority state ended `HALTED`, with native exposure explicitly `flat`.
Its history contains only authorization, claim, smoke begin and smoke native
start. Successor, continuation and retry remain false. Hourly and transition jobs
were skipped. No successor ran and no nonexistent exposure was invented.

## Remaining Solana persistence throughput defect

The receive-capacity/IPC churn repairs held: zero local-capacity disconnects,
zero queue overflows, no repeated acknowledgment failure. However bounded
backpressure alone did not provide sufficient sustained throughput.

The stream processed about 6.687 GB across 1,385 accepted data messages. Ordered
commit used about 663 seconds of the 700.55-second overall run, in 540 batches;
peak commit was 2.40 seconds. Dispatch stayed bounded at 28 frames / 95,343,394
bytes; peak ordered wait was 12.63 seconds. The store accumulated approximately
6.94 million address references. Maintenance made progress (30,080 archived
records); service shutdown was clean and did not force-kill admitted work.

Receipt availability proves accumulating backlog: initial source-receipt lag was
about 10 seconds, median 51.75 seconds, and peak 276.09 seconds. Two
`ConnectionClosedError` discontinuities created six gaps; four repaired, while
two Pump gaps remained unresolved at the runtime terminal snapshot. The original
exception classification does not prove a particular provider-close reason.
Normal service-shutdown gaps are separate from those runtime gaps.

The strengthened readiness classifier correctly failed material local gap
blocking despite bounded queues, process liveness and reconciled accounting.

## Repair work in progress

Offline profiling uses bounded lossless transaction and economic-log samples
from this exact archive. It exercises real `ServiceState.source_batch`, scope
decoders, durable storage and receipt sealing. Missing full original provider
frames are reconstructed as explicitly synthetic envelopes around retained
bodies; they are not claimed as new authenticated market observations.

Initial profiles identify repeated JSON serialization, SQLite address indexing,
per-record savepoints and empty economic-ingest calls inside the serial owner.
A transaction-local address-index prototype alone did not materially improve
the mixed replay. A populated-store comparison and source-clock-preserving
production-pressure regression are required before selecting a repair.

No repaired candidate has yet been certified or sent to the market after Run 380.
Thresholds, strategies, queue limits, freshness, provider governance and PAPER
authority must remain unchanged.

## Confirmed candidate retention defect

Thirteen completed/rejected Meteora candidates retained active candidate interests,
starting at slot 450818929. Address-scoped archive pins protected their payloads;
the scope retention floor also prevented reclamation of old whole-program indexes.
The final store contained 7,032,199 address references. The native candidate loop
now releases its acknowledged candidate interest in a `finally` block. Open-position
leases have separate identities and remain protected until resolved.

A regression invokes the real native runner for compatibility rejection, warmup
rejection, qualification rejection, and unexpected failure. The old implementation
fails all four subcases; the repaired implementation releases only the candidate,
retains an independent unresolved position, and allows the retention floor to
advance only after that position is explicitly resolved. Twenty-one affected
Meteora production-path tests pass. The native policy file is untouched.

## Fixed-source-clock hosted reproduction

Provider-free comparison `36281366490`, analysis source
`4448f30c270af61fbc13079e36249472754568e5`, replayed 480 reconstructed 4.082-MB frames
(1.959 GB) with a fixed 0.27-second source cadence. Timestamp assignment occurs
before receiver backpressure, so a slow reader cannot make old evidence look fresh.

* Preserved runtime: 222.48 seconds to process a 129.6-second source window;
  peak source lag 93.67 seconds. Artifact `10919510049`, SHA256
  `a8a87423afc5ab9f82c090eb468944bf0125518a98c6acdf689e05bd4c071b2b`.
* Initial repair (per-frame rollback and single content validation/serialization):
  175.41 seconds, peak lag 46.51 seconds. Artifact `10918253736`, SHA256
  `06b9b72a18056796312b6b988613d7fa2d0aa81ad941c5fc367dd7101c77cb0e`.

The initial repair was rejected as insufficient for sustained market operation.
No market workflow was launched. The reproduction confirms that bounded draining
alone does not establish sustained readiness. Both paths stayed within existing
frame/byte bounds; the three gaps emitted after intentional stop are shutdown
boundaries, not runtime capacity gaps.

The next prototype moves pure record decoding, canonical hashing and lossless hot
encoding to the existing two decode workers. Ordered owner transactions still
validate source identity, enforce retention/storage limits, detect conflicts,
persist content/lineage/censuses, and publish coverage. Per-frame preparation has
a 16-MiB canonical-content budget; unusually expansive frames retain the exact
serial path instead of being dropped. No queue, timeout, freshness or strategy
threshold is enlarged. New bounded preparation metrics identify usage and fallback.
Prepared/serial parity tests cover all three Solana scopes and pickle transport.
Full certification is pending stabilization and hosted pressure verification.


Hosted prepared-worker verification `36281875254` (analysis source
`47c23260e805e58604a3d1d78207633c4705b8a9`) processed all 480 frames / 1,959,362,398
wire bytes in 130.09 seconds against a 129.6-second source clock. Peak source lag
was 1.742 seconds, outstanding frames five, dispatch bytes 20,410,025, maximum
commit batch 12,246,015 bytes. All 481 received protocol/data messages committed;
no reconnect or local-capacity failure occurred. Prepared payload peak was
3,409,099 bytes. Serial owner source execution fell to 87.60 seconds while the
existing decode workers performed pure preparation concurrently. Artifact
`10919007882`, SHA256
`188d8005406123bf3dd0bfda112ac5834252268f725c4cbefdb8da3e6aa36561`.

The canonical suite now includes a 240-frame fixed-source-clock replay with real
local IPC, concurrent control commands, authoritative candidate reads, ordering,
gap detection, durable drain, integrity and unchanged pressure-bound assertions.
The five atomic/preparation regressions cover all-scope byte/hash/lineage parity,
pickle transfer, real preparation-budget fallback, source identity mismatch,
late-frame rollback, prior-frame durability and fail-closed explicit gaps.
Twenty affected transport/pressure tests pass. The additional sustained replay
requires a 600-second non-market native suite budget and 20-minute hosted job
budget; these changes affect certification scheduling only, never market runtime
deadlines or evidence freshness. Exact integrated certification remains mandatory
before any new market contact.
