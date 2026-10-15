# Reproduce the GitHub release on AWS Lightsail

This is a software installation and recovery runbook for the owner-selected
Ubuntu 24.04.4 LTS, **x86_64**, four-vCPU, 8 GB RAM, 320 GB SSD Lightsail host in
Oregon. It does not provision AWS, migrate state, start PAPER, or establish market
capacity or profitability. The source comes entirely from GitHub. DigitalOcean
remains the preserved rollback/state reference until authenticated migration is
independently verified; it is not a package, build, or runtime-source dependency.

Keep the existing $1,000 shared PAPER epoch, historical $500 accounting, pending
evidence, original ACKs, source-session identities, deadlines, and recovery
obligations. Never initialize/reseed a portfolio as an installation shortcut.
Meteora and Ramses remain paused. Do not provide wallet/signing keys or enable
real-money trading.

## 1. Freeze and retrieve the exact release

Use the final verified **main commit and tree from the release report**, not a
development branch, PR merge into an intermediate target, or this document's
creation date. Supply the two 40-character values before running these commands
on the new host. Use a GitHub deploy credential with read-only repository access
if authentication is required; keep it outside the clone and command history.

```sh
export MM_RELEASE_COMMIT='REPLACE_WITH_VERIFIED_MAIN_COMMIT'
export MM_RELEASE_TREE='REPLACE_WITH_VERIFIED_MAIN_TREE'
umask 0022
git clone --no-single-branch https://github.com/levonmendall/The-Meme-Machine.git meme-machine
cd meme-machine
git fetch origin main
git merge-base --is-ancestor "$MM_RELEASE_COMMIT" refs/remotes/origin/main
git checkout --detach "$MM_RELEASE_COMMIT"
test "$(git rev-parse HEAD)" = "$MM_RELEASE_COMMIT"
test "$(git rev-parse 'HEAD^{tree}')" = "$MM_RELEASE_TREE"
test -z "$(git --no-optional-locks status --porcelain)"
test -f requirements.txt
test -f operational/runtime-resource-contract.json
```

Retain full Git history: source-equivalence and historical policy checks use
committed reference objects. A normal clone materializes `.python-version`,
`requirements.txt`, and documentation that a sparse engineering worktree can
omit. Do not copy `.venv`, untracked Python files, databases, credentials, or
DigitalOcean worktrees into this checkout.

## 2. Operating system, interpreter, and dependencies

The application explicitly requires **CPython 3.12.14**. Ubuntu's `python3`
command alone does not establish that patch version. The application checks the
SQLite library linked into Python, requiring **SQLite >= 3.45.1**; 3.45.1 is the
observed old-host version, not an exact binary pin. The repository also records
testing of 3.53.1. Any different linked version must pass the exact-source suites
before deployment. The `sqlite3` command's version can differ from Python's.

Install/build prerequisites on the new host:

```sh
sudo apt-get update
sudo apt-get install -y build-essential pkg-config ca-certificates curl git \
  xz-utils libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
  libffi-dev liblzma-dev libncurses-dev libgdbm-dev uuid-dev \
  sqlite3 util-linux procps iproute2 libseccomp2 systemd
```

Build CPython into its own prefix, preserving the OS interpreter. Obtain the
official CPython 3.12.14 source archive and independently authenticate its release
digest/signature through the Python release distribution. Set the authenticated
SHA-256 below; an unset digest stops this recipe. This repository does not vendor
or claim to pin OS package binaries, the CPython tarball digest, or wheel hashes.
Record their provenance in the installation receipt.

```sh
export MM_PYTHON_TARBALL_SHA256='REPLACE_WITH_AUTHENTICATED_RELEASE_SHA256'
mkdir -p "$HOME/meme-machine-build"
cd "$HOME/meme-machine-build"
curl --fail --location --proto '=https' --tlsv1.2 \
  --output Python-3.12.14.tar.xz \
  https://www.python.org/ftp/python/3.12.14/Python-3.12.14.tar.xz
printf '%s  %s\n' "$MM_PYTHON_TARBALL_SHA256" Python-3.12.14.tar.xz | sha256sum --check -
tar -xf Python-3.12.14.tar.xz
cd Python-3.12.14
./configure --prefix=/opt/cpython/3.12.14 --with-ensurepip=install
make -j4
sudo make altinstall
```

