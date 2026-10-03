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


V2_INTERFACES = ('cgroup.controllers', 'cgroup.subtree_control', 'cgroup.type',
                 'cpu.max', 'cpu.weight', 'cpuset.cpus', 'cpuset.cpus.effective',
                 'memory.max', 'memory.high', 'memory.swap.max')
V1_INTERFACES = ('cpu.cfs_quota_us', 'cpu.cfs_period_us', 'cpuset.cpus',
                 'cpuset.effective_cpus', 'memory.limit_in_bytes',
                 'memory.soft_limit_in_bytes', 'memory.memsw.limit_in_bytes')
# Linux cgroup-v2 documents these interfaces as non-root-only. This annotation
# never replaces ABSENT evidence or proof that the observed root is the true root.
V2_ROOT_EXCEPTIONS = ('cgroup.type', 'cpu.max', 'cpu.weight', 'cpuset.cpus',
                      'memory.max', 'memory.high', 'memory.swap.max')


def _interface(path):
    try:
        return dict(state='PRESENT', raw=Path(path).read_text())
    except FileNotFoundError:
        return dict(state='ABSENT')
    except OSError as exc:
        return dict(state='UNREADABLE', error=type(exc).__name__+':'+str(exc))


def _raw(interface):
    require(interface.get('state') == 'PRESENT' and type(interface.get('raw')) is str,
            'unreadable_or_missing_cgroup_interface')
    return interface['raw'].strip()


def _memberships(raw):
    rows = []
    for line in raw.splitlines():
        hierarchy, controllers, name = line.split(':', 2)
        require(hierarchy.isdecimal() and name.startswith('/') and '..' not in Path(name).parts
                and str(Path(name)) == name, 'hidden_cgroup_ancestor')
        controls = controllers.split(',') if controllers else []
        require(len(set(controls)) == len(controls) and bool(controls) == (int(hierarchy) != 0),
                'invalid_cgroup_membership')
        rows.append([hierarchy, controls, name])
    require(rows and len({r[0] for r in rows}) == len(rows), 'missing_or_duplicate_cgroup_membership')
    return rows


def _cgroup_mounts(raw):
    rows = []
    for line in raw.splitlines():
        fields = line.split(); sep = fields.index('-')
        if fields[sep+1] in ('cgroup', 'cgroup2'):
            unescape = lambda s: s.replace('\\040', ' ').replace('\\011', '\t').replace('\\134', '\\')
            rows.append(dict(version=fields[sep+1], root=unescape(fields[3]),
                mount=unescape(fields[4]), device=fields[2], mount_id=int(fields[0]),
                controllers=fields[sep+3].split(','), raw=line))
    return rows


def _matching_mount(mounts, controllers):
    matches = [m for m in mounts if m['version'] == ('cgroup' if controllers else 'cgroup2')
               and (not controllers or set(controllers).issubset(m['controllers']))]
    require(len(matches) == 1, 'missing_or_ambiguous_cgroup_mount')
    mount = matches[0]
    require(mount['root'] == '/' and Path(mount['mount']).is_absolute(), 'hidden_cgroup_mount_root')
    return mount


def _parsed_limits(row):
    """Compatibility columns are derived from explicit raw states, never authority."""
    files, v2 = row['interfaces'], row['version'] == 'cgroup2'
    def optional(name):
        return _raw(files[name]) if files[name]['state'] == 'PRESENT' else None
    fields = dict(quota_us=None, period_us=None, cpuset=optional('cpuset.cpus'))
    if v2:
        raw = optional('cpu.max'); fields['cpu_max_raw'] = raw
        if raw is not None:
            parts = raw.split()
            require(len(parts) == 2 and parts[1].isdecimal() and int(parts[1]) > 0
                    and (parts[0] == 'max' or parts[0].isdecimal() and int(parts[0]) > 0),
                    'invalid_cpu_max')
            fields.update(quota_us=None if parts[0] == 'max' else int(parts[0]), period_us=int(parts[1]))
        fields['cpuset_effective'] = optional('cpuset.cpus.effective')
        memory_files = [('memory_max', 'memory.max'), ('memory_high', 'memory.high'),
                        ('swap_max', 'memory.swap.max')]
    else:
        raw, period = optional('cpu.cfs_quota_us'), optional('cpu.cfs_period_us')
        fields.update(quota_us=None if raw in (None, '-1') else int(raw),
                      period_us=int(period) if period is not None else None)
        require(fields['quota_us'] is None or fields['quota_us'] > 0, 'invalid_cpu_quota')
        require(fields['period_us'] is None or fields['period_us'] > 0, 'invalid_cpu_period')
        fields['cpuset_effective'] = optional('cpuset.effective_cpus') or fields['cpuset']
        memory_files = [('memory_max', 'memory.limit_in_bytes'),
                        ('memory_high', 'memory.soft_limit_in_bytes'), ('memsw_max', 'memory.memsw.limit_in_bytes')]
    for field, name in memory_files:
        raw = optional(name)
        require(raw is None or raw == 'max' and v2 or raw.isdecimal(), 'invalid_memory_limit')
        fields[field+'_raw'] = raw
        fields[field] = None if raw is None or raw == 'max' or not v2 and int(raw) >= 2**60 else int(raw)
    for field in ('cpuset', 'cpuset_effective'):
        if fields[field] is not None:
            cpus(fields[field])
    return fields


