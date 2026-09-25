# Pump immutable diagnosis and minimal repair

Source: accepted run `35949285193`, runtime `1c6da29d08bfbe42e39ea1c8068933aae6b15cdb`. Primary digest-verified review and native projection are under `evidence/accepted-review` and `evidence/native`. No historical artifact, cohort outcome, or admission classification was rewritten.

## Correct denominator and outcomes

The reported **1/25** compares one completed full vector with **25 distinct mints requesting decision-history evidence**, not 25 requests that had already passed the inexpensive gates and necessarily needed concentration evidence.

| Evidence layer | Episodes | Unique mints | Meaning |
|---|---:|---:|---|
| Current decision history requested | 500 | 25 | Every request remains in the denominator, including failures |
| Current decision window supported | 239 | 20 | 238 optimistic postgrad rejects plus one full-vector result |
| Current decision window incomplete | 261 | 22 | Actual missing required decision evidence; not excused by another earlier/later rejection |
| Full vector known to require concentration | 1 | 1 | Passed the optimistic qualification gates |
| Full vector completed | 1 | 1 | Rejected for concentration 9,785 bps; no trade |
| Valid optimistic preflight rejection | 385 | 20 | 238 postgrad plus 147 second-leg decisions; no holder scan needed for these states |
| Second-leg history incomplete | 81 | 14 | A separate reconstruction need after a complete current window |
| Complete history with no pullback shape | 4 | 2 | Valid structural/strategy rejection, not missing history |

The 22 current-window and 14 second-leg failure sets overlap on 11 mints: **all 25 requested mints experienced at least one genuinely incomplete decision state**. Twenty eventually supported at least one valid decision. Nineteen had only early rejection results; one produced the full concentration rejection. Five never reached any supported decision and subsequently expired. This does not imply 20/25 entire candidate lifetimes had uninterrupted evidence.

At observation close `1790223797`, three requested mints remained within their candidate horizon. Two had prior supported decisions; one (`EvaWRi4m1NxgU2ZpxQz8UGYQTpAYtFUMqfb4YztDFuoP`) had only failed windows. The frozen campaign stops new evaluations at observation close, then its tail expires candidates. All five never-evaluated requested mints ultimately expired by final report `1790224797`. The repair does not change this runtime boundary or infer successful reconstruction from expiry.

## Incomplete taxonomy and root causes

The old generic reason classifier recorded **537 reconstruction-class rows / 55 identities**. Exact decomposition:

| Recorded reason | Episodes | Mints | Correct interpretation |
|---|---:|---:|---|
| `insufficient_curve_trajectory` | 159 | 25 | Pre-admission prospect evidence incomplete. No full-evidence request was admitted in late-curve mode. Do not invent success, a strategy rejection, or a full-reconstruction failure from this stage |
| `incomplete_pumpswap_decision_window` | 261 | 22 | Required current decision evidence failed |
| `incomplete_pumpswap_second_leg_history` | 81 | 14 | Required second-leg reconstruction failed |
| `missing_pullback` | 4 | 2 | Complete authenticated history contained no qualifying pullback; valid earlier rejection |
| `postgrad_entry_horizon_expired` | 32 | 32 | Candidate state expired normally. Seven never requested evidence. Keep all earlier missing-evidence events intact |

The genuine incomplete categories therefore total **342 episodes across 25 mints**, with per-mode overlaps retained. Separately, **459 valid stream prospect rejections across 53 mints** never authorized late-curve HTTP/full reconstruction. The 159 prospect-incomplete episodes are retained as their own unknown/pre-admission bucket, not relabeled successful rejection.

Among 261 current-window failures:

- 249 had zero pending known signatures but still lacked stream transaction bodies.
- 12 had unresolved known signatures; three also had unresolved stream signatures.
- Every failure had zero unknown historical block timestamps.
- 228 had a covered broker stream, while 33 were during a stream warmup/reconnect boundary. `stream_complete` in history also depends on body hydration, so it must not be read as websocket connectivity alone.

