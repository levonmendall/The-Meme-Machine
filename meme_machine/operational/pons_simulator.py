"""One separate experimental PAPER epoch using the ordinary Pons economics.

Preparation and reporting work without a market connection. The live adapter
uses the ordinary Supervisor and native Pons child with a separate, explicitly
experimental process-limit/storage contract, never another service's identity.
"""
import argparse
from contextlib import closing
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import resource
import sqlite3
import stat
import subprocess
import sys
import threading
import time


LOCATION = os.environ.get('MM_PONS_SIMULATOR_LOCATION', 'workspace')
LOCATIONS = dict(workspace=Path('/workspace/experiments/pons-simulator-20261024'),
    ec2=Path('/opt/mm-ec2-admin-runner/_work/meme-machine-admin/pons-simulator-experiment-20261024'))
EXPERIMENT = LOCATIONS.get(LOCATION, LOCATIONS['workspace'])
STATE = EXPERIMENT / 'state'
EPOCH = 'paper-pons-simulator-1000-20261024'
RESTORED_INCEPTION = '0098b5790dee06e6b540a1e02fad0db562d115006f10b3575b36ba4e0f221474'
RESTORED_JOURNAL = 'df1f211d6b64f26e0eea33c92d51a913fb2ca604da163d93044a1130d6f4de1a'
RESTORED_PROJECTION = 'c77501ffd4a25e2053e320c31b19dae95d2fd39d04168b7f4e3f57b07a462da1'
OBSERVER = Path('/opt/mm-ec2-admin-runner/_work/meme-machine-admin/pons-simulator-observer')
RETIRED_MARKER = 'simulator-authority-retired.json'
SOURCE = Path(__file__).resolve().parents[2]
RISK_FILE = SOURCE / 'operational/shared-capital-activation/risk-policy.shared-1000.proposed.json'
RISK_FILE_SHA256 = 'f2da6f2fa3f1451c1313be20bc3592d53070b70c62725cb0ac43fa6f3a73d034'
RISK_SHA256 = 'b91e83300994b6c02fe5e6bdbeb031cc391e6c8caa97af9fa6df1ecbc4aa979c'
PROFILE_SOURCE = SOURCE / 'operational/pump-first-release/deployment/paper-continuous.four-regime.json'
PROFILE_SOURCE_SHA256 = '7d07d80ca00218e4a65b05c873cb10ae2686ebe9109cd7fd4d61d5b39e0e048f'
PARENT_AS = 1024**3
NATIVE_AS = 6 * 1024**3
NOFILE = 8192
RESOURCE_CONTRACT = 'experimental_process_limits_v1'
OBLIGATIONS = ('reservations', 'commitments', 'obligations', 'pending_deliveries',
               'pending_backing', 'runtime_pending', 'runtime_inbox')


class SimulatorFailure(ValueError):
    """Fixed diagnostic codes only; provider configuration never enters output."""


def require(value, code):
    if not value:
        raise SimulatorFailure(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def writable_authority():
    require(LOCATION in LOCATIONS, 'SIMULATOR_LOCATION_INVALID')
    if STATE.exists() or STATE.is_symlink():
        physical(STATE)
    require(not (STATE / RETIRED_MARKER).exists() and not (STATE / RETIRED_MARKER).is_symlink(),
            'SIMULATOR_AUTHORITY_RETIRED')


def provider_paths():
    return dict(MM_PROVIDER_DB=str(OBSERVER / 'provider.sqlite' if LOCATION == 'ec2'
                                else STATE / 'shared/robinhood-provider.sqlite'),
                MM_RPC_CACHE_DB=str(OBSERVER / 'evidence.sqlite' if LOCATION == 'ec2'
                                   else STATE / 'shared/robinhood-evidence.sqlite'))


def write_once(path, value):
    writable_authority()
    raw = canonical(value)
    physical(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as out:
            out.write(raw); out.flush(); os.fsync(out.fileno())
    finally:
        os.close(fd)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    require(path.read_bytes() == raw, 'SIMULATOR_STORAGE_READBACK_FAILED')


def read_json(path):
    physical(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
            and before.st_nlink == 1 and not before.st_mode & 0o077 and before.st_size <= 65536,
            'SIMULATOR_PRIVATE_FILE_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = os.read(fd, 65537)
        after = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, len(raw), after.st_mtime_ns, after.st_ctime_ns),
                'SIMULATOR_FILE_CHANGED')
    finally:
        os.close(fd)
    return json.loads(raw)


def storage_space():
    physical(STATE)
    fs = os.statvfs(STATE)
    available = fs.f_bavail * fs.f_frsize
    used = (fs.f_blocks - fs.f_bfree) * fs.f_frsize
    require(available >= 5 * 1024**3 and used / (used + available) < .85,
            'SIMULATOR_STORAGE_HEADROOM_REQUIRED')
    return dict(device=STATE.stat().st_dev, available_bytes=available)


def verify_experimental_storage():
    financial = export_state()
    observed = storage_space()
    path = STATE / 'simulator-storage.json'
    binding = dict(schema='pons-simulator-storage-v1', epoch_id=EPOCH,
        inception_sha256=financial['inception_sha256'], device=observed['device'],
        storage_contract='experimental_current_filesystem_v1', power_loss_recovery_verified=False)
    if path.exists() or path.is_symlink():
        require(read_json(path) == binding, 'SIMULATOR_STORAGE_BINDING_CHANGED')
    else:
        write_once(path, binding)
    return binding


def continuous_profile():
    physical(PROFILE_SOURCE)
    raw = PROFILE_SOURCE.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == PROFILE_SOURCE_SHA256,
            'SIMULATOR_CONTINUOUS_SOURCE_CHANGED')
    profile = json.loads(raw)
    profile.update(funding_regimes=['pons_current'], maximum_cpu_cores='1')
    from .position_continuation import validate_continuous
    validate_continuous(profile)
    path = STATE / 'continuous-profile.json'
    if path.exists() or path.is_symlink():
        require(read_json(path) == profile, 'SIMULATOR_CONTINUOUS_PROFILE_CHANGED')
    else:
        write_once(path, profile)
    return profile


