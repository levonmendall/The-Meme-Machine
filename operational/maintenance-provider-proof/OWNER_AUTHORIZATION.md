# Separate authorization for the 300-second technical proof

This command has **not been run**. No real provider request was made by this
assignment. Authorization remains NOT_GRANTED in the unchanged published
contract. The package is not classified READY because the exact-tree full OPERATIONAL
verification was stopped at the owner's finalization instruction;
live capacity, recovery acceptance and autonomy remain separate decisions.

Review and test executable commit
`9c6910c57236004468bef506603c2d0502acbd3c`. The final engineering branch adds
receipts as a documentation-only descendant. Run from a clean checkout of the
executable commit, with no untracked modifications. Source identity and contract
SHA are checked before authorized dispatch. Ordinary import, description,
`--execute` without the authorization flag, CI, and a standalone `--child`
invocation cannot open providers.

The original bounded handoff command is preserved below. It remains unrun and
is not a recommendation to bypass the unverified full-suite requirement. After
separate owner authorization, the exact invocation on this host is:

```sh
/root/Documents/Codex/2026-10-08/the-meme-machine-robinhood-scout-first/.venv/bin/python -m engineering.solana_capacity.pump_pons_proof --execute --authorized-live-proof --source-commit 9c6910c57236004468bef506603c2d0502acbd3c --contract operational/forward-survivor/NEXT_PROOF.json --env /var/tmp/mm-provider-proof-read-only.env --output /var/tmp/mm-proof-300-authorized
```

The output directory must not already exist. The explicit credential file must
supply only the required read transport values below; no signing key or monetary
book configuration is inherited by the worker. Do not put actual secrets in the
authorization package, command line, version control or receipts.

* `MM_SOLANA_READ_RPC_URL`: Solana Alchemy HTTPS `/v2/<key>`.
* `MM_SOLANA_YELLOWSTONE_TOKEN`: the existing Yellowstone read token.
* `MM_ROBINHOOD_READ_RPC_URL`: Robinhood Alchemy HTTPS `/v2/<key>`.

Host requirements are two dedicated vCPUs, 8 GiB RAM, at least 2 GiB available
system memory, pinned CPython 3.12.14 and repository-pinned dependencies. The
executor requires Linux x86_64, delegated cgroup v2 cpu/memory/io controllers,
cgroup.kill, block I/O accounting for the local output filesystem, seccomp
notification support, subreaper and network-namespace privileges. Use the
existing privileged engineering environment. Direct TLS must be reachable;
HTTP proxies and redirects are deliberately not used. Unavailable enforcement
is a preflight failure, never assumed compliance. CI execution is refused.

Approved provider endpoints are Solana Alchemy HTTPS and Solana WSS at `solana-mainnet.streaming.alchemy.com/v2/<key>`, Yellowstone
at `solana-mainnet.streaming.alchemy.com:443`, Robinhood Alchemy HTTPS, and the existing
read-only public Robinhood HTTPS fallback at
`rpc.mainnet.chain.robinhood.com:443`. All endpoint families and method lists
are validated before dispatch. There is zero EVM subscription workload.

| Maximum resource exposure | Hard contract ceiling |
| --- | ---: |
| RPC method elements | 7,200 total: Solana 6,000; Robinhood 1,200 |
| Physical HTTP/subscription-opening attempts | 7,200; a batch is one attempt |
| Published modeled RPC CU | 720,000 |
| Legacy diagnostic RPC CU | 720,000 |
| Diagnostic native CU | 4,194,304 |
| Combined diagnostic CU | 4,914,304 |
| Actual plus conservatively reserved native delivery | 2 GiB |
| HTTP response payload | 128 MiB cumulative; 2,000,000 bytes per response |
| Robinhood log range / RPC retries | 10 inclusive blocks / zero |
| Native in-flight shutdown reserve | 256 MiB |
| Proof group RSS, including supervisor and descendants | 4 GiB |
| CPU over each trailing 30-second interval | 1.8 cores average |
| Available system memory | At least 2 GiB |
| Cumulative process writes / output storage stock | 2 GiB / 768 MiB |
| Queue capacity / sustained stop | 64 / depth 32 for 5 seconds |
| Position / consecutive candidate deadline violations | Zero / stop at two |

