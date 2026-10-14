# PAPER opportunity access v1

This candidate implements the owner's six selected PAPER policy changes. They
are starting policy choices, not demonstrated profitability improvements. The
active default is `paper-opportunity-access-v1`; it is not a shadow policy and
does not create a portfolio epoch. Deployment and market observation are
separate from publication.

The implementation and source-guard base is
`a048ee8cbeb87bff9c589a0b6f587fd909c23ed5`. The reviewed
`2fa0b59fa8038275676e72fb3c1e7f9380f7724d` is its ancestor. This base includes
the Pons pacing/HTTP context and SQLite attribution repairs, diagnostic access
repair, Pump history separation, and the prior lifecycle/reporting package.
The existing integration checkout and other worktrees were preserved.

Before publication, this branch fast-forwarded to completed integration commit
`ddcee53eb2498b7281820793408abbea71f2e88a`. Its three changes contain only the
replacement-observation result, evidence and safe-pause handoff; the tested
application source is unchanged. The implementation commit is
`5f94eb0b7c286ec2d763ab274784ebbb89b2baaa`, published on the owned branch
`policy/paper-opportunity-access-v1-20261014` through the normal non-force,
non-deploying workflow. A subsequent documentation/evidence commit contains
this register. The integration owner remains
`engineering/targeted-resolution-20261014`.

## Required change register

All rows below select the same active revision through native policy defaults,
the central `paper_policy_revision` registry, supervisor child environment and
the source `paper-continuous.conf` profile. The policy snapshot at
`meme_machine/policy_history/pre_opportunity_access_v1.json` preserves the four
preceding policies and their exact hashes. Historical decisions retain their
original policy identity. Implementation is intended for the next separately
authorized PAPER release; none of these rows denotes deployment.

| Item | Source and actual caller integration | Former and revised behavior | Focused checks |
| --- | --- | --- | --- |
| C1 | `pons_selective_continuation.py`: qualification, entry persistence, ongoing requalification; `pons_selective_acquisition.py`: prospect/trajectory filters; native `pons_selective_paper.py` fill/add consumers | Both curve and flow acceleration required → both flags false, measured optional context. Positive net demand, core progress/ETA where applicable, buyers, concentration, freshness and execution remain gates. | Selective continuation, market-scope, entry ordering and ongoing-scale fixtures; otherwise-qualified slowing admits, unsafe demand/progress still rejects. |
| C2 | `pump_acceleration_strategy.py`: `qualify`, prospect and `entry_signal_persistence`; `runner.py`: native reservation/fill/add callers | Repeat count and share independently reject late-curve entry → confirmation/ranking only, including missing optional diagnostics. Other modes and buyer/growth/imbalance/concentration/trajectory/execution requirements remain. | Pump opportunity-access and acceleration fixtures exercise qualification, prospect, native fill and retained rejection cases. |
| C3 Pump | `pumpswap_survivor.py` and `pumpswap_survivor_runtime.py`: native history reconstruction, preview and fresh commit | Unconditional six-hour witness → explicit window `min(age,21600)`, starting at `now-effective`, with authenticated boundary witness and continuous coverage. Initial eligibility remains inclusive four hours–seven days. | Native four-to-six-hour windows, missing witness/gap, entry-age boundaries, funded commit and restart. |
| C3 Pons | `pons_postgrad_survivor.py` and `pons_survivor_runtime.py`: medium/short/long windows and native graduation coverage | Arbitrary loaded rows could masquerade as a six-hour interval → nominal, effective, covered duration and completeness explicit, genuine graduation/boundary witness required. Existing 24-hour long-trend threshold is not rescaled. | Four-hour forward admission, honest duration metadata, insufficient history and age boundaries. |
| C4 | `pumpswap_survivor.py`: policy, completed-base evaluation and reset reducer; `survivor_history.py`: existing derived checkpoint transition | Reset 1800→300 bps; base compression 6000→10000 bps. Original peak→retracement→completed base→breakout order, base durations, reset low and extension/safety limits remain. | Exact 3% reset/equal ranges, invalid ordering, broken reset low, expanding base, no breakout, old prefix recovery and retired detail unavailable. |
| C5 | `pons_postgrad_survivor.py`: evaluate entry; native Survivor preview, fresh fill and approved add requalification | Gross buying increase ≥10% independently vetoes → `no_demand_acceleration` optional context. Ratio1.25, population/newcomers, creator/concentration, trend/structure and execution remain. | Sustained/slowing demand qualifies through native admission; unsafe demand/concentration still reject; missing optional prior buy is unavailable. |
| C6A | `pons_selective_continuation.py`: `pregraduation_action`; `pons_selective_paper.py`: actual controller and continuation facts | Confirmed positive progressing demand slowing alone liquidates → hold/manage with old-predicate context. Confirmed nonpositive demand or nonprogressing curve retains its existing authority, as do risk/structural protections and committed exits. | Native pregraduation replay/restart and helper fixtures: soft-only holds, retained hard/nonpositive/nonprogressing conditions act. |
| C6B | `pons_selective_continuation.py`: `runner_action`; native Current controller and bridged continuation facts | Confirmed stale high/nonexpanding lifetime-new breadth alone liquidates → hold/manage. Separate adverse flow, hard stop, realization, ordinary trail and 40%-of-gain tail remain. | Runner soft-only and adverse-flow/hard-stop/trail fixtures; native bridge continuation, committed exit and restart preservation. |