From the cloned repository, create an isolated environment and install the
committed dependency pins. No editable-package build is required: commands run
from the repository root. Application code and generated Yellowstone protobuf
modules are committed source.

```sh
/opt/cpython/3.12.14/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python - <<'PY'
import importlib.metadata as metadata
import platform
import sqlite3
assert platform.python_version() == '3.12.14'
assert sqlite3.sqlite_version_info >= (3, 45, 1)
print('Python', platform.python_version(), 'SQLite', sqlite3.sqlite_version)
for name in ('websockets', 'pysimdjson', 'grpcio', 'protobuf', 'based58'):
    print(name, metadata.version(name))
PY
```

The inspected requirements are `websockets==17.1`, `pysimdjson==7.0.2`,
`grpcio==1.84.0`, `protobuf==7.36.2`, and `based58==0.1.1`; the checked-out
`requirements.txt` is authoritative. Save `pip freeze`, OS release, kernel,
package versions, Python/SQLite versions, commit/tree, and requirements digest
outside economic state. The native containment proofs currently require Linux
x86_64, cgroup v2 CPU/memory/I/O controllers, block-device I/O accounting, and
seccomp user notification. An ARM instance is not equivalent validation.

## 3. Offline verification before connecting providers

No production state, provider credentials, or DigitalOcean files are needed for
the clean-checkout tests. `operational.tests` installs the market-network guard
and uses disposable synthetic state. Run the release's focused regressions and
the full applicable suites on this exact checkout; preserve failed/unknown
results. Tests that cannot obtain required Linux containment are unavailable,
not successful.

```sh
.venv/bin/python -m operational.tests FAST --modules \
  tests.test_solana_source_drain tests.test_source_handler_recovery \
  tests.test_control_interrupted_recovery tests.test_position_continuation \
  tests.test_integrated_startup_rehearsal
.venv/bin/python -m operational.tests OPERATIONAL --modules \
  tests.lanes.pump.test_postgrad_read_efficiency tests.lanes.pump.test_postgrad \
  tests.lanes.pump.test_pumpswap_survivor tests.test_final_acquisition
.venv/bin/python -m operational.tests FAST --modules \
  tests.test_operational_nine tests.test_paper_policy_compatibility \
  tests.lanes.pump.test_paper_opportunity_access tests.test_volume_quality \
  tests.test_shared_capital_economics tests.test_current_survivor_independence
.venv/bin/python -m operational.tests FAST --verbose
.venv/bin/python -m operational.tests OPERATIONAL --verbose
.venv/bin/python -m operational.dependencies
```

The complete FAST suite includes real kernel containment regressions. Follow
the exact privileged containment/affinity setup in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) on a **disposable Linux
validation host**, including two-CPU test affinity, enabled cgroup controllers,
and a parent file-descriptor soft limit of at least 4096. This tests the original
two-CPU protection contract; it does not set the four-vCPU runtime allowance.
Do not change kernel controller delegation under a running economic service or
skip containment failures to claim a release PASS. GitHub CI terminal results
must also be inspected for the final revision; queued/skipped/canceled jobs do
not pass.

## 4. Configuration and provider boundaries

Install source at `/opt/meme-machine` and keep credentials/configuration under
`/etc/meme-machine`, outside Git. For runtime, repeat the full clone and exact
commit/tree verification from section 1 at `/opt/meme-machine`; create its venv
there rather than moving a venv created elsewhere. On a new host where that
directory and service identity do not already exist:

```sh
sudo useradd --system --user-group --home-dir /var/lib/meme-machine \
  --shell /usr/sbin/nologin meme-machine
sudo install -d -o root -g root -m 0755 /etc/meme-machine
sudo sh -c 'umask 0022; git clone --no-single-branch https://github.com/levonmendall/The-Meme-Machine.git /opt/meme-machine'
sudo git -C /opt/meme-machine checkout --detach "$MM_RELEASE_COMMIT"
test "$(sudo git -C /opt/meme-machine rev-parse 'HEAD^{tree}')" = "$MM_RELEASE_TREE"
sudo /opt/cpython/3.12.14/bin/python3.12 -m venv /opt/meme-machine/.venv
sudo /opt/meme-machine/.venv/bin/python -m pip install \
  -r /opt/meme-machine/requirements.txt
sudo /opt/meme-machine/.venv/bin/python -m pip check
```

