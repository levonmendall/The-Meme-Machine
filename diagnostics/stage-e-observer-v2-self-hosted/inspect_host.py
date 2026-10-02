"""Control-plane host and storage inspection; never imports a workload."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import time
import urllib.request


def command(*args):
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return dict(code=r.returncode, stdout=r.stdout.strip(), stderr=r.stderr.strip())


def main():
    target = json.loads(Path(__file__).with_name('RUNNER_TARGET.json').read_text())
    out = Path(os.environ['OBSERVER_IDENTITY_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    failures = []
    def require(condition, reason):
        if not condition:
            failures.append(reason)
    require(os.environ['GITHUB_RUN_ATTEMPT'] == '1', 'rerun_forbidden')
    require(os.environ['GITHUB_SHA'] == os.environ['OBSERVER_EXPECTED_SHA'], 'workflow_sha')
    require(command('git', 'rev-parse', 'HEAD')['stdout'] == os.environ['GITHUB_SHA'], 'checkout_sha')
    env = {k: os.environ.get(k) for k in ('RUNNER_NAME','RUNNER_OS','RUNNER_ARCH','RUNNER_WORKSPACE','RUNNER_TEMP','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REPOSITORY','GITHUB_SHA','GITHUB_WORKFLOW_REF','GITHUB_WORKFLOW_SHA')}
    require(env['RUNNER_NAME'] == target['runner_name'], 'runner_name')
    require(env['RUNNER_OS'] == 'Linux' and env['RUNNER_ARCH'] == 'X64', 'runner_platform')
    host = socket.gethostname()
    require(host == target['hostname'], 'hostname')
    metadata = {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for key in ('id','hostname'):
        try:
            with opener.open('http://169.254.169.254/metadata/v1/' + key, timeout=5) as r:
                metadata[key] = r.read(4096).decode().strip()
        except Exception as exc:
            metadata[key] = {'error': type(exc).__name__}
    require(metadata.get('id') == str(target['droplet_id']), 'droplet_metadata_identity')
    require(metadata.get('hostname') == target['hostname'], 'metadata_hostname')
    registration = None
    version = None
    for parent in Path(os.environ['RUNNER_TEMP']).resolve().parents:
        path = parent / '.runner'
        if path.is_file():
            raw = json.loads(path.read_text())
            registration = {k: raw.get(k) for k in ('agentId','agentName','poolId','poolName','gitHubUrl','workFolder')}
            registration['path'] = str(path)
            version = command(str(parent / 'bin/Runner.Listener'), '--version')
            break
    require(registration and registration['agentName'] == target['runner_name'], 'runner_registration')
    require(version and version['stdout'] == target['runner_version'], 'runner_version')
    mounts = command('findmnt','--json','--list','--output','SOURCE,TARGET,FSTYPE,OPTIONS')
    disks = command('lsblk','--json','--bytes','--output','NAME,PATH,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINTS')
    devices = sorted({str(p.resolve()) for p in Path('/dev/disk/by-id').glob('*DO_Volume*')})
    volumes = []
    if mounts['code'] == 0:
        for m in json.loads(mounts['stdout'])['filesystems']:
            if str(Path(m['source']).resolve()) in devices:
                u = shutil.disk_usage(m['target'])
                volumes.append(dict(**m, total_bytes=u.total, used_bytes=u.used, free_bytes=u.free))
    require(len(volumes) == 1, 'one_mounted_do_block_volume')
    require(len(volumes) == 1 and volumes[0]['free_bytes'] >= 40 * 1024**3, 'volume_free_space')
    os_release = {k:v.strip('"') for k,v in (line.split('=',1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)}
    require(os_release.get('ID') == 'ubuntu' and os_release.get('VERSION_ID') == '24.04', 'ubuntu_24_04')
    require(os.cpu_count() == 2 and platform.machine() == 'x86_64', 'host_cpu')
    services = command('systemctl','list-units','--all','--type=service','--no-legend','--no-pager')
    service_rows = []
    for line in services['stdout'].splitlines():
        fields = line.lstrip('● ').split()
        if fields and fields[0].startswith('actions.runner.'):
            service_rows.append(command('systemctl','show',fields[0],'--property=Id,ActiveState,UnitFileState'))
    require(len(service_rows) == 1 and 'ActiveState=active' in service_rows[0]['stdout'] and 'UnitFileState=enabled' in service_rows[0]['stdout'], 'dedicated_enabled_active_service')
    usage = shutil.disk_usage('/')
    row = dict(version='observer-host-identity-only-v1', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()), passed=not failures, failures=failures, runner=env, hostname=host, digitalocean_metadata=metadata, registration=registration, runner_version=version, routing_labels=target['routing_labels'], registered_labels_user_confirmed=target['registered_labels_user_confirmed'], unique_eligibility=target['unique_eligibility'], platform=platform.platform(), os_release=os_release, cpu_count=os.cpu_count(), affinity=sorted(os.sched_getaffinity(0)), memory={k:v.strip() for k,v in (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines()) if k in ('MemTotal','MemAvailable')}, findmnt=mounts, lsblk=disks, volume_devices=devices, volume_mounts=volumes, root_disk=dict(total_bytes=usage.total,free_bytes=usage.free), runner_services=service_rows, inspection_python=platform.python_version(), workflow_file_sha256=hashlib.sha256(Path('.github/workflows/non-market-certification.yml').read_bytes()).hexdigest(), started_trials=0, started_members=0, candidate_imports=0)
    (out / 'HOST_IDENTITY.json').write_text(json.dumps(row,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(passed=row['passed'], failures=failures, runner_name=env['RUNNER_NAME'], hostname=host, droplet_id=metadata.get('id'), volume_mounts=volumes)))
    return 0 if row['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
