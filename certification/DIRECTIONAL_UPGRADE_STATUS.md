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

The new common cohort is `prospective-four-lane-six-regime-v13-20260926`.
The prior v12 protocol is archived byte-for-byte under `certification/cohorts/`.
`profitability_protocol.json` commits all six regime identities plus both shared
sleeve identities. Allocation resolves in the sleeve's append-only serial order:
the first durable reservation owns capital, and restart cannot reorder it.

The prepared composer manifests pass source/hash verification. The focused
six-regime integration gate passes all lane, policy, sleeve and unchanged-strategy
checks. One bounded preserved-input pass passes 90 tests (Pump 26, Pons 33, shared
31); historical Survivor profitability and missing historical evidence remain
UNKNOWN. The local supervisor suite runs 338 tests; three existing provider
process-liveness tests fail from the documented local PID namespace mismatch.
Those tests remain enabled without modification in the hosted full certification.

The exact candidate must pass the full hosted deterministic/non-market workflow
before canonical promotion. The dedicated workflow calls the existing complete
certification with preserved inputs, all four native suites, supervisor, crash,
restart, accounting, integration and resource gates. It performs no provider
connectivity probes or market collection and cannot authorize a market run.
This implementation record is not a certification or profitability claim.

Candidate `d39e71f25b40cb1ccb1924b8f377aa86bef5f743` failed full workflow
`36264056375`: one missing Pons startup import and one PumpSwap account-map
capacity dispatch error. Meteora 452 and Ramses 357 tests passed; Pons ran 419
and Pump 372. Both affected regressions pass after repair. The next candidate
also preserves both directional namespaces and sleeve authorities in archives,
validates Survivor capture/replay, and recognizes only verified Survivor handoffs
through the existing continuation controls. No market workflow was launched.

Candidate `9f76d1d30d79f0215388e011146bca2266bc294b` passed all 1,601
native tests (Pump 373, Pons 419, Meteora 452, Ramses 357), 342 supervisor tests,
and regular CI. Workflow `36264525057` then found a direct crash-harness import
path missing the neutral helper root. The corrected harness passes the complete
20-boundary native SIGKILL matrix; all four runner restart probes also pass.
Strategy and composite policy hashes are unchanged by this harness repair.

Candidate `29e5671a68d603b124537d8cfbe9718c3e94fc0b`, workflow `36264890415`,
passed all 1,601 native and 342 supervisor tests, crash/restart/integration/resource
gates, six-regime integration, and the 91-test bounded preserved pass. The final
aggregate found that Git's automatically longer diff object abbreviations changed
the historical Meteora receipt hash. Source bytes, journals, economics and balances
were identical to the immutable original proof. Pinning its original seven-character
diff presentation reproduces the exact original receipt; no historical registry,
strategy, policy, cohort or acceptance threshold changes. A real temporary Git
repository regression covers configured abbreviation drift and content mutation.