The shared opportunity receipts label demoted measurements as nonblocking
confirmation/context and preserve unavailable values. They record exact
decision policy, former predicate failures, and newly qualified decisions where
that comparison is supported. Pump's changed reset reducer may select a
different historical cycle: its former-threshold context is explicitly limited
to the selected setup, not a complete prior-policy decision or trading return.

## Conforming access and compatibility corrections

Fresh entry age is separate from ongoing requalification of an actually open
position. A pending/cancelled entry cannot use that exemption. Pump postgrad
Current and both Survivors keep retained quality/execution/add requirements
while healthy held winners do not acquire an initial-entry upper-age deadline.

Pump Current's historical mint/mode qualifier-count veto was duplicated in
`runner.py::_reserve_position` and the three nomination loops in `main`. Its
native policy defines no post-trade
reset predicate. A verified never-filled cancellation or genuinely filled and
closed trade can therefore be reconsidered after exact native terminal and
sleeve/portfolio release proof, strictly newer canonical evidence, complete
qualification and unchanged funding/execution checks. Active or unresolved
attempts block. The existing checkpoint retains a compact latest-attempt
frontier through normal retirement/restart; no timestamp is renewed and no retry
loop is added. Pons Current's earlier genuinely filled reset reference and both
Survivors' actual reset predicates are unchanged.

Pump postgrad continuation previously wired optional creator launch-history
quality to present distribution safety. It now uses the already measured
early-holder sell share and its unchanged native distribution ceiling. Missing
pregraduation distribution evidence remains explicitly unavailable; it is not
invented from creator-history quality.

Current and Survivor discovery/qualification remain independent. Existing
per-candidate readiness does not wait for a complete market-wide seven-day
census. Existing bounded sizing uses executable ordinary and exact double-size
stress probes; capital or capacity failure is reported independently of a
strategy rejection. No obsolete Pons Survivor position-count cap is activated.

The bounded discovery-to-re-entry pass has the following disposition; it does
not authorize further economic changes.

