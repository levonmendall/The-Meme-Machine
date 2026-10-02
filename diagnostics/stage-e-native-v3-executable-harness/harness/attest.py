"""Read-only Linux observation and fail-closed, authenticated envelope admission.

Affinity and quota are constraints, never allocation evidence. A provider/owner
allocation document must be signed by a separately trusted, predeclared key.
No CPU benchmark, disk write probe, provider call or workload runs here.
"""
import base64
from fractions import Fraction
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time

from core import HEADROOM, RAM, REAL_NS, REAL_UTC_NS, canonical, file_sha, read, require, sha
from preserve import fsync_dir, persist


def cpus(value):
    result = set()
    for item in value.strip().split(','):
        if not item:
            continue
        edges = item.split('-')
        require(len(edges) <= 2, 'invalid_cpuset')
        lo, hi = int(edges[0]), int(edges[-1])
        require(0 <= lo <= hi < 1048576, 'invalid_cpuset_range')
        result.update(range(lo, hi+1))
    return sorted(result)


def _text(path):
    return Path(path).read_text().strip()


def signed_document(path, key, key_sha256):
    """Verify canonical payload with OpenSSL; a self-asserted verified flag is ignored."""
    require(file_sha(key) == key_sha256, 'attestation_trust_key_changed')
    envelope = read(path)
    require(set(envelope) == {'payload', 'signature_base64'}, 'signed_document_schema')
    signature = base64.b64decode(envelope['signature_base64'], validate=True)
    with tempfile.TemporaryDirectory(prefix='v3-signature-') as folder:
        payload_path, signature_path = Path(folder)/'payload', Path(folder)/'signature'
        payload_path.write_bytes(canonical(envelope['payload']))
        signature_path.write_bytes(signature)
        result = subprocess.run(['openssl', 'dgst', '-sha256', '-verify', str(Path(key).resolve()),
                                 '-signature', str(signature_path), str(payload_path)],
                                capture_output=True, timeout=10, check=False)
    require(result.returncode == 0, 'unauthenticated_allocation_or_permission')
    return envelope['payload']


def mount_inventory(path):
    target = Path(path).resolve()
    choices = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        sep = fields.index('-')
        unescape = lambda value: value.replace('\\040', ' ').replace('\\011', '\t').replace('\\134', '\\')
        mount = Path(unescape(fields[4]))
        if target == mount or target.is_relative_to(mount):
            choices.append(dict(mount_id=int(fields[0]), parent_id=int(fields[1]),
                device=fields[2], root=unescape(fields[3]), mount=str(mount), options=fields[5],
                fs_type=fields[sep+1], source=unescape(fields[sep+2]), super_options=fields[sep+3]))
    require(choices, 'storage_mount_unknown')
    row = max(choices, key=lambda r: len(Path(r['mount']).parts))
    info = os.statvfs(target)
    return dict(row, path=str(target), st_dev=os.stat(target).st_dev,
                free_bytes=info.f_bavail*info.f_frsize, total_bytes=info.f_blocks*info.f_frsize,
                block_bytes=info.f_frsize)


def _ancestors(current, root):
    require(current.is_relative_to(root), 'cgroup_escape')
    result = []
    while True:
        result.append(current)
        if current == root:
            break
        current = current.parent
    return result