Use the dedicated `meme-machine` service user;
tracked source directories must be traversable and source files readable by
that identity. Use `umask 0022` for Git operations, including shared object stores.
Keep credential files root-owned mode 0600 and never print their contents.
The systemd manager reads `EnvironmentFile`; the application does not automatically
source `MM_PAPER_ENV_FILE` as a shell script.

Start from the committed
[`deployment/paper.env.example`](../deployment/paper.env.example), replacing
paths with the verified AWS persistent mount and preserving the migrated epoch.
The historical comments about creating a new $1,000 epoch do not authorize
recreation of the now-existing portfolio. These are configuration **names**:

| Name | Required meaning |
| --- | --- |
| `MM_MODE` | `PAPER` |
| `MM_PAPER_ENV_FILE` | Exact selected protected environment file; also captured in acceptance identity |
| `MM_STATE_ROOT` | Absolute canonical path to the authenticated migrated $1,000 shared epoch |
| `MM_STORAGE_GUARD_CONFIG` | Root-owned storage-identity JSON for that mount/device/epoch |
| `MM_BACKUP_ENV_FILE` | Explicit protected maintenance environment for acceptance capture; use an AWS-local path such as `/etc/meme-machine/backup.env`; no DigitalOcean token is needed |
| `MM_BACKUP_CONFIG_FILE` | Explicit reviewed backup configuration captured in acceptance identity, normally `/etc/meme-machine/backup.json` |
| `MM_SOLANA_READ_RPC_URL` | Existing authenticated Solana mainnet Alchemy HTTPS authority |
| `MM_ROBINHOOD_READ_RPC_URL` | Existing authenticated Robinhood Alchemy HTTPS authority, chain 4663 |
| `MM_PAPER_POLICY_REVISION` | `paper-opportunity-access-v1` |
| `MM_VOLUME_QUALITY_ENABLED` | Preserve the reviewed selection; attention tracking never grants capital |
| `MM_PUMP_HELD_RPC_MODE` | Preserve the reviewed `baseline`/`optimized` selection |
| `MM_SOLANA_HISTORY_SEPARATED` | Preserve the reviewed history-mode selection |
| `MM_RPC_CAPABILITIES`, `MM_PONS_LOG_CAPABILITY_FILE` | If used, authenticated, endpoint-bound capability files; never fabricated |
| `MM_PROVIDER_OPERATION_MODE`, `MM_CONTINUOUS_PROVIDER_ENVELOPE`, `MM_PROVIDER_USAGE_DB` | Continuous-mode profile and epoch-local durable usage ledger, only for the separately verified runtime |
| `MM_BOUNDED_PROVIDER_ENVELOPE`, `MM_BOUNDED_PROVIDER_DB`, `MM_POSITION_CONTINUATION_ENVELOPE` | Explicit bounded diagnostic/recovery profile; do not mix these with continuous mode |

Optional held-PAPER diagnostics are documented in
[`deployment/pump-pons-live-paper.env.example`](../deployment/pump-pons-live-paper.env.example).
Do not infer that a diagnostic flag changes quote/protection requirements.
Do not set `WALLET_PRIVATE_KEY`, `SOLANA_PRIVATE_KEY`, `ETH_PRIVATE_KEY`, or
`MM_LIVE_TRADING`; the PAPER entrypoint rejects them.
The backup path overrides retain legacy DigitalOcean filenames as defaults for
backward compatibility. Select the generic paths explicitly on AWS; a missing
explicit file fails closed. Acceptance records variable names/public endpoint
identity, not secret values. These overrides make configuration capture portable;
they do not implement AWS backup transport.

