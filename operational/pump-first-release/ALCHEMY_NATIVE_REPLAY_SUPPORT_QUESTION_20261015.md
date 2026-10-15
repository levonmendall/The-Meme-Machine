# Sanitized Alchemy replay-contract question

Prepared for technical clarification; **not sent**. No credentials or team ID are
needed. Existing mainnet application: `9bin99s96t7ga5e9`. Native host:
`solana-mainnet.streaming.alchemy.com:443`, authenticated using the unchanged
application binding. HTTP endpoint identity SHA256:
`8f3feda9d10baa64d74b5ecb3a97cfa48af379982666f93a425e537668a51749`.

At approximately 2026-10-15T00:36:11Z, two authenticated subscriptions returned
INVALID_ARGUMENT: `failed to get replay position for slot 457039819`. The
contemporaneous HTTP finalized tip was 457040075; requested from_slot was exactly
tip minus 256. Neither subscription delivered a native frame.

The exact request forms were:

```text
commitment: FINALIZED
from_slot: 457039819
blocks_meta { key: "b" value {} }
slots { key: "f" value { filter_by_commitment: true } }
```

```text
commitment: FINALIZED
from_slot: 457039819
accounts {
  key: "p"
  value {
    owner: "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    filters { memcmp { offset: 0 bytes: 0x17b7f83760d8ac60 } }
  }
}
accounts_data_slice { offset: 0 length: 49 }
```

At 01:04:51Z, SubscribeReplayInfo reported first_available=456183362 and native
FINALIZED GetSlot reported 457048070 on one TLS channel. Both returned OK; neither
identified the underlying replay backend beyond istio-envoy.

A subsequent single bounded capability experiment at about 01:30:12–01:30:16Z
reported first_available=456190360 and matching HTTP/native FINALIZED tips 457055103.
Both exact request forms at from_slot=457054847 (tip minus 256) returned matching
content. The experiment stopped each stream after 64 messages, rather than claiming
complete replay coverage. Both streams began at 457054816, **31 slots before** the
requested cursor. Control returned 32 finalized slot updates and 32 block metadata
updates, through 457054847. The 64 correctly filtered 49-byte Pump account updates
covered 457054816–457054825. There was no semantic rejection, so no CONFIRMED
comparison or retry was performed.

Please clarify:

1. What exact cursor contract does this application/endpoint support for these
   FINALIZED filters? Must from_slot refer to a produced slot, an extant replay
   buffer position or a specific chunk boundary? How should unavailable/skipped
   slots be requested while preserving complete interval evidence?
2. What does SubscribeReplayInfo.first_available guarantee across accounts,
   block metadata, finalized slots, commitments and load-balanced backends?
   Does one TLS channel establish replay-backend affinity? Is a backend/request
   identifier available for correlation?
3. Is delivery before from_slot documented replay granularity/overdelivery, and
   does matching data from the requested cursor onward remain guaranteed? Why
   could the original 256-slot overlap be rejected despite the later much older
   advertised floor? Can this be corrected in existing provider configuration?
4. Which published replay-window statement applies to this bound endpoint:
   [6,000 slots](https://www.alchemy.com/docs/reference/yellowstone-grpc-subscribe-request)
   or [approximately 432,000](https://www.alchemy.com/docs/reference/yellowstone-grpc-historical-replay)?

We have not shifted/aligned/clamped the cursor, changed finality or filters,
omitted required evidence, advanced canonical checkpoints or migrated providers.
Please provide the supported coverage-preserving recovery procedure, rather than
an arbitrary offset. Same-channel sampling and request acceptance alone do not
establish original backend attribution or complete historical coverage.

Exact requests, timestamps, sanitized metadata and retained protobuf hashes are
indexed in [native-replay-capability-result-20261015.json](evidence/native-replay-capability-result-20261015.json).