def cgroup_inventory(pid):
    memberships = []
    for line in Path(f'/proc/{pid}/cgroup').read_text().splitlines():
        hierarchy, controllers, name = line.split(':', 2)
        require(name.startswith('/') and '..' not in Path(name).parts, 'hidden_cgroup_ancestor')
        memberships.append((hierarchy, controllers.split(',') if controllers else [], name))
    mounts = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split(); sep = fields.index('-')
        if fields[sep+1] in ('cgroup', 'cgroup2'):
            mounts.append((fields[sep+1], fields[3], Path(fields[4]), fields[sep+3].split(',')))
    result = []
    complete = True
    for hierarchy, controllers, name in memberships:
        matches = [m for m in mounts if m[0] == ('cgroup' if controllers else 'cgroup2')
                   and (not controllers or set(controllers).issubset(m[3]))]
        if len(matches) != 1:
            complete = False
            continue
        version, mount_root, root, _ = matches[0]
        # A delegated subtree mount cannot establish omitted ancestor quotas.
        if mount_root != '/':
            complete = False
            continue
        for folder in _ancestors(root / name.lstrip('/'), root):
            row = dict(version=version, controllers=controllers, membership=name,
                       path=str(folder), mount_root=mount_root)
            def optional(file):
                p = folder/file
                return _text(p) if p.exists() else None
            if version == 'cgroup2':
                raw = optional('cpu.max')
                row['cpu_max_raw'] = raw
                row['quota_us'], row['period_us'] = ((None if raw.split()[0] == 'max' else int(raw.split()[0]),
                                                      int(raw.split()[1])) if raw else (None, None))
                row['cpuset'] = optional('cpuset.cpus')
                row['cpuset_effective'] = optional('cpuset.cpus.effective')
                for name_, file in [('memory_max', 'memory.max'), ('memory_high', 'memory.high'),
                                    ('swap_max', 'memory.swap.max')]:
                    raw = optional(file)
                    row[name_] = None if raw in (None, 'max') else int(raw)
                    row[name_+'_raw'] = raw
            else:
                raw = optional('cpu.cfs_quota_us')
                row['quota_us'] = None if raw in (None, '-1') else int(raw)
                raw_period = optional('cpu.cfs_period_us')
                row['period_us'] = int(raw_period) if raw_period else None
                row['cpuset'] = optional('cpuset.cpus')
                row['cpuset_effective'] = optional('cpuset.effective_cpus') or row['cpuset']
                for name_, file in [('memory_max', 'memory.limit_in_bytes'),
                                    ('memory_high', 'memory.soft_limit_in_bytes'),
                                    ('memsw_max', 'memory.memsw.limit_in_bytes')]:
                    raw = optional(file)
                    row[name_] = None if raw is None or int(raw) >= 2**60 else int(raw)
                    row[name_+'_raw'] = raw
            result.append(row)
    if not result:
        complete = False
    cpu_rows = [r for r in result if r['period_us'] is not None]
    cpuset_rows = [r for r in result if r['cpuset_effective']]
    memory_rows = [r for r in result if r.get('memory_max_raw') is not None]
    # Root-only v2 may have no controllers enabled: limits are unrestricted
    # within the independently authenticated VM allocation.
    unified_root = len(result) == 1 and result[0]['version'] == 'cgroup2' and result[0]['membership'] == '/'
    complete = complete and (bool(cpu_rows and cpuset_rows and memory_rows) or unified_root)
    return dict(complete=complete, memberships=[list(m) for m in memberships], ancestors=result,
                namespace=os.readlink(f'/proc/{pid}/ns/cgroup'),
                pid1_namespace=os.readlink('/proc/1/ns/cgroup'))


def process_inventory():
    """All tasks in the measured executor, including threads; no arguments/env."""
    result = []
    for path in sorted(Path('/proc').iterdir()):
        if not path.name.isdecimal():
            continue
        try:
            status = _text(path/'stat')
            rest = status[status.rfind(')')+2:].split()
            row = dict(pid=int(path.name), ppid=int(rest[1]), process_group=int(rest[2]),
                       state=rest[0], start_ticks=int(rest[19]))
            exe = path/'exe'
            if exe.exists():
                actual = exe.resolve(strict=True)
                row.update(executable=str(actual), executable_sha256=file_sha(actual), kernel=False)
            else:
                row.update(executable=None, executable_sha256=None, kernel=True)
            row['threads'] = []
            for task in sorted((path/'task').iterdir()):
                tid = int(task.name)
                row['threads'].append(dict(tid=tid, affinity=sorted(os.sched_getaffinity(tid)),
                    cgroup_sha256=file_sha(task/'cgroup')))
            result.append(row)
        except FileNotFoundError:
            continue  # Exits are reconciled with mandatory child teardown receipts.
        except ProcessLookupError:
            continue
    return result


