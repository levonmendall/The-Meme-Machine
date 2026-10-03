"""Nonmaterial evidence collector. Calls the unchanged approved resource inspector."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

sys.dont_write_bytecode = True
APPROVED = 'f480c6b4f7a8442fd148c7ed61bcc4447edaefca'
PREFLIGHT = 'native-v3-a-preflight-20261003T112100Z'
HOST = 'ubuntu-gd-2vcpu-8gb-nyc1'
MOUNT = Path('/mnt/volume_nyc1_1790918115030')
OUTPUT = None
RESULT = dict(version='fresh-native-v3-A-host-preflight', preflight_id=PREFLIGHT,
    paper_only=True, execution_authorized=False, actual_slots_reserved=False,
    source_frames_released=0, A_slots_consumed=0, A_trials_started=0,
    B_started=False, C_started=False, stage_e='RED', stage_f='NOT STARTED',
    approved_executable_commit=APPROVED, campaign_created=False,
    resource_configuration_mutations=0)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(8*1024**2), b''):
            h.update(block)
    return h.hexdigest()

def require(condition, reason):
    if not condition:
        raise ValueError(reason)

def save(name, value):
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    path = OUTPUT/name
    with path.open('xb') as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())
    fd = os.open(OUTPUT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return dict(path=name, bytes=len(data), sha256=sha(data))

def command(argv):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    return dict(argv=argv, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)

def durability_capability():
    # A bounded capability probe in a separate evidence directory, never an A/B/C
    # trial or application database. No candidate or workload module is imported.
    import sqlite3
    folder = OUTPUT.parent/(PREFLIGHT+'-storage-capability')
    folder.mkdir(exist_ok=False)
    path = folder/'capability.sqlite'
    first = sqlite3.connect(path,timeout=0)
    second = None
    proof = dict(version='fresh-storage-capability-only',path=str(path),sqlite_version=sqlite3.sqlite_version,
        probe_rows=1,source_frames_released=0,A_trials_started=0)
    try:
        proof['journal_mode'] = first.execute('PRAGMA journal_mode=WAL').fetchone()[0]
        first.execute('PRAGMA synchronous=FULL')
        proof['synchronous'] = first.execute('PRAGMA synchronous').fetchone()[0]
        first.execute('CREATE TABLE capability (value INTEGER NOT NULL)')
        first.execute('INSERT INTO capability VALUES (1)')
        first.commit()
        second = sqlite3.connect(path,timeout=0)
        proof['separate_connection_readback'] = second.execute('SELECT value FROM capability').fetchall()
        first.execute('BEGIN IMMEDIATE')
        try:
            second.execute('BEGIN IMMEDIATE')
            proof['second_writer_excluded'] = False
        except sqlite3.OperationalError as exc:
            proof['second_writer_excluded'] = str(exc) == 'database is locked'
            proof['second_writer_error'] = str(exc)
        first.rollback()
        proof['files'] = []
        for p in sorted(folder.iterdir()):
            fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            proof['files'].append(dict(path=str(p),bytes=p.stat().st_size,sha256=file_sha(p),fsync_returned=True))
        fd=os.open(folder,os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        proof['directory_fsync_returned'] = True
        require(proof['journal_mode']=='wal' and proof['synchronous']==2
            and proof['separate_connection_readback']==[(1,)] and proof['second_writer_excluded'],
            'SQLite_WAL_locking_capability_failed')
    finally:
        if second is not None:
            second.close()
        first.close()
    proof['closed_database_sha256'] = file_sha(path)
    proof['closed_database_bytes'] = path.stat().st_size
    save('STORAGE_CAPABILITY.json',proof)

def main():
    global OUTPUT
    require(socket.gethostname() == HOST, 'actual_executor_hostname_mismatch')
    require(os.environ.get('RUNNER_NAME') == 'the meme machine', 'actual_runner_mismatch')
    require(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'preflight_rerun_forbidden')
    require(MOUNT.is_dir() and not MOUNT.is_symlink(), 'durable_volume_unavailable')
    parent = MOUNT/'stage-e-native-v3-paper-preflight'
    parent.mkdir(exist_ok=True)
    OUTPUT = parent/PREFLIGHT
    OUTPUT.mkdir(exist_ok=False)
    save('SCOPE.json', RESULT)
    repo = Path(os.environ['MM_APPROVED_REPOSITORY']).resolve()
    require(subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip() == APPROVED,
            'approved_executable_commit_mismatch')
    package = repo/'diagnostics/stage-e-native-v3-executable-harness'
    contract = repo/'diagnostics/stage-e-native-v3-production-envelope-contract'
    require(file_sha(package/'package-manifest.json') == 'd0047922f45cc85599c25705616152005ab598d65343cb4482e983f34ebd6859',
            'approved_harness_manifest_changed')
    require(file_sha(contract/'package_sha256.json') == '786308bcfc18c88f1c5e97286c311766159d592b47a637d2c6ae6ff53ffd22f0',
            'approved_contract_manifest_changed')
    for label, manifest, base in [('harness',package/'package-manifest.json',repo),
                                 ('contract',contract/'package_sha256.json',contract)]:
        rows = json.loads(manifest.read_bytes())['artifacts']
        for row in rows:
            path = base/row['path']
            require(path.is_file() and not path.is_symlink() and path.stat().st_size == row['bytes']
                    and file_sha(path) == row['sha256'], label+'_artifact_changed:'+row['path'])
        save(label.upper()+'_READBACK.json', dict(manifest_sha256=file_sha(manifest),verified_entries=len(rows)))
    sys.path.insert(0, str(package/'harness'))
    import attest
    import binding
    import core
    identity = binding.infrastructure_identity()
    require(identity == json.loads((package/'source_hashes.json').read_bytes()), 'approved_infrastructure_changed')
    save('EXTERNAL_SOURCE_IDENTITY.json', identity)
    context = {k:os.environ.get(k) for k in ('GITHUB_REPOSITORY','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT',
        'GITHUB_SHA','GITHUB_EVENT_NAME','GITHUB_WORKFLOW_REF','GITHUB_WORKFLOW_SHA','RUNNER_NAME','RUNNER_OS','RUNNER_ARCH')}
    save('EXECUTOR_CONTEXT.json', dict(context=context,repository=str(repo),
        approved_commit=APPROVED,collector_sha256=file_sha(__file__),
        python=sys.executable,python_version=sys.version,uid=os.getuid(),gid=os.getgid()))
    registration = json.loads(Path('/opt/actions-runner/.runner').read_text(encoding='utf-8-sig'))
    registration = {k:registration.get(k) for k in ('agentId','agentName','poolId','poolName','gitHubUrl','workFolder')}
    save('RUNNER_REGISTRATION.json', registration)
    require(registration['agentId'] == 21 and registration['agentName'] == 'the meme machine', 'actual_runner_registration_mismatch')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    metadata = {}
    for name in ('id','hostname'):
        with opener.open('http://169.254.169.254/metadata/v1/'+name,timeout=5) as response:
            metadata[name] = response.read(4096).decode().strip()
    save('PROVIDER_GUEST_IDENTITY.json', metadata)
    require(metadata == dict(id='605465049',hostname=HOST), 'actual_droplet_mismatch')
    initial = attest.inspect([str(MOUNT)])
    save('RESOURCE_INITIAL.json', initial)
    raw = {}
    for name in ('/proc/cpuinfo','/proc/meminfo','/proc/self/status','/proc/self/limits','/proc/self/cgroup',
        '/proc/1/cgroup','/proc/self/mountinfo','/proc/1/mountinfo','/proc/modules','/proc/swaps',
        '/proc/stat','/proc/loadavg','/proc/diskstats','/etc/os-release'):
        raw[name] = Path(name).read_text()
    raw['commands'] = [command(argv) for argv in (
        ['lscpu','--json'], ['findmnt','--json','--list','--output','SOURCE,TARGET,FSTYPE,OPTIONS'],
        ['lsblk','--json','--bytes','--output','NAME,PATH,SIZE,MODEL,ROTA,TYPE,FSTYPE,LABEL,UUID,MOUNTPOINTS'],
        ['systemctl','list-units','--all','--type=service','--no-legend','--no-pager'],
        ['ps','-eo','pid,ppid,uid,nlwp,pcpu,pmem,stat,comm'])]
    raw['process_names'] = {}
    for row in initial['processes']:
        try:
            raw['process_names'][str(row['pid'])] = Path('/proc',str(row['pid']),'comm').read_text()
        except FileNotFoundError:
            raw['process_names'][str(row['pid'])] = 'EXITED_AFTER_SNAPSHOT'
    raw['block_devices'] = {}
    for device in Path('/sys/block').iterdir():
        row = {}
        for name in ('queue/write_cache','queue/fua','queue/rotational','queue/scheduler','device/model','device/vendor'):
            try:
                row[name] = (device/name).read_text()
            except FileNotFoundError:
                row[name] = None
        raw['block_devices'][device.name] = row
    save('RAW_MACHINE_EVIDENCE.json',raw)
    require(not initial['inspection_errors'], 'resource_inspection_incomplete:'+','.join(initial['inspection_errors']))
    ids = initial['cpu']['present']
    require(len(ids) == 2 and initial['cpu']['possible'] == initial['cpu']['online'] == initial['affinity'] == ids,
            'executor_allocation_larger_than_two_or_offline_CPUs')
    require(0 < initial['memory']['MemTotal'] <= core.RAM, 'usable_RAM_allocation_binding')
    require(initial['memory']['SwapTotal'] == 0, 'swap_is_not_RAM')
    require(initial['balloon_modules'] == [], 'ballooning')
    cg = initial['cgroup']
    require(not attest.cgroup_completeness_errors(cg) and cg['complete'], 'corrected_cgroup_inventory_incomplete')
    verified = attest.verified_cgroup_inventory(cg)
    save('CGROUP_VERIFICATION.json',dict(ancestor_inventory_sha256=core.sha(core.canonical(cg)),
        independently_verified=True,ancestor_count=len(cg['ancestors']),verified=verified))
    for row in cg['ancestors']:
        q,p = row.get('quota_us'),row.get('period_us')
        require(q is None or p and q >= 2*p, 'restrictive_ancestor_CPU_quota:'+row['path'])
        for name in ('cpuset','cpuset_effective'):
            require(not row.get(name) or set(ids).issubset(attest.cpus(row[name])), 'restrictive_ancestor_cpuset:'+row['path'])
        for name in ('memory_max','memory_high','memsw_max'):
            require(row.get(name) is None or row[name] >= core.RAM, 'restrictive_ancestor_'+name+':'+row['path'])
    require(all(row['free_bytes'] >= core.HEADROOM for row in initial['storage']), 'insufficient_storage_headroom')
    require(all(row['fs_type']=='ext4' and 'rw' in row['options'].split(',') for row in initial['storage']),
            'nondurable_or_readonly_storage')
    durability_capability()
    final = attest.inspect([str(MOUNT)])
    save('RESOURCE_FINAL.json',final)
    require(not final['inspection_errors'] and attest.constraint_identity(initial) == attest.constraint_identity(final),
            'resource_constraints_changed_during_inspection')
    RESULT.update(status='HOST_FACTS_COMPLETE_REQUIRES_SIGNED_ALLOCATION_AND_REMAINING_CHECKS',
        boot_id=initial['boot_id'],hostname=initial['hostname'],visible_cpu_ids=ids,
        usable_ram_bytes=initial['memory']['MemTotal'],
        ancestor_inventory_sha256=core.sha(core.canonical(cg)))
    RESULT['preflight_parent_shell_pid'] = os.getppid()

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        RESULT.update(status='STAGE_E_NATIVE_V3_A_PREFLIGHT_BLOCKED',blocker_type=type(exc).__name__,blocker=str(exc))
    finally:
        if OUTPUT is not None:
            RESULT['retained_executor_evidence_path'] = str(OUTPUT)
            save('HOST_RESULT.json',RESULT)
            rows = [dict(path=p.name,bytes=p.stat().st_size,sha256=file_sha(p)) for p in sorted(OUTPUT.iterdir()) if p.is_file()]
            save('HOST_EVIDENCE_MANIFEST.json',dict(artifacts=rows,execution_authorized=False,source_frames_released=0,A_slots_consumed=0))
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'],'a') as target:
                    target.write('evidence_path='+str(OUTPUT)+'\n')
        print(json.dumps(RESULT,sort_keys=True))
