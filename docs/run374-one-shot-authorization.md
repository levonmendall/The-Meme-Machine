# Run 374 one-shot PAPER authorization

Base repair SHA: `ace36e9e7dee9bee3e52d14507d5796e2fa74352`.

This branch changes only the one-shot single-campaign authorization/control wrapper
needed to authorize exactly one fresh PAPER four-lane workflow after Run 373 exposed
Solana dispatch saturation and the repaired ordered-parallel dispatch runtime was
fully non-market certified.

No live-money authority, workflow reruns, automatic successors, or dispatch retries
are authorized.
