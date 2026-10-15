# Maintenance and bounded provider proof

This package finishes the existing pump_pons_proof executor and verifies the
three maintenance regressions. VALIDATION.json provides the final readiness
classification, frozen executable commit, source hashes, commands and receipts.
MAINTENANCE.md explains the fixture repair; ENFORCEMENT.json maps every published
contract leaf to its enforcement, measurement and regression. OWNER_AUTHORIZATION.md
contains the separate live invocation. No provider proof or deployment is
authorized or performed by this engineering package.

The published forward-Survivor contract remains byte-identical. The executor
rejects absent, duplicate, malformed, nonfinite, legacy or altered contracts.
Default import, description, CI and unsupervised child entrypoints cannot
dispatch. Offline mode uses deterministic local responses, no credentials,
an isolated network namespace and an independent kernel socket guard. Tests
also exercise alternate clients and SDK channels rather than relying on a
single urllib monkeypatch.

HTTP reservations atomically count JSON-RPC elements, physical HTTP attempts
and independently frozen method weights before dispatch. Native Subscribe and
WebSocket upgrades count physical attempts without adding RPC elements. The
3,000-CU token-largest contract override is separate from its 20-CU legacy
diagnostic. Unknown methods, endpoints, retry attempts, redirects and oversized
log ranges are refused. HTTP bodies are acquired in bounded chunks; full
per-response reservations prevent concurrent cumulative-byte races.

Native bytes are serialized Yellowstone messages and Solana WebSocket payloads,
including overlap, errors and shutdown delivery. TLS framing is excluded under
the existing transport model. SDK receive sizes/queues are bounded; possible
unobserved SDK tails are conservatively charged on cancellation and reported
separately from known delivered bytes. Admission stops one maximum frame before
the 256 MiB shutdown margin. These are modeled transport exposures, never
authenticated account billing. There is no EVM subscription workload.

The supervisor runs independently of application threads. Linux cgroup v2
contains descendants, including setsid escapes; CPU, memory and block-write
controls remain active if the application stalls. RSS is summed across all proof
processes, with the supervisor included. Forks reserve duplicated RSS before
dispatch because cgroup memory counts shared pages once. Trailing 30-second
CPU consumption includes exited descendants. Retained per-process dirty-page write counters, actual cumulative physical writes,
conservative pre-write reservations and current output stock are independent
measurements. A 16 MiB write margin covers bounded block-writeback, mapped tails
and the final receipt; aggregate SQLite shared maps are capped at 6 MiB. Missing
measurements fail closed. Kernel notifications refuse
writes outside disposable output, writable unaccountable maps and bypass
syscalls before execution; production databases and monetary state are never
opened by the workload. Original capital tests use only disposable fixture books.

Queue records come from actual owner admission, durable acquisition/history
enqueue/claim/completion, qualification decisions, native provider admission,
pacer waits and asyncio queue transitions. They preserve source deadlines,
tightening and cancellation. Native deadline-missed dispositions are retained
even between censuses. Backlog is timed continuously, with successful service
events and a running drain witness; shutdown cannot manufacture that witness.
Live Model B also retains the existing continuously sampled normal_drain proof.

The optimized Pump source and candidate paths and Pons native Current broker,
forward enrollment, targeted lineage and shared pool reads are retained. One
bounded disconnect uses native checkpoint resume and checks identity, original
clocks and nonregressing frontiers. The offline replay uses the original Pump
capture and clearly synthetic Pons tape, plus seven existing qualification,
Current canonical refresh and shared-capital fixtures. Captured identities and
source clocks are unchanged; unavailable intervals and unreplayed tails remain
incomplete. Paused-family capture sessions are excluded before fake acquisition.

The offline workload correctly reports INSUFFICIENT_SAMPLE for live capacity,
authentic native positions and newly mature Survivor qualification. An engineering
READY classification means the executable and its safety boundaries are validated;
it does not certify position maintenance, six-hour Pump/four-hour Pons maturity,
profitability, capacity, recovery acceptance or autonomous reliability. The
separate 3,600-second capacity and 129,600-second autonomy scopes remain unchanged.

Run the offline executor with the pinned CPython 3.12.14 environment:

    python -m engineering.solana_capacity.pump_pons_proof --offline --output /tmp/mm-proof-new

The output path must be fresh, local and disposable. Execution requires the
specified two-CPU/eight-GiB Linux host, delegated cpu/memory/io controllers,
libseccomp notification support, cgroup.kill and network-namespace privileges.
This host's io controller was enabled for engineering accounting; existing
production cgroup limits, services, state and epoch were untouched.

The final executable also includes the completed Pump bandwidth audit at
874e94a915900215993566822e8adc9ce9524a6b and Robinhood PAYG work at
73243cb0c135197359c23cce46d3a91a48d8b40a. Their worktrees were not changed.
The one merge conflict retained the current Pons incomplete-history assertion
and all thirteen new Pump bandwidth tests. No provider optimization was added
by this assignment. The final complete OPERATIONAL run tests this combined tree.

Final disposition: BLOCKED_BY_EXTERNAL_CONSTRAINT for the unfinished exact-tree
full OPERATIONAL verification, stopped at the owner's explicit finalization
instruction. The focused maintenance and offline safety validations pass; no
remaining engineering defect was demonstrated. This is not a green full-suite
or autonomous-readiness claim. VALIDATION.json preserves the partial receipt.
