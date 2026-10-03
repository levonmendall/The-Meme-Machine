"""Preserve the first runtime mismatch and a final read-only machine inventory."""
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import platform
import sys
import time
sys.dont_write_bytecode=True
REPO=Path(os.environ['MM_APPROVED_REPOSITORY']).resolve()
PACKAGE=REPO/'diagnostics/stage-e-native-v3-executable-harness'
sys.path.insert(0,str(PACKAGE/'harness'))
import attest,binding,core
HERE=Path(__file__).resolve().parent
OUTPUT=Path('/mnt/volume_nyc1_1790918115030/stage-e-native-v3-paper-preflight/native-v3-a-closure-20261003T121620Z-runtime-blocker')
OUTPUT.mkdir(exist_ok=False)
def save(name,value):
    path=OUTPUT/name;data=core.canonical(value)+b'\n'
    with path.open('xb') as target:
        target.write(data);target.flush();os.fsync(target.fileno())
    attest.fsync_dir(OUTPUT)
try:
    core.require(binding.git(REPO,'rev-parse','HEAD').decode().strip()=='f480c6b4f7a8442fd148c7ed61bcc4447edaefca','approved_executable_identity_changed')
    versions={}
    for name in ('websockets','PyYAML','jsonschema'):
        try:
            dist=importlib.metadata.distribution(name)
            files=[]
            for relative in dist.files or ():
                if str(relative).endswith(('.dist-info/METADATA','.dist-info/RECORD')):
                    path=Path(dist.locate_file(relative))
                    files.append(dict(path=str(path),bytes=path.stat().st_size,sha256=core.file_sha(path)))
            versions[name]=dict(version=dist.version,identity_metadata_files=files)
        except importlib.metadata.PackageNotFoundError:versions[name]=dict(state='NOT INSTALLED')
    executable=Path(sys.executable)
    expected=dict(python='3.12.14',websockets='17.1')
    observed=dict(python=platform.python_version(),websockets=versions.get('websockets',{}).get('version'))
    failed=[key for key,value in expected.items() if observed.get(key)!=value]
    save('RUNTIME_FAILURE_OBSERVATION.json',dict(first_exact_blocker='frozen_runtime_version',expected=expected,observed=observed,
        mismatch_fields=failed,sys_version=sys.version,sys_executable=str(executable),resolved_executable=str(executable.resolve()),
        executable_sha256=core.file_sha(executable),executable_bytes=executable.stat().st_size,
        implementation=platform.python_implementation(),machine=platform.machine(),uname=list(os.uname()),
        installed_dependencies=versions,observed_utc_ns=time.time_ns(),observed_monotonic_ns=time.monotonic_ns(),
        exact_approved_helper_sha256=core.file_sha(PACKAGE/'harness/binding.py'),
        predicate='platform.python_version() == 3.12.14 and importlib.metadata.distribution(websockets).version == 17.1',
        runtime_changes_performed=0,execution_authorized=False,actual_slots_reserved=False,A_slots_consumed=0,source_frames_released=0))
    snapshot=attest.inspect(['/mnt/volume_nyc1_1790918115030'],os.getppid())
    save('RESOURCE_AFTER_BLOCKER.json',snapshot)
    spec=importlib.util.spec_from_file_location('read_only_process_supplement',HERE/'collect_process_attestation_r2.py')
    collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
    details=collector.process_details(snapshot)
    save('PROCESS_AFTER_BLOCKER_DETAILS.json',details)
    save('SYSTEMD_AFTER_BLOCKER.json',collector.unit_evidence(details))
    save('ACTIVITY_AFTER_BLOCKER.json',collector.cgroup_activity(details))
    save('EXECUTABLES_AFTER_BLOCKER_PROVENANCE.json',collector.packages({r['executable'] for r in snapshot['processes'] if not r['kernel']}))
    save('RESOURCE_AFTER_BLOCKER_CHECKS.json',collector.host_checks(snapshot))
    save('STOP_RECORD.json',dict(first_exact_blocker='frozen_runtime_version',frozen_predicate_failed=bool(failed),paper_only=True,
        execution_authorized=False,actual_slots_reserved=False,A_trials_started=0,A_slots_consumed=0,source_frames_released=0,
        owner_execution_permit_created=False,runtime_changes_performed=0,quiescence_performed=False,stage_e='RED',stage_f='NOT STARTED',
        continued_activities='read-only blocker identification, final inventory and preservation only'))
finally:
    save('EVIDENCE_MANIFEST.json',dict(artifacts=[dict(path=p.name,bytes=p.stat().st_size,sha256=core.file_sha(p)) for p in sorted(OUTPUT.iterdir()) if p.is_file()],
        execution_authorized=False,A_slots_consumed=0,source_frames_released=0))
    with open(os.environ['GITHUB_OUTPUT'],'a') as target:target.write('evidence_path='+str(OUTPUT)+'\n')
print('STOP: frozen_runtime_version; evidence preserved; zero Stage-E slots and source frames')