def ensure_provider_usage():
    """One durable fresh-experiment ledger, then ordinary reopen; never reset."""
    writable_authority()
    from .bounded_provider import Budget
    profile = continuous_profile()
    path = STATE / 'shared/provider-usage.continuous.sqlite'
    marker_path = STATE / 'simulator-provider-initialization.json'
    financial = export_state()
    marker = dict(schema='pons-simulator-provider-initialization-v1', epoch_id=EPOCH,
        inception_sha256=financial['inception_sha256'], profile_sha256=hashlib.sha256(canonical(profile)).hexdigest())
    physical(path)
    if marker_path.exists() or marker_path.is_symlink():
        require(read_json(marker_path) == marker and path.is_file(), 'SIMULATOR_PROVIDER_HISTORY_REQUIRED')
    elif not path.exists():
        require(not financial['provider_usage_bound'], 'SIMULATOR_PROVIDER_HISTORY_REQUIRED')
        # Durable intent PRECEDES creation. An interrupted creation or missing
        # ledger cannot be mistaken for a new zero-consumption allowance.
        write_once(marker_path, marker)
    budget = Budget(path) if path.exists() else Budget.create(path, continuous=profile)
    require(budget.continuous and budget.envelope == profile,
            'SIMULATOR_EXISTING_PROVIDER_PROFILE_MISMATCH')
    budget.preflight_file(STATE / 'continuous-profile.json')
    if not marker_path.exists():
        # An already-existing authenticated ledger may acquire the new marker;
        # none of its clocks, counters or receipts is changed or re-created.
        write_once(marker_path, marker)
    return budget


def process_facts(pid):
    root = Path('/proc') / str(pid)
    def stamp():
        raw = (root / 'stat').read_text()
        require(len(raw) <= 4096, 'SIMULATOR_PROCESS_IDENTITY_UNAVAILABLE')
        fields = raw.rsplit(')', 1)[1].split()
        return int(fields[19]), int(fields[1])
    start, parent = stamp()
    text = (root / 'status').read_text()
    require(len(text) <= 65536, 'SIMULATOR_PROCESS_IDENTITY_UNAVAILABLE')
    status = dict(line.split(':', 1) for line in text.splitlines() if ':' in line)
    require(int(status['Uid'].split()[0]) == os.geteuid(), 'SIMULATOR_PROCESS_OWNER_CHANGED')
    limits = {}
    for line in (root / 'limits').read_text().splitlines():
        for key in ('Max address space', 'Max open files', 'Max core file size'):
            if line.startswith(key):
                limits[key] = tuple(int(value) for value in line[len(key):].split()[:2])
    tasks = list((root / 'task').iterdir())
    require(0 < len(tasks) <= 128, 'SIMULATOR_PROCESS_TOPOLOGY_CHANGED')
    affinities = [set(os.sched_getaffinity(int(task.name))) for task in tasks]
    children = {int(value) for task in tasks for value in (task / 'children').read_text().split()}
    cgroup = (root / 'cgroup').read_text()
    require(len(cgroup) <= 4096, 'SIMULATOR_CGROUP_UNAVAILABLE')
    require(stamp() == (start, parent), 'SIMULATOR_PROCESS_IDENTITY_CHANGED')
    return dict(pid=pid, start=start, parent=parent, rss=int(status['VmRSS'].split()[0]) * 1024,
                limits=limits, affinities=affinities, children=children, cgroup=cgroup)


def own_cgroup_memory():
    raw = Path('/proc/self/cgroup').read_text().strip()
    require(len(raw) <= 4096 and raw.startswith('0::/') and '\n' not in raw,
            'SIMULATOR_CGROUP_UNAVAILABLE')
    relative = raw[3:]
    require(all(part not in ('.', '..') for part in Path(relative).parts)
            and relative not in ('/system.slice/meme-machine-paper.service',
                                 '/system.slice/meme-machine-pons-pilot.service'),
            'SIMULATOR_FOREIGN_RESOURCE_IDENTITY')
    group = Path('/sys/fs/cgroup') / relative.lstrip('/')
    maximum = (group / 'memory.max').read_text().strip()
    require(maximum.isdecimal() and int(maximum) > 0, 'SIMULATOR_INHERITED_MEMORY_LIMIT_REQUIRED')
    return int((group / 'memory.current').read_text()), int(maximum)