def verified_cgroup_inventory(groups):
    """Pure completeness proof. Captured complete/applicability flags are not proof.

    A node's incoming controller is governed by its parent's subtree_control;
    disabling the node's outgoing propagation never excuses its own limits.
    """
    require(groups.get('version') == 'v3-cgroup-controller-evidence', 'cgroup_controller_evidence_missing')
    for key in ('namespace', 'mount_namespace'):
        value = groups.get(key)
        require(type(value) is str and value and value == groups.get('pid1_'+key)
                == groups.get('reader_'+key), 'cgroup_namespace_visibility_mismatch')
    files = groups['visibility_interfaces']
    memberships = _memberships(_raw(files['membership']))
    require(groups['memberships'] == memberships, 'contradictory_cgroup_membership')
    pid1 = _memberships(_raw(files['pid1_membership']))
    require([r[:2] for r in pid1] == [r[:2] for r in memberships], 'hidden_cgroup_hierarchy')
    mounts = _cgroup_mounts(_raw(files['mountinfo']))
    require(mounts == _cgroup_mounts(_raw(files['pid1_mountinfo'])), 'cgroup_mount_visibility_mismatch')
    remaining = list(groups['ancestors']); verified = []; observed_mounts = set()
    for _, controllers, name in memberships:
        mount = _matching_mount(mounts, controllers)
        observed_mounts.add(mount['mount_id'])
        root = Path(mount['mount'])
        expected = list(reversed(_ancestors(root/name.lstrip('/'), root)))
        parent_enabled = None
        for folder in expected:
            matches = [r for r in remaining if r.get('path') == str(folder)
                       and r.get('membership') == name and r.get('controllers') == controllers]
            require(len(matches) == 1, 'hidden_or_duplicate_cgroup_ancestor')
            row = matches[0]; remaining.remove(row)
            is_root = folder == root
            require(row['version'] == mount['version'] and row['mount_root'] == '/'
                    and row['cgroup_path'] == ('/' if is_root else '/' + folder.relative_to(root).as_posix())
                    and row['namespace'] == groups['namespace'], 'contradictory_cgroup_ancestor_identity')
            directory = row['directory']
            require(directory.get('state') == 'PRESENT' and type(directory.get('inode')) is int
                    and directory['inode'] > 0
                    and f"{os.major(directory['device'])}:{os.minor(directory['device'])}" == mount['device'],
                    'unreadable_or_changed_cgroup_directory')
            if row['version'] == 'cgroup2':
                require(not is_root or directory['inode'] == 1, 'hidden_cgroup_root_directory')
                interfaces = row['interfaces']
                require(set(interfaces) == set(V2_INTERFACES), 'missing_cgroup_interface_evidence')
                available = _raw(interfaces['cgroup.controllers']).split()
                enabled = _raw(interfaces['cgroup.subtree_control']).split()
                require(len(set(available)) == len(available) and len(set(enabled)) == len(enabled)
                        and all(t.replace('_', '').isalnum() for t in available+enabled)
                        and set(enabled).issubset(available), 'contradictory_controller_enablement')
                require(is_root or set(available) == parent_enabled, 'inconsistent_ancestor_enablement')
                exceptions = list(V2_ROOT_EXCEPTIONS) if is_root else []
                require(row.get('root_exceptions') == exceptions, 'invalid_cgroup_root_exception')
                for field in exceptions:
                    require(interfaces[field] == {'state': 'ABSENT'}, 'impossible_cgroup_root_interface')
                if not is_root:
                    require(_raw(interfaces['cgroup.type']) == 'domain', 'unsupported_cgroup_domain')
                applicability = {'cpu': ('cpu.max', 'cpu.weight'),
                                 'cpuset': ('cpuset.cpus', 'cpuset.cpus.effective'),
                                 'memory': ('memory.max', 'memory.high', 'memory.swap.max')}
                for controller, names in applicability.items():
                    for field in names:
                        if field in exceptions:
                            continue
                        if controller in available:
                            value = _raw(interfaces[field])
                            if field == 'cpuset.cpus.effective':
                                require(bool(cpus(value)), 'missing_effective_cpuset')
                            if field == 'cpu.weight':
                                require(value.isdecimal() and 1 <= int(value) <= 10000, 'invalid_cpu_weight')
                        else:
                            require(interfaces[field] == {'state': 'ABSENT'}, 'unexplained_cgroup_interface_state')
                parent_enabled = set(enabled)
            else:
                require(row.get('root_exceptions') == [] and set(row['interfaces']) == set(V1_INTERFACES),
                        'invalid_legacy_cgroup_evidence')
                # Preserve v1's explicit CPU/cpuset/memory checks. An optional
                # old-kernel effective cpuset falls back to the explicit cpuset;
                # absent memsw is not RAM evidence (host swap is separately zero).
                required = {'cpu': ('cpu.cfs_quota_us', 'cpu.cfs_period_us'),
                            'cpuset': ('cpuset.cpus',),
                            'memory': ('memory.limit_in_bytes', 'memory.soft_limit_in_bytes')}
                for controller, names in required.items():
                    if controller in controllers:
                        for field in names:
                            require(bool(_raw(row['interfaces'][field])), 'missing_legacy_cgroup_limit')
                require(all(f.get('state') in ('PRESENT', 'ABSENT') for f in row['interfaces'].values()),
                        'unreadable_legacy_cgroup_interface')
            fields = _parsed_limits(row)
            require(all(k in row and type(row[k]) is type(v) and row[k] == v for k, v in fields.items()),
                    'contradictory_parsed_cgroup_limit')
            verified.append(dict(row, **fields))
    require(not remaining and verified, 'extra_or_missing_cgroup_ancestor')
    require(all(m['mount_id'] in observed_mounts for m in mounts
                if m['version'] == 'cgroup2' or {'cpu', 'cpuset', 'memory'}.intersection(m['controllers'])),
            'hidden_cgroup_controller_membership')
    if not any(r['version'] == 'cgroup2' for r in verified):
        require({'cpu', 'cpuset', 'memory'}.issubset({c for r in verified for c in r['controllers']}),
                'incomplete_legacy_controller_coverage')
    return verified