def inspect(paths, scope_pid=None):
    scope_pid = scope_pid or os.getpid()
    visible = {name: cpus(_text('/sys/devices/system/cpu/'+name)) for name in ('possible', 'present', 'online')}
    topology = []
    for cpu in visible['present']:
        folder = Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
        topology.append(dict(cpu=cpu, core_id=_text(folder/'core_id'),
                             package_id=_text(folder/'physical_package_id'),
                             thread_siblings=_text(folder/'thread_siblings_list')))
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            memory[key] = int(value.strip().split()[0]) * 1024
    errors = []
    try:
        groups = cgroup_inventory(scope_pid)
        if not groups['complete']:
            errors.append('complete_cgroup_inventory_unavailable')
    except (OSError, ValueError) as exc:
        errors.append('cgroup:'+type(exc).__name__+':'+str(exc))
        groups = dict(complete=False, ancestors=[], memberships=[], namespace=None, pid1_namespace=None)
    try:
        processes = process_inventory()
    except (OSError, ValueError) as exc:
        errors.append('process_inventory:'+type(exc).__name__+':'+str(exc))
        processes = []
    try:
        balloon_modules = [line.split()[0] for line in Path('/proc/modules').read_text().splitlines()
                           if 'balloon' in line.split()[0]]
    except OSError as exc:
        errors.append('balloon_inventory:'+type(exc).__name__)
        balloon_modules = None
    return dict(version='v3-linux-resource-snapshot', real_monotonic_ns=REAL_NS(),
        real_utc_ns=REAL_UTC_NS(), boot_id=_text('/proc/sys/kernel/random/boot_id'),
        hostname=socket.gethostname(), scope_pid=scope_pid, cpu=visible, topology=topology,
        affinity=sorted(os.sched_getaffinity(scope_pid)), memory=memory,
        cgroup=groups, scope_cgroup_sha256=file_sha(f'/proc/{scope_pid}/cgroup'),
        processes=processes, inspection_errors=errors,
        storage=[mount_inventory(path) for path in paths],
        balloon_modules=balloon_modules)


def constraint_identity(snapshot):
    return {key: snapshot[key] for key in ('boot_id', 'hostname', 'cpu', 'topology', 'affinity', 'cgroup', 'balloon_modules')}


def reserve_storage(snapshot, bounds, *, member=None):
    """Existing tape/evidence is already reflected in statvfs free bytes.

    Before preparation reserve the complete new working/publication budgets;
    before each member reserve its declared new bytes and publication budget.
    The continuous admission predicate separately retains 12 GiB headroom.
    """
    work = bounds['working_bytes'] if member is None else bounds['member_working_bytes'].get(member)
    require(type(work) is int and work > 0, 'missing_member_storage_reservation')
    require(type(bounds['publication_copy_bytes']) is int and bounds['publication_copy_bytes'] > 0,
            'missing_publication_storage_reservation')
    required = HEADROOM + work + bounds['publication_copy_bytes']
    require(snapshot['storage'] and all(p['free_bytes'] >= required for p in snapshot['storage']),
            'insufficient_free_reserved_work_and_publication_space')
    return dict(member=member,free_bytes=[p['free_bytes'] for p in snapshot['storage']],
                working_bytes=work,publication_copy_bytes=bounds['publication_copy_bytes'],
                headroom_bytes=HEADROOM,required_free_bytes=required)


