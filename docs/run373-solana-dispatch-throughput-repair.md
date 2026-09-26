# Run 373 Solana dispatch-throughput repair

Base repair SHA: `1c77dc2a0c6b32515ad3b72f6edd5879f45869e7`.
Incident market run: `36253445901` (Run 373).

Run 373 proved the Run 372 large-frame repair eliminated websocket keepalive
starvation, but the bounded downstream dispatch path saturated under sustained
Solana block volume. The live smoke observed 9,832 received frames, 5,783
accepted stream messages, 7.08 GB accepted bytes, 56 dispatch overflows,
55 fail-closed reconnects, and 188 unresolved gaps. Pump completed zero local
authoritative reads.

This repair preserves the existing 64-frame / 96 MiB memory bounds and changes
throughput/continuity instead:

- account-subscription reconciliation runs independently of the frame commit path;
- two process decoders compact large block frames concurrently;
- authoritative SQLite commits remain strictly websocket-receive ordered;
- outstanding frame/byte accounting remains bounded until commit;
- on capacity exhaustion the receiver stops, every already-admitted frame drains
  through ordered commit, then the discontinuity is recorded at the true first
  unretained frame boundary;
- telemetry separates decode queue wait, decode duration, ordered-commit wait,
  SQLite commit duration, subscription sync, outstanding depth, and drain time.

Focused regressions include a sustained Run-373-shaped 10+ MiB block stream near
13 MiB/s and a forced tiny-buffer overflow proving admitted frames commit before
the gap is created.

PAPER ONLY. No market workflow is authorized by this repair or its certification.

Focused prepared-runtime certification: workflow 36255447776 passed.
Prepared Pump diff SHA256: `5349956f0ae189d6e19be348b675e912f18083845740d3b5c4e1c0fd77f96be3`.
Prepared Meteora diff SHA256: `7153ef534181073c7e769dc675ed43bc51d4c81368a9bdcf24ddba2241af2055`.

Certification bookkeeping repair: the historical Meteora receipt now pins Git diff abbreviation to 7 characters and requires the original frozen overlay SHA256 `ce328f328c0ea95d3e681da3c8912a095c13cc0aa590999088c161843df48503`. This corrects repository-growth-dependent object-ID abbreviation without changing historical economics or exposure disposition.