The immutable stream attribution reports 63,000 unique Pump-window signatures with expired consumers; 62,127 unique signatures expired before transport. This is real acquisition pressure under the frozen request budgets/capacity, not multiplying repeated identical consumers. Existing negative-only log screening excluded 7,213 pool/signature pairs. The primary archive retains 183,161 pool notifications, 116,337 with possible PumpSwap activity, 66,824 with complete logs excluding PumpSwap, and only six default-signature notifications. Missing bodies cannot safely be fabricated, inferred negative, or discarded merely to improve completion.

Checked all seven failure observations with a warm/complete stream, no pending stream body, but unresolved known signatures against the immutable Pump/Meteora raw RPC timeline. Missing bodies were still unavailable before their original decision deadline; one sample's eight responses were logged immediately before the limit but the broker recorded `post_transport_late_result` at `1790220250.8913605` against deadline `1790220250.8863878`. No observed ignored-timely-cache defect was proved, so no speculative cache or scheduler repair was made.

## Stream continuity

Pump's finalized discovery tape records eight real reconnect gaps, zero parse failures, zero tape-capacity losses, and zero creation-capacity losses. PumpSwap records six reconnects across seven connections. Final `connected=false` is emitted after intentional shutdown; Pump's last `loss_until=1790223430` was already past by observation close, and its final uninterrupted warm duration was 1,424 seconds. Cumulative gaps remain real historical interruption evidence, but final shutdown is not a new provider failure. Existing fail-closed warmup remained active. Available artifacts do not prove that every event during those physical disconnects was recovered, nor demonstrate a safe missing-body acquisition repair within frozen evidence and capacity rules.

## Implemented minimal changes

Owned runtime file: `tests/pump_acceleration_natural_prospective.py`.

- Record pre-admission missing trajectory as `pre_admission_evidence_incomplete`.
- Record normal candidate-horizon expiry as `superseded_candidate_state`; earlier genuine failures remain append-only.
- Record authenticated complete-history/no-shape outcomes as strategy rejection only when the attached history explicitly has `complete=true`.
- Record actual optimistic/full qualification rejections as strategy rejection.
- Record `decision_evidence_requested`, `decision_evidence_complete`, `evidence_required`, `full_evidence_requested`, and `evidence_not_required` separately, with mode/time/reason facts. A full requirement is recorded before the existing late-curve attempt cap; actual request is recorded only before the holder read.
- Full-vector completion is never fabricated from a valid rejection. A valid rejection at one state cannot erase another state's failure.

The parent owns the dynamic `Pipeline.snapshot` stage/class exposure and shared assurance aggregation. No policy, acquisition, stream reconnect, persistence, or execution lifecycle implementation was changed in this Pump patch.

## Verification

- New `tests/test_pump_evidence_classification.py`: four meaningful regression tests covering pre-admission attribution, expiry preserving prior failure, complete-history shape rejection, and valid preflight rejection followed by a later failure of the same mint.
- Focused/affected history, natural harness, lifecycle, tail drain, campaign and classification suites: **34 tests passed**.
- Entire prepared Pump lane offline suite: **320 tests passed** (including unchanged qualification, staged realization/runner, fill persistence, monitoring, settlement and accounting regressions).
- Synthetic resource check: **passed**, 2,000 frames / 240,000 submitted events, peak RSS 18,656 KiB, zero real provider calls. This is a bounded synthetic resource proof, not market evidence.
- No new market run, provider request, cancellation, push, or external write was performed by this worker.

Strategy economics unchanged: yes. Target scope unchanged: yes. Provider limits unchanged: yes. Evidence requirements unchanged: yes. Accounting semantics unchanged: yes. Paper-only unchanged: yes.

Pump justified classification repairs are implemented and locally verified. Genuine missing evidence under the frozen capacity remains explicitly reported; these changes do **not** claim the evidence-completion problem is solved, natural profitability, or that all lost stream events were recovered. No preventable Pump acquisition defect was established beyond the classification issues from this accepted dataset.

## Per-requested-mint trace

Window/history failures are episodes. Outcomes summarize any supported decision and never cancel earlier/later losses.