def admission_errors(snapshot, allocation, storage_bounds, runtime, *, scope_pids=(), evidence_files=None):
    """Pure verifier; signature validation must precede this function."""
    errors = []
    def check(value, reason):
        if not value:
            errors.append(reason)
    a = allocation.get('allocation', {})
    check(snapshot.get('inspection_errors', []) == [], 'incomplete_resource_inspection')
    for key, value in [('allocated_vcpu', 2), ('dedicated_vcpu', 2), ('ram_bytes', RAM)]:
        check(type(a.get(key)) is int and a[key] == value, 'allocation_'+key)
    ids = snapshot['cpu']['present']
    check(len(ids) == 2 and snapshot['cpu']['possible'] == snapshot['cpu']['online'] == ids,
          'executor_allocation_larger_than_two_or_offline_CPUs')
    check(a.get('visible_cpu_ids') == ids and snapshot['affinity'] == ids, 'visible_cpu_affinity_binding')
    check(a.get('executor_kind') in ('dedicated-vm', 'dedicated-bare-metal'), 'dedicated_executor_kind')
    check(a.get('ballooning') is False and not snapshot['balloon_modules'], 'ballooning')
    check(a.get('swap') is False and snapshot['memory']['SwapTotal'] == 0, 'swap_is_not_RAM')
    check(a.get('competing_workload') is False, 'dedication_capability')
    check(allocation.get('boot_id') == snapshot['boot_id'] and allocation.get('hostname') == snapshot['hostname'],
          'allocation_host_binding')
    now = snapshot['real_utc_ns']
    check(type(allocation.get('valid_from_utc_ns')) is int and type(allocation.get('expires_utc_ns')) is int
          and allocation['valid_from_utc_ns'] <= now < allocation['expires_utc_ns'], 'allocation_expired')
    usable = snapshot['memory']['MemTotal']
    check(0 < usable <= RAM and allocation.get('usable_ram_bytes') == usable, 'usable_RAM_allocation_binding')
    cg = snapshot['cgroup']
    check(cg['complete'] is True and cg['namespace'] == cg['pid1_namespace']
          and allocation.get('ancestor_inventory_sha256') == sha(canonical(cg)), 'hidden_or_changed_cgroup_ancestors')
    for row in cg['ancestors']:
        period, quota = row['period_us'], row['quota_us']
        check(quota is None or type(period) is int and period > 0 and Fraction(quota, period) >= 2,
              'restrictive_ancestor_CPU_quota')
        for field in ('cpuset', 'cpuset_effective'):
            check(not row[field] or set(ids).issubset(cpus(row[field])), 'restrictive_ancestor_cpuset')
        for field in ('memory_max', 'memory_high', 'memsw_max'):
            limit = row.get(field)
            check(limit is None or type(limit) is int and limit >= RAM, 'restrictive_ancestor_'+field)
    check(bool(allocation.get('allocation_evidence')), 'allocation_capability_evidence_missing')
    for receipt in allocation.get('allocation_evidence', []):
        actual_path = (evidence_files or {}).get(receipt.get('path'),receipt.get('path',''))
        check(set(receipt) == {'path', 'sha256'} and Path(actual_path).is_file()
              and file_sha(actual_path) == receipt['sha256'], 'capability_evidence_bytes')
    check(runtime.get('python') == '3.12.14' and runtime.get('machine') == 'x86_64'
          and runtime.get('dependencies', {}).get('websockets', {}).get('version') == '17.1', 'runtime_identity')
    check(storage_bounds.get('headroom_bytes') == HEADROOM, 'headroom_cannot_change')
    required = HEADROOM + sum(storage_bounds.get(key, -HEADROOM) for key in
                              ('immutable_tape_bytes', 'working_bytes', 'retained_evidence_bytes', 'publication_copy_bytes'))
    check(all(type(storage_bounds.get(key)) is int and storage_bounds[key] >= 0 for key in
              ('immutable_tape_bytes','working_bytes','retained_evidence_bytes','publication_copy_bytes')),
          'malformed_storage_reserves')
    check(storage_bounds.get('working_bytes',0)>0 and storage_bounds.get('publication_copy_bytes',0)>0,
          'working_and_publication_reserves_missing')
    check(storage_bounds.get('immutable_tape_bytes') == 2442975789 and required >= HEADROOM + 2442975789,
          'storage_reserve_not_frozen')
    require_storage = storage_bounds.get('requirements', [])
    check(len(require_storage) == len(snapshot['storage']) and bool(require_storage), 'storage_all_paths_bound')
    signed_mounts = allocation.get('durable_mounts', [])
    for row, bound in zip(snapshot['storage'], require_storage):
        check(row['path'] == bound.get('path') and row['total_bytes'] >= required
              and row['free_bytes'] >= HEADROOM and row['total_bytes'] >= bound.get('minimum_total_bytes', required),
              'storage_capacity_or_headroom')
        check(row['fs_type'] not in ('tmpfs', 'ramfs', 'overlay', 'nfs', 'nfs4', 'cifs', 'fuse')
              and 'rw' in row['options'].split(','), 'nondurable_or_readonly_storage')
        check(any(r.get('device') == row['device'] and r.get('mount') == row['mount']
                  and r.get('file_and_directory_fsync') is True and r.get('sqlite_WAL_locking') is True
                  and r.get('physical_durability') is True for r in signed_mounts), 'durability_capability_unattested')
    processes = snapshot['processes']
    scope = set(scope_pids) | {snapshot['scope_pid']}
    while True:
        expanded = scope | {p['pid'] for p in processes if p['ppid'] in scope}
        if expanded == scope:
            break
        scope = expanded
    system = {(r['pid'], r['start_ticks'], r['executable_sha256']) for r in allocation.get('system_processes', [])}
    for row in processes:
        if row['kernel']:
            continue
        if row['pid'] in scope:
            check(row['executable_sha256'] in {runtime.get('python_executable_hash')} |
                  {r['sha256'] for r in runtime.get('os_tools', {}).values()}, 'unbound_executable_in_scope')
            for task in row['threads']:
                check(task['affinity'] == ids, 'child_or_thread_affinity')
                check(task['cgroup_sha256'] == snapshot['scope_cgroup_sha256'], 'child_or_thread_cgroup_escape')
        else:
            check((row['pid'], row['start_ticks'], row['executable_sha256']) in system, 'competing_or_unattested_process')
    return sorted(set(errors))


