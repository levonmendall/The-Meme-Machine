# Certify changes, preflight runs

The PAPER market workflow uses a two-level safety model.

1. **Certification is change-driven.** Runtime, strategy, provider, lifecycle, accounting, and control-policy changes require deterministic validation appropriate to the changed surface. A composed runtime receives one full exact-SHA non-market certificate before it is eligible for market admission.
2. **Market launches are preflight-driven.** An unchanged certified runtime reuses that certificate. Launch checks re-verify the exact runtime ref/SHA, certificate artifact and fingerprint, prepared source hashes, one-shot owner authority, absence of competing market work, chain binding, endpoint capabilities, and PAPER-only controls. They do not rerun the full four-lane deterministic suite.
3. **Owner authorization is external to the certified runtime.** The reusable runtime stores only the static single-campaign policy. A fresh `authorization_id` is carried on `launch/certified-runtime-authority-v2` by the launch request and consumed into append-only state before the single workflow dispatch. Issuing another PAPER authorization therefore does not mutate the certified runtime SHA.
4. **Durable position continuations inherit the consumed authorization.** They may manage only the already-open Meteora/Ramses position and cannot create a replacement discovery campaign.
5. **Certification fingerprints are auditable.** Runtime identity includes the exact SHA, executable Git-tree hash, implementation hash, protocol hash, source-manifest/diff hashes, lane strategy/policy identities, and execution-configuration hash. Full-certificate receipts also carry a deterministic fingerprint. Ephemeral authorization IDs are intentionally excluded from the runtime fingerprint.

Full recertification remains mandatory after a material runtime change. A one-shot authorization refresh, prior-run narrative, launch request, or other non-runtime control-plane metadata must not create a new runtime SHA merely to authorize another PAPER observation.

## Enforced validation tiers

- `targeted-repair-validation.yml` is the bounded development gate for one affected lane or the control plane. Its artifact explicitly declares `market_certificate: false`.
- The final composed runtime still receives one full `non-market-certification.yml` certificate before any new runtime SHA can be admitted to a market workflow.
- A `[single-market-launch]` request-only commit is permitted to change only `.github/single-campaign-launch-request.json`; generic runtime tests are skipped for that commit because the exact certified runtime SHA is unchanged.