| Mint | History requests | Window failures | Second-leg history failures | Supported outcome |
|---|---:|---:|---:|---|
| `2bG3H9xUvvrrURQ5DbD6z2TYixswAXzjqRUG8LGMpump` | 16 | 13 | 0 | valid optimistic rejection |
| `2zXLR6BXB8GuXLkNkF7XAFX6LEika1G4mBwgktwWy7yy` | 16 | 14 | 2 | valid optimistic rejection |
| `3whmkC3YdkMGXKxtk43AGQRiB2qrkbP9T6KrPz9spump` | 23 | 3 | 11 | valid optimistic rejection |
| `4aA7C3X5RdV1d8vri6N76hXLhK1f5vCN2sNb3mAJhg63` | 17 | 17 | 0 | no supported decision; expired |
| `5yRMyd99UjtQJX7MKkH97AmBjVQVQMqEUxDezewfpump` | 19 | 0 | 4 | valid optimistic rejection |
| `6CEdJHjtNkU4FE8rx46DVViFcmYBGXa65vv7pkGhpump` | 36 | 25 | 0 | valid optimistic rejection |
| `7g1KqzPuPXW972HWxgSNCYkunjes86pckhg6WxiYpump` | 18 | 11 | 0 | valid optimistic rejection |
| `891mada1XAi4ma6os8MpTM2NPQBopwiuX971SZinpump` | 20 | 1 | 15 | full vector; concentration rejection |
| `8nEqXVqEKNfyHrV3kaSSBgTpyzMDGgpL35CGZ9d3pump` | 17 | 2 | 0 | valid optimistic rejection |
| `8xkvAYMZGLR8HDXCzCoafo3SLSQaiBd6RGhyE5qUpump` | 21 | 15 | 1 | valid optimistic rejection |
| `95bdhn7cRPffFYJ7sKrifHw8PNNtofJNTzhppDxMpump` | 17 | 0 | 2 | valid optimistic rejection |
| `CC45Y5yE7gLvGtqhPGPL73aKcpcwcmLgT5KJkfW4pump` | 31 | 20 | 0 | valid optimistic rejection |
| `CdZasTVby3LChoMqhqX3SYZe6U43KB2J8RUGZmkPmNE9` | 19 | 15 | 4 | valid optimistic rejection |
| `EvaWRi4m1NxgU2ZpxQz8UGYQTpAYtFUMqfb4YztDFuoP` | 6 | 6 | 0 | no supported decision; expired |
| `FYJM1qz9zT9yCVEVJpzqWSCMHZcUiWQCSfcU8PYypump` | 20 | 0 | 3 | valid optimistic rejection |
| `FnEQ3N4E1VMh2GeBj69cU4LfaYxjsktrAD9jKexwpump` | 18 | 13 | 0 | valid optimistic rejection |
| `GC6t9umfTUpibSRdtwtKy6MX1XEZjUUr3LVUUdTLYCuq` | 15 | 15 | 0 | no supported decision; expired |
| `GFKg5wMi5GJowq1qhAzopejnPaqxcoLgVCrjGM4fpump` | 20 | 20 | 0 | no supported decision; expired |
| `GWi9k566WBsGawVky9XoVpCFWb3t5gADjexQm5yE5YCV` | 29 | 29 | 0 | no supported decision; expired |
| `HsM7uGQsw2FVBRKaGHbnh9EgFqiXHu6sNnfG7QAkpump` | 21 | 1 | 7 | valid optimistic rejection |
| `JrUzdNLYM2PLtCSo9j9q7pr1WuG13wikfgRSgm6pump` | 23 | 2 | 2 | valid optimistic rejection |
| `Vyz6M65DuBSghKBaGwKGtpDAmWTLM1J1dgY1XoMpump` | 17 | 1 | 15 | valid optimistic rejection |
| `cotZeLVbgYKcZo3t2kfaW7VMnG2xbSTdkNGRmfvpump` | 24 | 19 | 1 | valid optimistic rejection |
| `fKoq1tcLRDn5WKzDkLqPmkUfHGLDS1nbfeSraJ5pump` | 17 | 1 | 12 | valid optimistic rejection |
| `fdLgyBb3qPCAt91oXCPER8xcRvxVXbokbBsvWNKpump` | 20 | 18 | 2 | valid optimistic rejection |
