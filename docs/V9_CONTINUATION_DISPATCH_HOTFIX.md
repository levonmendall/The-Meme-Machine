# Position continuation workflow registration

Baseline: `07ec67a2b7967fd3e97c056307967ce1738f6d20`.
Historical campaign: `36043064083` (unchanged).

The continuation workflow existed on the frozen runtime ref but had never been
registered with GitHub Actions. A read-only push job on the dedicated repair
branch now registers that same workflow path. Every position-executing job is
excluded from push events. This job neither checks out runtime code nor reads
providers, changes control state, or dispatches anything.

GitHub documents dispatch against another branch/tag after a workflow has run:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch

Registration is repository control-plane state. A future separately authorized
continuation of the historical position must still dispatch the ORIGINAL immutable
runtime ref/SHA, campaign run, and latest state run. Do not dispatch the hotfix SHA
against old native evidence: that would correctly fail implementation identity.
The existing claim/CAS, native state verification, policy and accounting remain
unchanged. Registration does not authorize recovery or consume the open position.

Focused verification: 40 tests pass, including the registration exclusion and
continuation claim boundary cases. The separate push wrapper calls the full
existing non-market certificate, including its established bounded connectivity
probes. No market campaign or real continuation is part of this repair.
