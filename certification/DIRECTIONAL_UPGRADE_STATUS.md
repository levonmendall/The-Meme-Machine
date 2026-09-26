# Pump/Pons six-regime PAPER upgrade

Implementation checkpoint; **not certified or promoted**. No market execution is
part of this work. No signing, transaction submission, live money, deployment,
or Render interaction is authorized.

- Base: `cert/single-market-runtime-v2-20260926`,
  `af60b355995dfa960555288fa73808bb7aba5d25`, full certification `36244774274`.
- Canonical active ref checked: `cert/prospective-market-v1`; its older
  `c9308774ad80edcaaea0a8e62bdf61668f9214c7` is not a successor to the requested base.
- Excluded failed repair `1c77dc2a0c6b32515ad3b72f6edd5879f45869e7` is not used.
- Pons Survivor policy and original regressions start from
  `8cbebf942c6bbb6538a2764f97346963c3352fb8`; the policy is extended with the
  requested commit retention, staged realization and durable shared-sleeve runtime.
- Current strategies retain their alpha gates. New sizing is capacity-only.
- Exactly four lane manifests; two strategy namespaces in each directional sleeve.
  The second namespace's nominal native-ledger genesis is subtracted from the
  aggregate. Only one shared reservation authority funds each sleeve.
- The neutral Survivor PaperBook is a reuse of the prepared certified Pump
  `meme_machine/paper_accounting.py`, not an alternative accounting design.

Focused tests already exercised exact 60%/65% retention, stale generations,
reservation restart, idempotent fill, deterministic downsizing, partial accounting,
exit intent, and frozen entry boundaries. Hosted full suites remain required.
The local environment has a PID namespace mismatch (`os.getpid()` versus `/proc`)
that breaks existing provider process-liveness/coalescing tests; no provider
liveness rule has been weakened to accommodate it.

UNKNOWN evidence remains UNKNOWN. In particular the on-chain Mayhem coin flag
and disclosed agent identity do not prove the agent completion timestamp. Without
an authenticated completion timestamp plus a complete 60-minute clean window,
a Mayhem Survivor entry is blocked. Agent flow is excluded independently.

Remaining: finish adapter/boundary/integration checks, prepare and verify actual
composer manifests, archive the immutable old cohort and freeze the new one,
complete bounded preserved-evidence validation, full offline certification of the
exact SHA, then canonical promotion of that same SHA. This checkpoint is not
prospective profitability evidence.