def install_process_limits(*, native=False):
    # This runs only in a dedicated CLI process or the single-thread exec
    # launcher, never preexec_fn inside the threaded Supervisor.
    require(len(list(Path('/proc/self/task').iterdir())) == 1,
            'SIMULATOR_SINGLE_THREAD_LAUNCH_REQUIRED')
    affinity = sorted(os.sched_getaffinity(0))
    require(bool(affinity), 'SIMULATOR_CPU_AFFINITY_UNAVAILABLE')
    os.sched_setaffinity(0, {affinity[0]})
    for key, soft, hard in ((resource.RLIMIT_AS, NATIVE_AS if native else PARENT_AS, NATIVE_AS),
            (resource.RLIMIT_NOFILE, NOFILE, NOFILE), (resource.RLIMIT_CORE, 0, 0)):
        current_hard = resource.getrlimit(key)[1]
        require(current_hard == resource.RLIM_INFINITY or current_hard >= hard,
                'SIMULATOR_INHERITED_LIMIT_TOO_SMALL')
        resource.setrlimit(key, (soft, hard))
        require(resource.getrlimit(key) == (soft, hard), 'SIMULATOR_LIMIT_NOT_ENFORCED')
    return set(os.sched_getaffinity(0))


def source_binding():
    git = ['/usr/bin/git', '--no-optional-locks', '-c', 'safe.directory=' + str(SOURCE),
           '-c', 'core.hooksPath=/dev/null',
           '-c', 'core.fsmonitor=false', '-C', str(SOURCE)]
    env = dict(PATH='/usr/bin:/bin', LANG='C', HOME='/nonexistent', GIT_OPTIONAL_LOCKS='0',
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
    hashes = subprocess.check_output(git + ['rev-parse', 'HEAD', 'HEAD^{tree}'],
        env=env, stderr=subprocess.DEVNULL, timeout=5).decode('ascii').splitlines()
    require(len(hashes) == 2 and all(len(value) == 40 and all(c in '0123456789abcdef' for c in value)
                                   for value in hashes), 'SIMULATOR_SOURCE_UNAVAILABLE')
    dirty = subprocess.check_output(git + ['status', '--porcelain', '--untracked-files=all'],
                                   env=env, stderr=subprocess.DEVNULL, timeout=5)
    require(not dirty, 'SIMULATOR_FROZEN_CLEAN_SOURCE_REQUIRED')
    return dict(commit=hashes[0], tree=hashes[1])


def native_child():
    writable_authority()
    require(os.environ.get('MM_MODE') == 'PAPER' and os.environ.get('MM_STATE_ROOT') == str(STATE)
            and os.environ.get('MM_PAPER_EPOCH') == EPOCH
            and os.environ.get('MM_RUNTIME_LANE') == 'pons', 'SIMULATOR_NATIVE_SCOPE_REQUIRED')
    expected = dict(commit=os.environ.pop('MM_PONS_SIMULATOR_SOURCE_COMMIT', ''),
                    tree=os.environ.pop('MM_PONS_SIMULATOR_SOURCE_TREE', ''))
    require(source_binding() == expected, 'SIMULATOR_NATIVE_SOURCE_CHANGED')
    install_process_limits(native=True)
    os.execv(sys.executable, [sys.executable, '-m', 'meme_machine.operational.lane',
        '--lane', 'pons', '--state-root', str(STATE)])


def supervisor_type():
    from .supervisor import Supervisor
    class SimulatorSupervisor(Supervisor):
        def __init__(self, *, admission, binding):
            super().__init__(STATE, admission=admission)
            self.frozen_source = binding
            self.expected_affinity = set(os.sched_getaffinity(0))
            self.parent_start = process_facts(os.getpid())['start']
            self.native_start = None
            self.storage_device = None
            self.resource_failure = None

        def verify_storage(self):
            writable_authority()
            require(self.root == STATE, 'SIMULATOR_STATE_SCOPE_CHANGED')
            binding = verify_experimental_storage()
            self.storage_device = binding['device']
            return binding

        def launch_lane(self, lane, args, folder, env):
            require(lane == 'pons' and self.runtime_lanes() == ('pons',), 'SIMULATOR_PONS_ONLY_REQUIRED')
            scoped = dict(env, MM_PONS_SIMULATOR_SOURCE_COMMIT=self.frozen_source['commit'],
                          MM_PONS_SIMULATOR_SOURCE_TREE=self.frozen_source['tree'],
                          MM_PONS_SIMULATOR_LOCATION=LOCATION, **provider_paths())
            child = subprocess.Popen([sys.executable, '-m', 'meme_machine.operational.pons_simulator', 'native-child'],
                cwd=folder, env=scoped, start_new_session=True)
            try:
                self.native_start = (child.pid, process_facts(child.pid)['start'])
                deadline = time.monotonic() + 10
                while True:
                    facts = process_facts(child.pid)
                    require((child.pid, facts['start']) == self.native_start,
                            'SIMULATOR_PROCESS_IDENTITY_CHANGED')
                    if facts['limits'].get('Max address space') == (NATIVE_AS, NATIVE_AS):
                        require(facts['parent'] == os.getpid()
                                and all(affinity == self.expected_affinity for affinity in facts['affinities'])
                                and facts['limits'].get('Max open files') == (NOFILE, NOFILE)
                                and facts['limits'].get('Max core file size') == (0, 0),
                                'SIMULATOR_NATIVE_LIMIT_NOT_ENFORCED')
                        break
                    require(child.poll() is None and time.monotonic() < deadline,
                            'SIMULATOR_NATIVE_LIMIT_ADMISSION_DEADLINE')
                    time.sleep(.02)
            except BaseException:
                child.kill(); child.wait(timeout=5)
                raise
            return child

        def resource_health(self, now, reason):
            try:
                require(set(self.processes) == {'pons'} and self.native_start is not None,
                        'SIMULATOR_PROCESS_TOPOLOGY_CHANGED')
                parent = process_facts(os.getpid())
                child = process_facts(self.processes['pons'].pid)
                require(parent['start'] == self.parent_start
                        and (child['pid'], child['start']) == self.native_start
                        and child['parent'] == parent['pid']
                        and child['cgroup'] == parent['cgroup']
                        and parent['children'] == {child['pid']} and not child['children'],
                        'SIMULATOR_PROCESS_TOPOLOGY_CHANGED')
                require(len(self.expected_affinity) == 1 and all(affinity == self.expected_affinity
                    for row in (parent, child) for affinity in row['affinities']),
                    'SIMULATOR_CPU_AFFINITY_CHANGED')
                for row, address_space in ((parent, PARENT_AS), (child, NATIVE_AS)):
                    require(row['limits'].get('Max address space') == (address_space, NATIVE_AS)
                            and row['limits'].get('Max open files') == (NOFILE, NOFILE)
                            and row['limits'].get('Max core file size') == (0, 0),
                            'SIMULATOR_LIMIT_NOT_CURRENT')
                memory, inherited_maximum = own_cgroup_memory()
                rss = parent['rss'] + child['rss']
                ceiling = self.provider_budget.envelope['maximum_rss_bytes']
                require(rss < ceiling and memory < ceiling, 'SIMULATOR_MEMORY_PRESSURE')
                require(storage_space()['device'] == self.storage_device,
                        'SIMULATOR_STORAGE_BINDING_CHANGED')
                self.resource_measurement = dict(limits_verified=True, resource_contract=RESOURCE_CONTRACT,
                    cgroup_scope='INHERITED_SHARED', cgroup_memory_bytes=memory,
                    inherited_cgroup_memory_max=inherited_maximum, aggregate_rss_bytes=rss,
                    parent_as_bytes=PARENT_AS, native_as_bytes=NATIVE_AS,
                    aggregate_current_address_space_soft_limit=PARENT_AS + NATIVE_AS,
                    configured_cpu_cores='1', cpu_affinity=sorted(self.expected_affinity),
                    maximum_queue_depth=64, maximum_queue_wait_seconds=5,
                    original_cgroup_contract_verified=False)
            except (OSError, ValueError, KeyError, ArithmeticError):
                self.resource_measurement = dict(limits_verified=False, resource_contract=RESOURCE_CONTRACT,
                    state='UNAVAILABLE', original_cgroup_contract_verified=False)
                self.resource_failure = 'SIMULATOR_RESOURCE_EVIDENCE_UNAVAILABLE'
                if self.admission == 'OBSERVATION':
                    self.stop_requested = True
                reason = reason or 'simulator_resource_evidence_unavailable'
            return reason

        def publish(self, *, provider_sample=None):
            # Ordinary OBSERVATION does not run continuation_health. Measure on
            # its existing main-loop publication cadence as well as NORMAL.
            if self.admission == 'OBSERVATION' and getattr(self, 'provider_budget', None):
                if self.stop_requested and self.processes and all(
                        proc.poll() is not None for proc in self.processes.values()):
                    # Supervisor's final publication follows joined ownership.
                    # Do not turn that expected dead PID into a new live fault,
                    # or erase an actual fault retained before the shutdown.
                    self.resource_measurement = dict(state='STOPPED', limits_verified=False,
                        resource_contract=RESOURCE_CONTRACT, original_cgroup_contract_verified=False)
                else:
                    self.resource_health(time.time(), None)
            return super().publish(provider_sample=provider_sample)
    return SimulatorSupervisor


def physical(path):
    """Refuse an alias into an existing epoch, including dangling aliases."""
    path = Path(path)
    require(path.is_absolute(), 'SIMULATOR_ABSOLUTE_PATH_REQUIRED')
    for parent in reversed(path.parents):
        require(stat.S_ISDIR(parent.lstat().st_mode), 'SIMULATOR_PATH_NOT_PHYSICAL')
    require(not path.is_symlink(), 'SIMULATOR_PATH_NOT_PHYSICAL')
    return path


def new_ancestors(path):
    for node in reversed((path, *path.parents)):
        try:
            info = node.lstat()
        except FileNotFoundError:
            node.mkdir(mode=0o700)
            info = node.lstat()
        require(stat.S_ISDIR(info.st_mode), 'SIMULATOR_PATH_NOT_PHYSICAL')


def approved_risk():
    physical(RISK_FILE)
    before = RISK_FILE.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 65536,
            'SIMULATOR_APPROVED_RISK_REQUIRED')
    fd = os.open(RISK_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_uid,
            value.st_gid, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        require(identity(os.fstat(fd)) == identity(before), 'SIMULATOR_RISK_CHANGED')
        raw = os.read(fd, 65537)
        require(identity(os.fstat(fd)) == identity(before) and len(raw) == before.st_size,
                'SIMULATOR_RISK_CHANGED')
    finally:
        os.close(fd)
    require(hashlib.sha256(raw).hexdigest() == RISK_FILE_SHA256,
            'SIMULATOR_APPROVED_RISK_REQUIRED')
    value = json.loads(raw)
    require(hashlib.sha256(canonical(value)).hexdigest() == RISK_SHA256,
            'SIMULATOR_APPROVED_RISK_REQUIRED')
    return value


def readonly(path):
    physical(path)
    require(path.is_file(), 'SIMULATOR_EXISTING_DATABASE_REQUIRED')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    return db


def export_state():
    """Replay the actual selected authority; never construct a financial writer."""
    require(LOCATION in LOCATIONS, 'SIMULATOR_LOCATION_INVALID')
    from meme_machine.shared_capital.reporting import read_authority, export
    from meme_machine.shared_capital.runtime import selected
    physical(STATE)
    database = STATE / 'portfolio.sqlite'
    physical(database)
    physical(STATE / 'shared-capital.sqlite')
    require(selected(database) == STATE / 'shared-capital.sqlite', 'SIMULATOR_SHARED_AUTHORITY_REQUIRED')
    with closing(readonly(STATE / 'shared-capital.sqlite')) as db:
        reader = read_authority(db)
        reader.path = STATE / 'shared-capital.sqlite'
        replay = reader.verify_replay()
        ledger = reader._read()
        head = db.execute('SELECT sequence,hash,state_hash FROM shared_capital_events ORDER BY sequence DESC LIMIT 1').fetchone()
        require(head and (replay['events'], replay['journal_hash'], replay['state_sha256']) == head,
                'SIMULATOR_REPLAY_HEAD_INVALID')
        require(ledger['epoch_id'] == EPOCH and Decimal(ledger['initial_capital']) == 1000
                and ledger['policy'] == approved_risk(), 'SIMULATOR_EPOCH_OR_RISK_MISMATCH')
        if LOCATION == 'ec2':
            require(ledger['inception_sha256'] == RESTORED_INCEPTION
                    and db.execute('SELECT hash,state_hash FROM shared_capital_events WHERE sequence=2').fetchone()
                    == (RESTORED_JOURNAL, RESTORED_PROJECTION), 'SIMULATOR_RESTORED_CHECKPOINT_REQUIRED')
        retired = (STATE / RETIRED_MARKER).exists() or (STATE / RETIRED_MARKER).is_symlink()
        projection = export(reader, at=ledger['at'] if retired else int(time.time()))
    with closing(readonly(database)) as db:
        pending = db.execute('SELECT count(*) FROM portfolio_native_pending').fetchone()[0]
    counts = {key: len(ledger.get(key, {})) for key in OBLIGATIONS}
    counts.update(positions_open=sum(p['status'] == 'OPEN' for p in ledger['positions'].values()),
                  legacy_native_pending=pending)
    require(not any(p['regime'] != 'pons_current' and p['status'] == 'OPEN'
                    for p in ledger['positions'].values()), 'SIMULATOR_FOREIGN_OPEN_POSITION')
    for bucket in ('reservations', 'commitments', 'obligations'):
        require(all(p['regime'] == 'pons_current' for p in ledger[bucket].values()),
                'SIMULATOR_FOREIGN_OBLIGATION')
    return dict(epoch_id=EPOCH, inception_sha256=ledger['inception_sha256'],
        authority='RETIRED_MIRROR' if retired else 'SELECTED', authority_retired=retired,
        sequence=head[0], journal_hash=head[1], projection_sha256=head[2],
        replay=replay, obligations=counts, portfolio=projection,
        admission_mode=ledger.get('runtime_admission', {}).get('mode'),
        provider_usage_bound=bool(ledger.get('runtime_admission', {}).get('continuous_provider_db')),
        current_readiness_verified=False, held_protection_demonstrated=False,
        autonomous_acceptance=False)


def prepare():
    """Create one new $1,000 epoch; existing or interrupted state is preserved."""
    require(LOCATION in LOCATIONS, 'SIMULATOR_LOCATION_INVALID')
    require(LOCATION == 'workspace', 'SIMULATOR_EC2_RESEED_FORBIDDEN')
    require(not STATE.exists() and not STATE.is_symlink(), 'SIMULATOR_EPOCH_EXISTS_NO_RESEED')
    risk = approved_risk()
    # Only the experiment's new ancestors may be created. The native constructor
    # below owns the exclusive state-directory creation and refuses all reuse.
    new_ancestors(STATE.parent)
    physical(STATE)
    from meme_machine.portfolio_accounting import inception_receipt, PortfolioAccounting
    from meme_machine.operational.supervisor import identities
    from meme_machine.runtime.directional_sleeve import policies
    from meme_machine.runtime.usd_valuation import utc
    from meme_machine.shared_capital.operational_candidate import initialize_new_epoch
    from meme_machine.shared_capital.cutover import install
    from meme_machine.operational.backup import snapshot_database
    receipt = inception_receipt(EPOCH, utc(time.time()), EPOCH + ':inception',
                                starting_capital='1000.00', shared=True)
    ids = identities(receipt)
    contracts = {lane: dict(strategy_id=lane, policy_hash=ids[lane]['policy_hash'])
                 for lane in ('meteora', 'ramses')}
    for family in ('pump', 'pons'):
        for strategy, checksum in policies(family).items():
            regime = family + ('_survivor' if 'survivor' in strategy else '_current')
            contracts[regime] = dict(strategy_id=strategy, policy_hash=checksum)
    plan = initialize_new_epoch(STATE, receipt, portfolio_identities=ids['pump'],
        lane_identities=ids, contracts=contracts, policy=risk)
    backup = STATE / 'simulator-inception-backup.sqlite'
    snapshot_database(STATE / 'portfolio.sqlite', backup, time.monotonic() + 15)
    with closing(readonly(backup)) as db:
        reader = object.__new__(PortfolioAccounting)
        reader.db = db
        seed = reader._replay()
        reader._reconcile(seed)
        require(seed['receipt'] == receipt and not seed['positions'] and not seed['reservations'],
                'SIMULATOR_INCEPTION_BACKUP_INVALID')
    marker = install(STATE, plan, approved_policy=plan['policy'], observation_only=True,
        prerequisites=dict(writers_stopped=True, coherent_backup_verified=True,
            native_mapping_verified=True, recovery_verified=True, provider_proof_verified=False))
    (STATE / 'shared').mkdir(mode=0o700)
    return dict(state='PREPARED_FUNDING_CLOSED', marker=marker, financial=export_state(),
                original_state_imported=False, provider_history_imported=False,
                paper_only=True, real_money_authority=False)


def require_provider_clock():
    from meme_machine.runtime.provider_clock import current_identity, ProviderClockError
    try:
        return current_identity()
    except ProviderClockError:
        raise SimulatorFailure('PROVIDER_CLOCK_IDENTITY_UNAVAILABLE') from None


def runtime_blockers(environ=None):
    """Configuration checks only: no provider call, public fallback or allowance."""
    env = os.environ if environ is None else environ
    blockers = []
    try:
        writable_authority()
    except SimulatorFailure as error:
        blockers.append(str(error))
    try:
        require_provider_clock()
    except SimulatorFailure:
        blockers.append('PROVIDER_CLOCK_IDENTITY_UNAVAILABLE')
    if not STATE.exists():
        blockers.append('SIMULATOR_NOT_PREPARED')
    from meme_machine.runtime.robinhood.provider_authority import endpoint
    try:
        endpoint(environ=env)
    except ValueError:
        blockers.append('CANONICAL_ALCHEMY_PROVIDER_NOT_CONFIGURED')
    return blockers


def status():
    result = dict(state='UNPREPARED', epoch_id=EPOCH, paper_only=True,
                  real_money_authority=False, blockers=runtime_blockers())
    if STATE.exists() or STATE.is_symlink():
        result.update(state='LEDGER_RECONCILED', financial=export_state())
        if result['financial']['authority_retired']:
            result['state'] = 'RETIRED_MIRROR'
    return result


def configure_runtime():
    writable_authority()
    require_provider_clock()
    if LOCATION == 'ec2':
        restored = export_state()
        require(restored['provider_usage_bound'] or restored['sequence'] == 2,
                'SIMULATOR_RESTORED_CHECKPOINT_REQUIRED')
        for path in provider_paths().values():
            require(Path(path).is_file(), 'SIMULATOR_OBSERVER_PROVIDER_HISTORY_REQUIRED')
            physical(Path(path))
    from .supervisor import validate_environment
    from meme_machine.runtime.robinhood.provider_authority import endpoint, reference
    endpoint()  # Configuration identity only. No secret is returned or serialized.
    validate_environment(required_lanes=('pons',))
    profile = continuous_profile()
    verify_experimental_storage()
    provider = dict(schema='pons-simulator-provider-v1', epoch_id=EPOCH, reference=reference())
    path = STATE / 'simulator-provider.json'
    if path.exists() or path.is_symlink():
        require(read_json(path) == provider, 'SIMULATOR_PROVIDER_BINDING_CHANGED')
    else:
        write_once(path, provider)
    ensure_provider_usage()
    os.environ.update(MM_MODE='PAPER', MM_STATE_ROOT=str(STATE), MM_PAPER_EPOCH=EPOCH,
        MM_PROVIDER_OPERATION_MODE='CONTINUOUS',
        MM_PROVIDER_USAGE_DB=str(STATE / 'shared/provider-usage.continuous.sqlite'),
        MM_CONTINUOUS_PROVIDER_ENVELOPE=str(STATE / 'continuous-profile.json'),
        **provider_paths(),
        MM_ROBINHOOD_STATE_DIR=str(STATE / 'shared'),
        MM_VOLUME_QUALITY_ENABLED='1', MM_PONS_OBSERVATION_ROUTE='canonical_primary',
        MM_PONS_USD_BRIDGE_ROUTES='verified_two_hop_v1', MM_PONS_USD_ACQUISITION_OVERLAP='1')
    # Budget creation/reopen remains the ordinary Supervisor operation. Nothing
    # here removes, replaces or replenishes an existing usage database/counter.
    return profile


def native_drain():
    """Check actual stopped native checkpoint/ownership, separately from money."""
    cohort = STATE / 'pons/pons-selective-continuation-v1-cohort'
    progress_path = cohort / 'cohort-progress.json'
    physical(progress_path)
    progress = json.loads(progress_path.read_text())
    physical(STATE / 'pons/health.json')
    health = json.loads((STATE / 'pons/health.json').read_text())
    with closing(readonly(Path(provider_paths()['MM_RPC_CACHE_DB']).with_suffix('.candidates.sqlite'))) as db:
        rows = dict(db.execute("SELECT key,body FROM runtime WHERE key IN ('pons_current_startup','pons_cohort')"))
        require(set(rows) == {'pons_current_startup', 'pons_cohort'}, 'SIMULATOR_NATIVE_CHECKPOINT_REQUIRED')
        startup, checkpoint = (json.loads(rows[key]) for key in ('pons_current_startup', 'pons_cohort'))
        require(startup.get('complete') is True and startup == progress.get('current_startup_coverage')
                and checkpoint.get('cursor') == progress.get('canonical_discovery_cursor')
                and checkpoint.get('phase') == progress.get('phase') == 'finalizing',
                'SIMULATOR_NATIVE_DRAIN_INCOMPLETE')
        require(db.execute('SELECT count(*) FROM candidates WHERE claim IS NOT NULL').fetchone()[0] == 0
                and db.execute('SELECT count(*) FROM receipt_obligations').fetchone()[0] == 0,
                'SIMULATOR_NATIVE_OBLIGATIONS_REMAIN')
    proof = health.get('native_continuation', {})
    require(health.get('phase') == 'STOPPED' and health.get('reconciled') is True
            and all(proof.get(key) is True for key in ('current_restored', 'survivor_replay_verified',
                'survivor_handoff_ready', 'exit_path_bound')), 'SIMULATOR_NATIVE_RECOVERY_REQUIRED')
    return dict(cursor=checkpoint['cursor'], startup_complete=True,
                current_survivor_recovery=True, held_protection_demonstrated=False)


def shadow(service, binding):
    """The ordinary owner runs; one read-only observer measures the usable window."""
    from .acceptance import observe
    from .position_continuation import readiness
    stopped = threading.Event()
    began = time.monotonic()
    measured = dict(ready=None, first_cursor=None, last_cursor=None, last_sample=None, samples=0, failure=None)
    def sample():
        while not stopped.wait(2):
            now = time.monotonic()
            usable = False
            try:
                health, portfolio, rss = observe(STATE, funding_lanes=('pons',))
                require(health['admission_mode'] == 'OBSERVATION', 'SIMULATOR_SHADOW_FUNDING_MODE')
                readiness(health, portfolio, rss, service.provider_budget.envelope)
                cursor = health['active_evidence']['pons_canonical_cursor']
                usable = True
            except (OSError, ValueError, KeyError, RuntimeError, AttributeError):
                pass
            if measured['ready'] is None:
                if now - began > 300:
                    measured['failure'] = 'SIMULATOR_SHADOW_READINESS_DEADLINE'
                elif usable:
                    measured.update(ready=now, first_cursor=cursor, last_cursor=cursor,
                                    last_sample=now, samples=1)
            elif not usable or now - measured['last_sample'] > 5 or cursor < measured['last_cursor']:
                measured['failure'] = 'SIMULATOR_SHADOW_REQUIRED_EVIDENCE_LOST'
            else:
                measured.update(last_sample=now, last_cursor=cursor, samples=measured['samples'] + 1)
                if now - measured['ready'] >= 120 and cursor > measured['first_cursor']:
                    service.stop_requested = True
                    return
            if measured['failure']:
                service.stop_requested = True
                return
    thread = threading.Thread(target=sample, name='simulator-readonly-shadow', daemon=True)
    thread.start()
    try:
        service.run(seconds=420)
    finally:
        stopped.set(); thread.join(6)
    require(not thread.is_alive(), 'SIMULATOR_SHADOW_OBSERVER_DID_NOT_JOIN')
    require(service.resource_failure is None, service.resource_failure or 'SIMULATOR_SHADOW_RESOURCE_FAILURE')
    require(measured['failure'] is None, measured['failure'] or 'SIMULATOR_SHADOW_FAILED')
    require(measured['ready'] is not None and measured['last_sample'] - measured['ready'] >= 120
            and measured['last_cursor'] > measured['first_cursor'], 'SIMULATOR_SHADOW_WINDOW_INCOMPLETE')
    financial = export_state()
    require(all(value == 0 for value in financial['obligations'].values()),
            'SIMULATOR_SHADOW_FINANCIAL_OBLIGATIONS_REMAIN')
    drain = native_drain()
    require(source_binding() == binding, 'SIMULATOR_SHADOW_SOURCE_CHANGED')
    result = dict(schema='pons-simulator-shadow-v1', epoch_id=EPOCH,
        inception_sha256=financial['inception_sha256'], sequence=financial['sequence'],
        journal_hash=financial['journal_hash'], ended_at=time.time(),
        usable_seconds=measured['last_sample'] - measured['ready'],
        startup_seconds=measured['ready'] - began, samples=measured['samples'],
        first_cursor=measured['first_cursor'], last_cursor=measured['last_cursor'],
        funding_mode='OBSERVATION', native=drain, resource_contract=RESOURCE_CONTRACT,
        source=binding, profile_sha256=hashlib.sha256((STATE / 'continuous-profile.json').read_bytes()).hexdigest(),
        provider=read_json(STATE / 'simulator-provider.json'),
        held_protection_demonstrated=False, autonomous_acceptance=False)
    # Successful history is append-only; later failures never replace it with PASS.
    path = STATE / ('simulator-shadow-' + str(time.time_ns()) + '.json')
    write_once(path, result)
    return dict(state='SHADOW_DRAIN_VERIFIED', shadow=result, financial=financial,
                shadow_receipt=path.name, paper_only=True, real_money_authority=False)


def runtime(command):
    require(command in ('shadow', 'run'), 'SIMULATOR_COMMAND_INVALID')
    blockers = runtime_blockers()
    if blockers:
        return dict(state='BLOCKED', epoch_id=EPOCH, requested_command=command, blockers=blockers,
            native_runtime_started=False, shadow_accepted=False, real_money_authority=False)
    binding = source_binding()
    configure_runtime()
    if command == 'run':
        # First NORMAL is deliberately separate from a successful live shadow.
        # Existing native recovery and fresh60s readiness still gate every fill.
        receipts = sorted(STATE.glob('simulator-shadow-*.json'))
        require(bool(receipts), 'SIMULATOR_DRAINED_SHADOW_REQUIRED')
        prior = read_json(receipts[-1])
        current = export_state()
        require(prior.get('schema') == 'pons-simulator-shadow-v1' and prior.get('epoch_id') == EPOCH
                and prior.get('inception_sha256') == current['inception_sha256']
                and prior.get('source') == binding
                and prior.get('profile_sha256') == hashlib.sha256((STATE / 'continuous-profile.json').read_bytes()).hexdigest()
                and prior.get('provider') == read_json(STATE / 'simulator-provider.json')
                and prior.get('usable_seconds', 0) >= 120
                and (current['admission_mode'] == 'NORMAL'
                     or 0 <= time.time() - prior.get('ended_at', 0) <= 900),
                'SIMULATOR_DRAINED_SHADOW_REQUIRED')
        if current['admission_mode'] != 'NORMAL':
            require(prior.get('sequence') == current['sequence']
                    and prior.get('journal_hash') == current['journal_hash']
                    and all(value == 0 for value in current['obligations'].values()),
                    'SIMULATOR_SHADOW_FINANCIAL_CONTINUITY_REQUIRED')
            native_drain()
        # A later NORMAL resume may hold legitimate P&L and pending positions.
        # Ordinary native startup restores those owners before discovery; fresh
        # current-process readiness still closes all new allocations meanwhile.
    install_process_limits()
    service = supervisor_type()(admission='OBSERVATION' if command == 'shadow' else 'NORMAL', binding=binding)
    if command == 'shadow':
        return shadow(service, binding)
    service.run()
    return dict(state='STOPPED', financial=export_state(), paper_only=True, real_money_authority=False)


def main(argv=None):
    from meme_machine.shared_capital.model import CapitalError
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'status', 'shadow', 'run', 'native-child'))
    args = parser.parse_args(argv)
    if args.command == 'native-child':
        native_child()
        return 2
    try:
        result = prepare() if args.command == 'prepare' else status() if args.command == 'status' else runtime(args.command)
    except (SimulatorFailure, CapitalError, OSError, ValueError, RuntimeError,
            sqlite3.Error, subprocess.SubprocessError) as error:
        reason = str(error) if type(error) is SimulatorFailure else 'SIMULATOR_STATE_UNAVAILABLE'
        result = dict(state='REFUSED', reason=reason, paper_only=True, real_money_authority=False)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 2 if result['state'] in ('REFUSED', 'BLOCKED') else 0


if __name__ == '__main__':
    raise SystemExit(main())