Provider access after deployment requires outbound DNS and authenticated TLS:
Solana HTTPS at `solana-mainnet.g.alchemy.com:443`, native gRPC/HTTP2 and WSS at
`solana-mainnet.streaming.alchemy.com:443`, and Robinhood HTTPS at
`robinhood-mainnet.g.alchemy.com:443`. Preserve separately selected public
observation/feed routes and original admission/pacing/error-preservation rules.
Confirm provider account entitlements and endpoint-bound capabilities during the
later bounded preflight. Dependency downloads and GitHub access are installation
traffic, not evidence of market-provider capability. No inbound trading API is
required; keep dashboard/metrics read-only and local unless separately secured.

## 5. Persistent data and authenticated recovery

Use a separately mounted **ext4** filesystem with state beneath its mount root,
for example `/srv/meme-machine/state/shared-1000`. The example is not a command
to create an epoch. `storage_guard` requires the actual mount target, filesystem
UUID, block-device identity, existing portfolio, epoch, and inception digest.
An empty directory or root-filesystem fallback cannot substitute for the mount.
AWS device and filesystem identities must be freshly verified; do not copy
DigitalOcean `/dev/disk/by-id` values.

The storage JSON has exactly these keys: `mount_target`, `state_root`,
`filesystem_uuid`, `volume_device`, `epoch_id`, `inception_sha256`. It is root-owned,
not writable by group/others, and readable by the service user. Bind its epoch
and inception checksum to authenticated restored evidence, not a newly generated
receipt. Keep state/service credentials private; do not recursively loosen data
permissions to solve source access.

Preserve the complete admitted recovery point: `portfolio.sqlite`,
`shared-capital.sqlite`, native lane databases/books/journals/genesis, reservations,
pending deliveries/inbox/obligations, Current/Survivor state and archives,
canonical evidence, original ACKs and delivery/source-session recovery records,
and provider usage/pacing ledgers. Unknown state files default to authoritative.
Preserve the historical $500 root separately. Source, financial state, and
non-economic observer/acceptance output have separate identities.

Use [`meme_machine.operational.backup`](../meme_machine/operational/backup.py)
and [`STATE_RECOVERY.md`](STATE_RECOVERY.md). The SQLite backup API incorporates
committed WAL data into each backup database. Never copy a changing `.sqlite`
file alone, delete live WAL/journals, or restore stale `.sock`, `.lock`, WAL, or
SHM files as economic authority. A completed point requires `backup.json`, valid
file hashes/SQLite integrity/full replay identity, and no incomplete/failed
marker. Keep failed and unknown evidence for disposition.

After authenticated transfer, with both original and replacement economic
writers stopped, verify **a new isolated restoration**, not the final
authoritative target. Set `MM_STATE_ROOT` to the intended authoritative AWS root
so the isolation guard excludes it. The `replay` command opens disposable
writers and must never target the authoritative root.

```sh
export MM_STATE_ROOT='/srv/meme-machine/state/shared-1000'
.venv/bin/python -m meme_machine.operational.backup verify /srv/meme-machine/restore-verification/point
.venv/bin/python -m meme_machine.operational.backup replay /srv/meme-machine/restore-verification/point
```

Do not improvise production schema migration with raw SQL. Required schema and
compatibility code is in Git, including
[`shared_capital/migration.py`](../meme_machine/shared_capital/migration.py) and
[`shared_capital_migration_check.py`](shared_capital_migration_check.py).
Review compatibility on the isolated copy and compare exact epoch/accounting,
native IDs, pending obligations, preserved ACK/deadline/session identities, and
single-writer fences before selecting the target. Native resumability is a
separate gate from flat monetary reconciliation; retain prior
`RECOVERY_REQUIRED` and failed drain records.

For later backups the portable `backup prepare TARGET --state-root ROOT` command
requires verified storage and fences the inactive supervisor, or freezes the
entire active cgroup under systemd with mandatory `ExecStopPost` thaw cleanup.
The active freeze deadline remains five seconds. A failed point is unusable.
Keep a verified off-host copy outside the host/disk failure domain, with bounded
retention and tested isolated restore. The DigitalOcean snapshot API wrapper and
its credentials are not an AWS backup implementation; the AWS operator must
select and verify off-host transport and restore before operational acceptance.