| Section 8 | Correction or retained working path |
| --- | --- |
| A: hidden gates | Removed C1/C2/C5 vetoes from prospect, fill and ongoing checks; optional acceleration/repeat diagnostics and C6 warnings cannot reject or retire a candidate. The native Current bridge uses retained adverse-flow proof. |
| B: history timing | C3 uses a complete explicitly bounded maturity-aware interval. Candidate completeness remains independent of a market-wide census. Gaps and missing boundary witnesses block. |
| C: independent later eligibility | Existing separate Current/Survivor evaluation and recovery are retained and checked; no shared permanent token blacklist is added. |
| D/E: attempts/count exclusions | Pump's duplicated historical mint/mode count veto is removed using verified terminal-attempt checkpoints and original canonical fences. Pons zero-fill/earlier-filled-reference handling and the already removed Survivor cap remain intact. Unresolved exposure and real resource/capital limits still block or defer. |
| F: nominal target infeasible | Existing bounded native downsizing remains authoritative. Funded fixtures exercise a smaller permitted size and the exact double-size stress quote; no dust, quote fabrication or target-size change. |
| G: initial age on held winners | `qualification_purpose='ongoing'` and Pons `qualification_scope='existing_position_add'` apply only to native OPEN positions. Entry-age ceilings do not become holding/add deadlines. Size/count/economics of the one add remain. |
| H: different measurements | Pump continuation uses actual early-holder selling instead of creator-history quality. Pons records gross-buy acceleration, net-flow change, total population and lifetime-new participation separately; required current newcomer evidence remains required. |

Previous/current policy hashes are recognized only where exact historical
recovery joins require them. New decisions use the revised identity. Existing
financial genesis, shared capital contracts, source/accounting identities,
balances and journal events remain unchanged. Shared funding retains its
original financial policy binding and separately records the effective decision
policy in existing request evidence.

The existing $1,000 PAPER epoch and historical $500 accounting are preserved.
Disposable fixtures verify all four revised native regimes can use the original
shared contracts without changing epoch, old financial policy hashes or totals.

The transition uses existing native/sleeve/history/controller checkpoints. It
requires replay-verified terminal rows and all shared reservations, positions,
commitments, obligations and pending delivery work clear before changing the
selection. A verified revised checkpoint permits restart of positions opened
under this revision. Old-policy open or unresolved positions cause an explicit
transition error; their governing policy and pending actions are not changed.

Pump reset-derived state is recomputed from original raw evidence. Original
policy/decision/prefix records survive. If a retired predecessor prefix lacks
the raw information needed for the new threshold, qualification reports
`reset_history_revision_detail_unavailable`; no backfill, invented reference or
old-threshold summary is treated as new-policy proof.

## Retained restrictions and operating scope

The four strategies remain distinct. Hard stops, realization amounts, add size
and count, trails/right-tail formula, creator/distribution, liquidity,
concentration, ordinary/stress execution limits, capital/reservations,
fresh canonical evidence, generation fences and Current/Survivor protection
deadlines remain. The genuine filled-trade reset predicate and its dimensions,
thresholds and elapsed-time requirement remain. Volume-quality labels keep
their attention-only authority. Meteora and Ramses remain paused.
Pons Current's five-second and Survivor's three-second protection deadlines are
unchanged; no quote suppression is introduced.

No strategy study, backtest, parameter search, simulated no-add engine, provider
feed, routing change, new scheduler, money, signing/submission or certification
machinery was added. Allowing healthy consolidation deliberately permits more
giveback before a retained exit acts.

## Actual software validation

Pinned CPython3.12.14/SQLite3.45.1 ran the existing network-blocked
`operational.tests OPERATIONAL` driver in disposable Scratch. Tests were
serialized; launch checks found no competing local test/profile worker. These
overlapping selections are not a sum of unique cases.

