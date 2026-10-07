# Unvalidated Pons work preserved at the stop boundary

This branch, `engineering/pons-finalization-wip-preservation-20261007`, preserves
the ten outstanding files exactly as found when the owner stopped the investigation.
Its base is the verified implementation commit
`86bdcac4afb6cb6290f32f495d81489bb572ec65`, tree
`f03405080491ae47002bcfae9426814cb2b52e59`.
This is a preservation snapshot, not an accepted runtime revision or a proposal
to merge, deploy, start PAPER, or continue the investigation.

The experiments add a durable quiet-market Current watch, fair timer rechecks
using fresh canonical state, restart guard handling, explicit same-curve execution
dispositions, associated regressions, and partially updated lifecycle documentation.
The last cold-start nomination-priming change is unfinished and has no completed
targeted validation. No additional implementation was performed after the stop.

Pre-existing scratch reports record 57 focused and 435 Pons tests passing, and
553 FAST / 641 affected OPERATIONAL tests with the existing byte-guard failure.
Those reports were produced while edits were still occurring. They cannot certify
the exact preserved snapshot, particularly the final cold-start experiment.
The recorded failure identity is
`tests.test_robinhood_usd_valuation.RobinhoodUSDTests.test_strategy_sources_and_nine_change_tests_byte_unchanged`.
No broad suite was launched for this preservation task.

The changed lifecycle map and final report describe experiments; the verification
and changed-file manifests still describe the earlier accepted implementation.
Do not treat this branch's mixed artifacts as a consistent certification bundle.
The authoritative 424/424 Pons, 46/46 focused, and 26/26 shared-governor results
remain attached to commit `86bdcac4afb6cb6290f32f495d81489bb572ec65`.

Frozen policy sources were not edited in these outstanding changes. Provider
credentials, runtime databases, raw provider logs, and local temporary files are
excluded. Any later review must be a separate, explicitly bounded task; this
snapshot does not authorize repair work or a new warmup mechanism.