## 6. systemd and four-vCPU resource configuration

Deployment units are committed templates, not AWS configuration. Review every
literal `/mnt/volume_nyc1_1790918115030`, associated mount unit, environment path,
user, state root, backup destination, and read-only/write path before installing
host-specific units. Keep all units disabled and PAPER inactive during this work.
Do not copy `paper-bootstrap.conf` to start or initialize the migrated epoch.

| Unit | AWS adaptation and preserved behavior |
| --- | --- |
| `meme-machine-paper.service` | Exact `/opt/meme-machine/.venv/bin/python` entrypoint; verified mount dependencies and storage guard; `User=meme-machine`; `KillMode=control-group`; `UMask=0077`; diagnosis must use `Restart=no` and one manual controlled start |
| `meme-machine-observer.service` | AWS root and read-only filesystem isolation; output `/var/lib/meme-machine-observer`; no provider credentials |
| `meme-machine-monitor.service` | AWS storage guard/read-only paths; output `/var/lib/meme-machine-monitor`; independent of position management |
| `meme-machine-metrics.service`, `meme-machine-uptime-health.service` | Use an appropriate AWS host identity instead of `do-agent`; read-only bounded projections; existing localhost restrictions; independently verify external alert delivery |
| `meme-machine-backup-point.service` | AWS backup target/mount and exact environment; portable app-consistent point with guaranteed thaw cleanup |
| `meme-machine-backup.service`, `.timer` | Replace the DO-specific snapshot wrapper with separately verified AWS off-host backup integration; no timer activation before backup non-overlap/recovery verification |
| `meme-machine-acceptance@.service` | AWS read-only mount, exact source/configuration identity, `/var/lib/meme-machine-acceptance`; one shared phase lock; `Restart=no` |

Configure `CPUQuota`, `MemoryHigh`, `MemoryMax`, `TasksMax`/file-descriptor limits,
and stop behavior explicitly in a reviewed host drop-in and capture the effective
values with `systemctl show`; these systemd values are not expanded from an
arbitrary environment variable. Do not carry `CPUQuota=180%` forward as a
four-vCPU capacity decision. Reserve resources for the OS, maintenance and
observability; record the selected quota and actual available/burst CPU capacity.
No four-core numeric runtime allowance is certified by this runbook.

Continuation and continuous profiles accept an explicit `maximum_cpu_cores`
decimal **string**, finite, positive and no larger than the CPUs actually
available through both host count and process affinity. Existing profiles retain
`"1.8"`. An AWS-specific reviewed profile might use `"3.6"` with
`CPUQuota=360%` on four available CPUs, leaving capacity for other work; this is a
configuration example, not a capacity PASS or an instruction to activate it.
The supervisor requires a positive finite cgroup `cpu.max` quota no greater than
the configured CPU value and reports `cpu_quota_cores` separately from
`configured_cpu_cores`. Increasing only the systemd quota above an inherited
`"1.8"` profile still fails the guard.

The original memory and protection constraints remain:
`maximum_rss_bytes=6442450944`, `MemoryHigh=6G`, `MemoryMax=7G`, queue depth 64,
and queue wait five seconds. Preserve provider spend, byte, shutdown-reserve and
position-protection bounds while adapting hardware capacity. Confirm the host
has sufficient actual available RAM and verify effective cgroup values before
the first-start gate; do not silently relax these protections.

Retain the existing controller's one-start guard, 300-second readiness,
1,800-second work and 1,865-second final shutdown boundaries for bounded
diagnostics. Preserve native shutdown/drain deadlines and the original
three-/five-second Pons quote/valuation protection. Choose systemd stop handling
consistent with the actual selected controller; do not extend application
timeouts or permit an automatic restart loop. The base service's historical
`Restart=on-failure` and bootstrap drop-in's 65-second stop timeout do not
constitute a reviewed AWS diagnostic controller.

On the future host, inspect prepared units without enabling or starting them:

```sh
sudo systemd-analyze verify /etc/systemd/system/meme-machine-paper.service
sudo systemctl daemon-reload
sudo systemctl is-active meme-machine-paper.service
sudo systemctl is-enabled meme-machine-paper.service
sudo systemctl show meme-machine-paper.service \
  -p User -p Group -p WorkingDirectory -p Restart -p KillMode -p TimeoutStopUSec \
  -p CPUQuotaPerSecUSec -p MemoryHigh -p MemoryMax -p LimitNOFILE
```

`inactive` and `disabled` return nonzero status; that is the intended preparation
state. Store exact reviewed units/drop-ins and nonsecret identity receipts with
deployment evidence. Bound journald independently (for example 256 MB/seven
days) without deleting protected runtime evidence.

## 7. First-start gate and remaining AWS verification

Run the configuration-only check with the selected root-owned environment
loaded through systemd or a credential-safe loader; supplying
`MM_PAPER_ENV_FILE` alone does not load it. The check performs no provider I/O and
creates no state. Storage verification also refuses missing inception instead
of creating it:

```sh
/opt/meme-machine/.venv/bin/python -m meme_machine.operational check
/opt/meme-machine/.venv/bin/python -m meme_machine.operational.storage_guard \
  --state-root /srv/meme-machine/state/shared-1000 \
  --config /etc/meme-machine/storage.shared-1000.json
sudo -u meme-machine git -c safe.directory=/opt/meme-machine \
  -C /opt/meme-machine rev-parse HEAD 'HEAD^{tree}'
sudo -u meme-machine git -c safe.directory=/opt/meme-machine \
  -C /opt/meme-machine --no-optional-locks status --porcelain
```

Match the service-user source identities with the report. Configure Git trust
for this exact root-controlled deployment directory if acceptance's Git calls
require it; never broadly trust arbitrary directories. A root-readable clone is
insufficient. Repeat runtime/storage checks as the service identity using the
same selected environment, without exposing secrets or granting write access
to financial state to observers.

Before one manual funding-closed start, separately verify authenticated state
migration, exact financial replay and shared authority, native resumability,
original pending delivery/source/CONTROL obligations, original evidence ACKs,
exclusive ownership/no old-host writer, mount/storage identity and access,
provider capabilities and durable usage, physical resource profile, recovery
reference, backup non-overlap, and effective unit/controller deadlines. Missing
evidence keeps funding and service startup closed. Source merge alone is not
this gate.

Then use a precisely bounded, separately controlled observation to establish
real provider access and Pump/Pons startup/management, accepted-source completion
or durable recovery, complete shutdown, SQLite ownership, ACK conservation and
unchanged accounting. Measure sustained acquisition/commit/publication and
backlog, CPU/memory/storage/provider demand, held-Pons three-/five-second
protection, Current/Survivor independence, additions/partial exits/right-tail
management, and maintenance fairness on AWS. Old two-vCPU throughput failure is
retained evidence, not an AWS measurement or a source-publication blocker.

After these first-start gates and the prepared portable acceptance/backup/alert
configuration pass, the existing full acceptance phases remain:

```sh
sudo systemctl start meme-machine-acceptance@CAPACITY.service
# Inspect latest-CAPACITY.json and its complete result before proceeding.
sudo systemctl start meme-machine-acceptance@RECOVERY.service
# Inspect same-source, same-epoch native/financial recovery before proceeding.
sudo systemctl start meme-machine-acceptance@AUTONOMY.service
```

These are **later operational commands**, not installation commands. CAPACITY
requires 3,600 seconds; AUTONOMY requires 129,600 seconds. RECOVERY deliberately
signals the owned processes. Each phase requires its preceding phase, the exact
same candidate/configuration/epoch, durable receipts and independent observation;
short or interrupted runs cannot pass. Profitability and live-market opportunity
coverage remain separate measurements. Keep PAPER inactive/disabled until the
applicable first-start and migration gates are verified.

Remaining host-specific work is explicit: AWS mount/device/epoch binding,
credential delivery, tested four-vCPU resource profile, reviewed unit paths,
explicit portable acceptance configuration, off-host backup/restore, external
alert verification, and authentic provider/held-position/market-capacity gates.
None requires another DigitalOcean source checkout or untracked application file.