| Check | Actual result |
| --- | --- |
| First compact affected-path selection, 37 modules | 544 tests in301.392s: 537 passed, five failures and two errors. The failed log and Scratch `/tmp/mm-engineering-siy0xjy1` are retained. |
| Only invalidated dependencies plus added native retirement/restart tests | 224 tests in63.178s, PASS with zero failures/errors. Includes four funded native financial-contract fixtures, policy transitions, old filled-reference recovery, native fill/add, repeated canonical evidence, protective precedence and prefix retirement. |
| Existing strategy source audit | PASS: only approved policy deltas; 44 Ramses economic modules unchanged; owner admission scheduler byte-identical to its engineering base. |
| Exact revision source guard and final parse/whitespace | Unapproved byte/AST mutations reject. All53 changed Python files parse; `git diff --check` passes. |

The initial failures exposed an incomplete new history fixture, synthetic Pons
price-unit mismatches, missing retained adverse-flow facts in two add fixtures,
an overly restrictive terminal-policy compatibility check, and a predecessor
source pin that had not incorporated this explicitly authorized revision.
Fixtures now supply authentic required inputs; terminal compatibility accepts
the exact selected identity and only known historical identities; predecessor
assertions remain behind the exact reviewed delta manifest. No assertion was
weakened. The 224-case successor covers all seven failed/error cases and the
dependencies changed by those fixes. Other initial passing paths were not
repeated without a dependency reason. No uninterrupted final full release-suite
PASS is claimed.

[The validation receipt](evidence/paper-opportunity-access-validation-20261014.json)
contains exact commands, selections, active hashes, the complete56-file source
change inventory, preserved operating-state checks and SHA256 evidence hashes.
Its small [initial log](evidence/paper-opportunity-access-initial.log.gz),
[successor log](evidence/paper-opportunity-access-corrections.log.gz) and
[source audit](evidence/paper-opportunity-access-source-audit.json) are published
with the candidate. Existing required release checks still apply to the final
combined release; these fixtures establish implementation behavior only.

## Activation handoff

This task made no operating-state changes. At the17:45UTC read-only check,
installed source remained clean
`a70e2610743d8595b3d1a36ed25821a6689c29f3`, with PAPER inactive/dead,
MainPID0 and disabled. Funding remains closed under the latest
[safe-pause handoff](SAFE_PAUSE_RESUME_HANDOFF.md). The separately authorized
[replacement observation](REPLACEMENT_OBSERVATION_RESULT_20261014.md) ended
RECOVERY_REQUIRED with a failed native Pump drain; its authorization is
consumed. This publication provides no restart authority and no readiness or
acceptance credit. Do not assume its retained flat receipt is current.

The integration checkout now also contains ongoing independent provider,
diagnostic and cancellation repairs. This task left them untouched, including
overlapping `runner.py`, `supervisor.py` and `operational/tests.py` edits. The
owner must combine that work with this separate candidate and validate affected
dependencies; no release from an older source is proposed. Pump recovery/drain,
sustained capacity, original SQLite failure, Pons provider suitability/READONLY
failure, and backup/protection issues remain independently owned operating
blockers. These policy changes claim none repaired.

Before separately authorized installation, the integration owner must reconcile
fresh positions, reservations, delivery/capital ACKs and native policy selection.
If an old-policy position or obligation remains, preserve its original rules
and complete the existing handling before this flat-boundary transition; do not
overwrite journals, reset capital, or switch it to revised rules. Recompute only
the affected derived state in the existing stores. Incorporate newer independent
engineering fixes through the existing integration workflow and verify the
final selected source/configuration. Do not use a different strategy workload
to claim a processing-performance comparison.

Retired detail is a specific evidence limit: an old Pump reset prefix without
the necessary raw path cannot qualify under C4 by relabeling its18% summary;
an old retired attempt without original native quantity/cost proof cannot be
classified for retry. Both remain explicitly unavailable rather than acquiring
provider data or inventing a reference. No additional numerical economic
proposal is left pending by this implementation.

Use applicable existing release checks and separately authorized observation.
The original uninterrupted one-hour PAPER acceptance definition remains; offline
fixtures, diagnostic minutes and fabricated trades supply no acceptance credit.
Return operational focus to that existing objective after this candidate is
integrated.
