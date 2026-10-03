"""Paper-only native-v3 admission collection. No campaign or workload imports."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
PACKAGE = REPO / 'diagnostics/stage-e-native-v3-executable-harness'
MOUNT = Path('/mnt/volume_nyc1_1790918115030')
OLD = MOUNT / 'meme-machine-observer-v2-7a516a6a'
PREFLIGHT = 'native-v3-a-paper-20261003T030901Z'
EXPECTED_HOST = 'ubuntu-gd-2vcpu-8gb-nyc1'
CONTRACT_SHA = '786308bcfc18c88f1c5e97286c311766159d592b47a637d2c6ae6ff53ffd22f0'
HARNESS_SHA = 'b69d6cc95b478b03bafeeb4f7598abe668c141069fb58ebcea0e70ec6016926f'
RAM = 8 * 1024**3
HEADROOM = 12 * 1024**3
OUTPUT = None
RESULT = dict(preflight_id=PREFLIGHT, paper_only=True, stage_e='RED', stage_f='NOT_STARTED',
              execution_authorized=False, source_frames_released=0, started_A_trials=0,
              consumed_A_slots=0, B_started=False, C_started=False, campaign_created=False)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(8*1024**2), b''):
            h.update(b)
    return h.hexdigest()

def save(name, value):
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    path = OUTPUT / name
    with path.open('xb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    fd = os.open(OUTPUT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return dict(path=str(path), bytes=len(data), sha256=digest(data))

def require(condition, reason):
    if not condition:
        raise ValueError(reason)

def cmd(args):
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return dict(argv=args, returncode=r.returncode, stdout=r.stdout, stderr=r.stderr)

def main():
    global OUTPUT
    require(socket.gethostname() == EXPECTED_HOST, 'executor_hostname_mismatch')
    require(os.environ.get('RUNNER_NAME') == 'the meme machine', 'executor_runner_mismatch')
    require(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'inspection_rerun_forbidden')
    require(MOUNT.is_dir() and not MOUNT.is_symlink(), 'existing_durable_volume_unavailable')
    root = MOUNT / 'stage-e-native-v3-paper-preflight'
    root.mkdir(exist_ok=True)
    OUTPUT = root / PREFLIGHT
    OUTPUT.mkdir(exist_ok=False)
    save('SCOPE.json', RESULT)
    scope_env = {k: os.environ.get(k) for k in ('RUNNER_NAME','RUNNER_OS','RUNNER_ARCH',
          'RUNNER_WORKSPACE','RUNNER_TEMP','GITHUB_REPOSITORY','GITHUB_RUN_ID',
          'GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_EVENT_NAME','GITHUB_WORKFLOW_REF',
          'GITHUB_WORKFLOW_SHA')}
    save('EXECUTOR_CONTEXT.json', dict(environment=scope_env, uid=os.getuid(),
         gid=os.getgid(), hostname=socket.gethostname(), boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
         inspector_executable=sys.executable, inspector_version=sys.version,
         probe_path=str(HERE), probe_sha256=file_digest(HERE)))
    require(file_digest(PACKAGE/'package-manifest.json') == HARNESS_SHA, 'approved_harness_manifest_drift')
    contract = REPO/'diagnostics/stage-e-native-v3-production-envelope-contract'
    require(file_digest(contract/'package_sha256.json') == CONTRACT_SHA, 'approved_contract_manifest_drift')
    for label, manifest, base in [('harness', PACKAGE/'package-manifest.json', REPO),
                                 ('contract', contract/'package_sha256.json', contract)]:
        m = json.loads(manifest.read_bytes())
        for row in m['artifacts']:
            p = base/row['path']
            require(p.is_file() and not p.is_symlink() and p.stat().st_size == row['bytes']
                    and file_digest(p) == row['sha256'], label+'_artifact_drift:'+row['path'])
        save(label.upper()+'_PACKAGE_READBACK.json', dict(manifest_sha256=file_digest(manifest),
             verified_entries=len(m['artifacts']), no_repository_workload_code_executed=True))
    # Only the frozen read-only observation/binding/tape helpers are imported.
    sys.path.insert(0, str(PACKAGE/'harness'))
    import attest
    import binding
    import core
    require(binding.infrastructure_identity() == json.loads((PACKAGE/'source_hashes.json').read_bytes()),
            'approved_harness_source_hash_drift')
    save('EXTERNAL_SOURCE_IDENTITY.json', binding.infrastructure_identity())
    metadata = {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for key in ('id','hostname'):
        with opener.open('http://169.254.169.254/metadata/v1/'+key,timeout=5) as f:
            metadata[key] = f.read(4096).decode().strip()
    save('DIGITALOCEAN_METADATA.json', metadata)
    require(metadata == {'id':'605465049','hostname':EXPECTED_HOST}, 'provider_host_binding_mismatch')
    registration = json.loads(Path('/opt/actions-runner/.runner').read_text(encoding='utf-8-sig'))
    registration = {k:registration.get(k) for k in ('agentId','agentName','poolId','poolName','gitHubUrl','workFolder')}
    save('RUNNER_REGISTRATION.json', registration)
    require(registration['agentId'] == 21 and registration['agentName'] == 'the meme machine',
            'runner_registration_mismatch')
    snap = attest.inspect([str(MOUNT)])
    save('RESOURCE_INITIAL.json', snap)
    raw = {}
    for name in ('/proc/cpuinfo','/proc/meminfo','/proc/self/status','/proc/self/limits',
                 '/proc/self/cgroup','/proc/1/cgroup','/proc/self/mountinfo',
                 '/proc/modules','/proc/swaps','/proc/stat','/proc/loadavg',
                 '/proc/diskstats','/etc/os-release'):
        try:
            raw[name] = Path(name).read_text()
        except OSError as e:
            raw[name] = dict(error_type=type(e).__name__,reason=str(e))
    raw['commands'] = [cmd(a) for a in [
        ['lscpu','--json'], ['findmnt','--json','--list','--output','SOURCE,TARGET,FSTYPE,OPTIONS'],
        ['lsblk','--json','--bytes','--output','NAME,PATH,SIZE,MODEL,ROTA,TYPE,FSTYPE,LABEL,UUID,MOUNTPOINTS'],
        ['systemctl','list-units','--all','--type=service','--no-legend','--no-pager'],
        ['ps','-eo','pid,ppid,uid,nlwp,pcpu,pmem,stat,comm']]]
    devices = {}
    for p in Path('/sys/block').iterdir():
        row = {}
        for name in ('queue/write_cache','queue/fua','queue/rotational','queue/scheduler','device/model','device/vendor'):
            try:
                row[name] = (p/name).read_text().strip()
            except OSError:
                row[name] = None
        devices[p.name] = row
    raw['block_devices'] = devices
    save('RAW_MACHINE_EVIDENCE.json', raw)
    require(not snap['inspection_errors'], 'resource_inspection_incomplete:'+','.join(snap['inspection_errors']))
    ids = [0,1]
    require(all(snap['cpu'][k] == ids for k in ('possible','present','online')) and snap['affinity'] == ids,
            'exact_two_visible_CPU_or_affinity_failed')
    require(0 < snap['memory']['MemTotal'] <= RAM, 'usable_RAM_invalid')
    require(snap['memory']['SwapTotal'] == 0, 'swap_enabled')
    require(snap['balloon_modules'] == [], 'balloon_module_present')
    cg = snap['cgroup']
    require(cg['complete'] and cg['namespace'] == cg['pid1_namespace'], 'ancestor_cgroup_inventory_incomplete')
    for row in cg['ancestors']:
        q,p = row['quota_us'],row['period_us']
        require(q is None or p and q >= 2*p, 'ancestor_CPU_quota_below_two_CPUs:'+row['path'])
        for k in ('cpuset','cpuset_effective'):
            require(not row[k] or set(ids).issubset(attest.cpus(row[k])), 'ancestor_cpuset_restricts_CPUs:'+row['path'])
        for k in ('memory_max','memory_high','memsw_max'):
            require(row.get(k) is None or row[k] >= RAM, 'ancestor_memory_limit_below_8_GiB:'+row['path']+':'+k)
    require(all(x['free_bytes'] >= HEADROOM for x in snap['storage']), '12_GiB_free_headroom_failed')
    require(all(x['fs_type'] == 'ext4' and 'rw' in x['options'].split(',') for x in snap['storage']),
            'durable_filesystem_identity_failed')
    RESULT['resource_fact_collection'] = 'COMPLETE; dedication, competitors and durability require independent authenticated admission'
    # Verify existing immutable candidate/assembly; never restore, alter, or import them.
    save('ACTUAL_CANDIDATE_VERIFICATION.json', binding.candidate_integrity(OLD/'candidate-checkout'))
    a = binding.verify_assembly(OLD/'assembly')
    save('ACTUAL_ASSEMBLY_VERIFICATION.json', dict(assembly_digest=a['assembly_digest'],
         assembly_manifest_sha256=file_digest(OLD/'assembly/assembly.json'), files_verified=len(a['files'])))
    historical_env = OLD/'fresh-environment.json'
    require(historical_env.is_file(), 'preserved_runtime_manifest_unavailable')
    env = json.loads(historical_env.read_bytes())
    save('PRESERVED_RUNTIME_IDENTITY.json', dict(manifest_path=str(historical_env),
         manifest_sha256=file_digest(historical_env), python_executable=env['python_executable'],
         python_executable_sha256=env['python_executable_hash']))
    python = Path(env['python_executable'])
    require(python.is_file() and file_digest(python) == env['python_executable_hash'], 'preserved_Python_executable_drift')
    code = ('import sys,json;sys.path.insert(0,sys.argv[1]);from binding import runtime_identity;'
            'print(json.dumps(runtime_identity(sys.argv[2]),sort_keys=True))')
    r = subprocess.run([str(python),'-B','-c',code,str(PACKAGE/'harness'),str(OLD/'assembly/source')],
                       capture_output=True,text=True,timeout=240)
    save('RUNTIME_INSPECTION_COMMAND.json', dict(executable=str(python),returncode=r.returncode,
         stdout=r.stdout,stderr=r.stderr,no_runtime_installed=True,no_candidate_imported=True))
    require(r.returncode == 0, 'approved_runtime_inspection_failed:'+r.stderr.strip()[-1500:])
    runtime = json.loads(r.stdout)
    save('RUNTIME_ENVIRONMENT.json', runtime)
    RESULT['runtime_environment_sha256'] = core.sha(core.canonical(runtime))
    # Approved tape verifier only reads/decompresses the immutable file. No feeder or source releases.
    import tape
    result = tape.validate_existing(OLD/'tape/full-cohort-v2.tape', OLD/'tape/FRAMES.json', kind='A')
    save('TAPE_VERIFICATION.json', result)
    RESULT['tape'] = result
    final = attest.inspect([str(MOUNT)])
    save('RESOURCE_FINAL.json', final)
    require(attest.constraint_identity(snap) == attest.constraint_identity(final), 'resources_changed_during_paper_inspection')
    RESULT['status'] = 'FACT_COLLECTION_COMPLETE_REQUIRES_INDEPENDENT_ADMISSION_REVIEW'
    RESULT['campaign_created'] = False

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        RESULT.update(status='STAGE_E_NATIVE_V3_A_PREFLIGHT_BLOCKED',
                      blocker_type=type(exc).__name__, blocker=str(exc))
    finally:
        if OUTPUT is not None:
            RESULT['evidence_path'] = str(OUTPUT)
            receipt = save('RESULT.json', RESULT)
            rows = []
            for p in sorted(OUTPUT.iterdir()):
                if p.is_file():
                    rows.append(dict(path=p.name,bytes=p.stat().st_size,sha256=file_digest(p)))
            save('RAW_EVIDENCE_MANIFEST.json',dict(artifacts=rows,source_frames_released=0,
                 started_A_trials=0,consumed_A_slots=0,execution_authorized=False))
            output = os.environ.get('GITHUB_OUTPUT')
            if output:
                with open(output,'a') as f:
                    f.write('evidence_path='+str(OUTPUT)+'\n')
                    f.write('result_sha256='+receipt['sha256']+'\n')
        print(json.dumps(RESULT,sort_keys=True))
        raise SystemExit(0)
