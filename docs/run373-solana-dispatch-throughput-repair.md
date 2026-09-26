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