class ResourceMonitor:
    """Common .25s budget observation, with mandatory per-child/thread admission."""
    def __init__(self, output, paths, allocation, bounds, runtime, scope_pid=None):
        self.output = Path(output)
        self.paths, self.allocation, self.bounds, self.runtime = paths, allocation, bounds, runtime
        self.scope_pid = scope_pid or os.getpid()
        self.stop = threading.Event()
        self.errors = []
        self.previous = '0'*64
        self.first_constraints = None
        self.ordinal = 0
        self.thread = None
        self.closed = False
        self.known_pids = {}

    def sample(self, boundary):
        row = inspect(self.paths, self.scope_pid)
        scope = {self.scope_pid}
        while True:
            expanded = scope | {p['pid'] for p in row['processes'] if p['ppid'] in scope}
            if expanded == scope:
                break
            scope = expanded
        self.known_pids.update({p['pid']: p['start_ticks'] for p in row['processes'] if p['pid'] in scope})
        failures = admission_errors(row, self.allocation, self.bounds, self.runtime)
        identity = sha(canonical(constraint_identity(row)))
        if self.first_constraints is None:
            self.first_constraints = identity
        elif identity != self.first_constraints:
            failures.append('resource_constraints_changed_during_execution')
        self.errors.extend(failures)
        self.ordinal += 1
        raw = dict(ordinal=self.ordinal, previous=self.previous, boundary=boundary,
                   snapshot=row, errors=failures, constraints_sha256=identity)
        self.previous = sha(canonical(raw))
        persist(self.output / f'RESOURCE-{self.ordinal:06d}.json', dict(raw, sha256=self.previous))
        require(not failures, 'production_envelope:' + ','.join(failures))
        return row

    def start(self):
        self.sample('admission')
        def loop():
            while not self.stop.wait(.25):
                try:
                    self.sample('continuous')
                except Exception as exc:
                    self.errors.append(type(exc).__name__+':'+str(exc))
                    return
        self.thread = threading.Thread(target=loop, name='v3-resource-monitor')
        self.thread.start()

    def close(self):
        if self.closed:
            return
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
            require(not self.thread.is_alive(), 'resource_monitor_shutdown')
        self.sample('teardown')
        self.closed = True
        require(not self.errors, 'resource_timeline_invalid')