If all 2 GiB native bytes were Solana WS payload, the published model bound is
429,496.7296 CU; if all were Yellowstone payload, it is USD 0.1610612736 at the
contract's decimal-byte tariff. Mixed transport bytes share one cap. Modeled
CU and diagnostic CU are separate ledgers, not actual authenticated billed
consumption. Provider-reported billing remains unknown unless supplied by the
provider. There is no paid upgrade or capacity extension.

Some admission guards stop earlier to leave bounded cleanup space: 128 MiB RSS
for the supervisor, a 16 MiB cumulative-write margin, 2 MiB output receipt
reserve, a 6 MiB aggregate SQLite shared-map bound, and one maximum native frame
in addition to the 256 MiB native reserve. Kernel CPU admission is 1.75 cores
for the worker group; measured total CPU includes the supervisor. These guards
strengthen the published ceilings and are disclosed in the receipts.

The entire invocation, including preflight, has a monotonic 300-second deadline.
Startup must complete within 60 seconds. Steady observation must last at least
180 seconds. No new provider/scheduler work is admitted at or after second270.
Shutdown has the remaining 30 seconds, propagates stop/cancellation to every
worker, and charges delivered/in-flight data. Escalation at shutdown+20 is FAIL;
the watchdog kills the process session and cgroup, including setsid descendants,
by shutdown+30 and the absolute deadline. All joins/reaping are bounded. Forced
termination cannot PASS. Receipts are written within their reserve when safely
possible; a missing final receipt is never PASS.

The workload uses the optimized Model B source, Pump/PumpSwap candidate and
economic acquisition, Pons forward enrollment/Current/scoped Survivor histories,
canonical lineage and shared pools, seven original qualification/capital
fixtures in disposable state, and one bounded native disconnect/checkpoint
resume. Every runtime database is new and isolated under the output path.
Production databases are not opened. The original PAPER epoch
`paper-1791089005190643467`, $500 capital, all four strategies, nine approved
strategy changes and paused Meteora/Ramses state are preserved. No production
service restart, deployment, PAPER trade or live monetary book is authorized.

Expected output includes `process.json`, `ceilings.json`, `worker.log`,
`capital-fixtures.log`, native Pump result/reconciliation/owner observations,
Pons observations, and disposable `state/`, `candidate.sqlite`, provider and
evidence databases. Offline receipts use `pump-replay/` for original recorded
delivery evidence. The original source clocks, identities and incomplete
intervals are preserved.

* **FAIL:** a ceiling, invalid/unavailable measurement, deadline violation,
  workload/reconciliation error, forced kill, incomplete shutdown, short
  observation, missing recovery exercise, or invalid receipt. Stop without an
  extension or retry. Preflight inability to start is **BLOCKED**.
* **INSUFFICIENT_SAMPLE:** bounded execution succeeds but authentic native
  positions, mature complete Survivor candidates, or a normal-service drainage
  witness are absent. Recorded/synthetic offline samples cannot certify live
  capacity. The supplied package has no authentic native position evidence;
  the current invocation therefore reports this limitation honestly.
* **PASS:** all applicable technical observations, checkpoint recovery and
  sustained service/drainage are evidenced, startup/steady/shutdown timing is
  valid, every measured ceiling holds, no worker survives, and no required
  sample is missing. PASS never means actual profitability, mature newly
  discovered six-hour Pump/four-hour Pons qualification, production position
  deadlines without native positions, or autonomous operational readiness.

The separate live proof and subsequent CAPACITY, RECOVERY and AUTONOMY
acceptance remain unperformed. No real provider calls have yet been made.