def cgroup_completeness_errors(groups):
    try:
        verified_cgroup_inventory(groups)
        return []
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        return ['cgroup_evidence:'+str(exc)]


def cgroup_inventory(pid):
    files = dict(membership=_interface(f'/proc/{pid}/cgroup'), pid1_membership=_interface('/proc/1/cgroup'),
                 mountinfo=_interface('/proc/self/mountinfo'), pid1_mountinfo=_interface('/proc/1/mountinfo'))
    memberships = _memberships(_raw(files['membership']))
    mounts = _cgroup_mounts(_raw(files['mountinfo']))
    groups = dict(version='v3-cgroup-controller-evidence', complete=False, memberships=memberships,
        ancestors=[], visibility_interfaces=files,
        namespace=os.readlink(f'/proc/{pid}/ns/cgroup'), pid1_namespace=os.readlink('/proc/1/ns/cgroup'),
        reader_namespace=os.readlink('/proc/self/ns/cgroup'),
        mount_namespace=os.readlink(f'/proc/{pid}/ns/mnt'), pid1_mount_namespace=os.readlink('/proc/1/ns/mnt'),
        reader_mount_namespace=os.readlink('/proc/self/ns/mnt'))
    for _, controllers, name in memberships:
        mount = _matching_mount(mounts, controllers); root = Path(mount['mount'])
        for folder in _ancestors(root/name.lstrip('/'), root):
            row = dict(version=mount['version'], controllers=controllers, membership=name, path=str(folder),
                cgroup_path='/' if folder == root else '/' + folder.relative_to(root).as_posix(), mount_root=mount['root'],
                namespace=groups['namespace'], root_exceptions=list(V2_ROOT_EXCEPTIONS)
                if mount['version'] == 'cgroup2' and folder == root else [])
            try:
                st = folder.stat(); row['directory'] = dict(state='PRESENT', inode=st.st_ino, device=st.st_dev)
            except OSError as exc:
                row['directory'] = dict(state='UNREADABLE', error=type(exc).__name__+':'+str(exc))
            row['interfaces'] = {f: _interface(folder/f) for f in
                                 (V2_INTERFACES if mount['version'] == 'cgroup2' else V1_INTERFACES)}
            try:
                row.update(_parsed_limits(row))
            except (ValueError, TypeError) as exc:
                row['parse_error'] = str(exc)
            groups['ancestors'].append(row)
    groups['complete'] = not cgroup_completeness_errors(groups)
    return groups


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
    evidence_errors = cgroup_completeness_errors(cg)
    errors.extend(evidence_errors)
    check(not evidence_errors and cg.get('complete') is True and cg.get('namespace') == cg.get('pid1_namespace')
          and allocation.get('ancestor_inventory_sha256') == sha(canonical(cg)), 'hidden_or_changed_cgroup_ancestors')
    for row in cg.get('ancestors', []):
        period, quota = row.get('period_us'), row.get('quota_us')
        check(quota is None or type(quota) is int and type(period) is int and period > 0 and Fraction(quota, period) >= 2,
              'restrictive_ancestor_CPU_quota')
        for field in ('cpuset', 'cpuset_effective'):
            check(not row.get(field) or set(ids).issubset(cpus(row[field])), 'restrictive_ancestor_cpuset')
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
