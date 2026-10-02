"""Complete-cohort process. No warmups, retry, replacement or partial credit."""
import os
from pathlib import Path
import signal
import subprocess

import bound_runtime as bound
from core import COHORT, INFRA, MODES, file_sha, read, require, workload
from preserve import persist, fsync_dir
from verify import stress_member_result

OVERLOAD = 'DIAGNOSTIC_OVERLOAD_WITH_NATIVE_FAIL_CLOSED_PROOF'


def member_acceptance(code, result, kind):
    """Protocol admission only; independent raw verification is still required."""
    if code != 0:
        return False, False
    if kind != 'C':
        return result.get('valid') is True, False
    classification = stress_member_result(result)
    valid = classification['mandatory_native_safety_pass'] and all(
        result.get(k) == v for k,v in classification.items())
    return valid, valid and classification['outcome'] == OVERLOAD


def runtime_command(params, entry):
    return [params['environment']['python_executable'], '-I', '-S', '-B', '-X',
            'pycache_prefix='+params['cache_path'], str(INFRA/'bootstrap.py'), entry]


def member_command():
    return runtime_command(bound.PARAMS, '--member')


def child_env(params_path):
    params = read(params_path)
    env = dict(PATH='/usr/bin:/bin', LANG='C.UTF-8', TZ='UTC', MM_REAL_IPC_TESTS='1',
        MM_STAGE_E_V3_PARAMS=str(params_path), MM_STAGE_E_V3_PARAMS_SHA=file_sha(params_path),
        MM_STAGE_E_V3_PYTHON=params['environment']['python_executable'],
        MM_STAGE_E_V3_CACHE=params['cache_path'], MM_STAGE_E_V3_BOOTSTRAP=str(INFRA/'bootstrap.py'))
    for key in ('GITHUB_REPOSITORY', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_EVENT_NAME',
                'GITHUB_SHA', 'GITHUB_WORKFLOW_REF'):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def stop_child(child, folder, reason):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=15)
    persist(Path(folder)/'INTERRUPTION.json', dict(reason=reason, native_safety_credit=False))


def main():
    params = bound.PARAMS
    kind, number, mode = params['kind'], params['sequence'], params['mode']
    require(kind in ('A','B','C') and type(number) is int and number >= 1, 'trial_identity')
    require(number <= (6 if kind == 'B' else 1), 'trial_no_retry')
    require(mode == (MODES[number-1] if kind == 'B' else 'baseline' if kind == 'A' else 'stress'), 'trial_mode_order')
    output = Path(params['output'])
    matrix = [('run373-full-v3',14,'run373'), ('run379-full-v3',120,'run379'), ('run380-full-v3',240,'run380')] if kind == 'A' else []
    matrix += [(name, frames, None) for name,frames in COHORT]
    members = []
    for index, (member, frames, shape) in enumerate(matrix,1):
        # Full storage/resource attestation is common to both B arms.
        bound.resource_admission(f'before-member-{index}',member=member)
        folder = output/f'm{index}'
        folder.mkdir(exist_ok=False)
        anchor = folder/'anchor.bin'
        with anchor.open('xb') as target:
            target.write(b'\0'*8); target.flush(); os.fsync(target.fileno())
        fsync_dir(folder)
        cadence = {'run373':750000,'run379':50000,'run380':270000}.get(shape,270000)
        row = dict(params, member=member, frames=frames, shape=shape, cadence_us=cadence,
                   output=str(folder), runtime=str(folder/'d'), anchor=str(anchor))
        parameter_path = folder/'params.json'
        persist(parameter_path, row)
        persist(output/f'MEMBER-{index}-STARTED.json', dict(member=member, sequence=number,
                trial_id=params['trial_id'], mode=mode, declaration_sha256=params['declaration_sha256']))
        child = None
        with (folder/'member.log').open('xb') as log:
            try:
                child = subprocess.Popen(member_command(), cwd=params['candidate_checkout'],
                    env=child_env(parameter_path), stdout=log, stderr=subprocess.STDOUT)
                code = child.wait(timeout=frames*cadence/1e6+240)
            except BaseException as exc:
                if child:
                    stop_child(child, folder, type(exc).__name__)
                raise
            finally:
                log.flush(); os.fsync(log.fileno())
        result_path = folder/'MEMBER_RESULT.json'
        result = read(result_path) if result_path.exists() else {}
        valid, terminal = member_acceptance(code, result, kind)
        members.append(dict(member=member, frames=frames, shape=shape, exit_code=code, valid=valid,
                            member_result_sha256=file_sha(result_path) if result_path.exists() else None))
        persist(output/f'MEMBER-{index}-FINISHED.json', dict(members=list(members), valid=valid))
        require(valid, 'started_member_invalid:'+member)
        if terminal:
            persist(output/'COHORT_RESULT.json', dict(version='v3-terminal-native-overload', kind=kind,
                sequence=number, trial_id=params['trial_id'], mode=mode, valid=True, members=members,
                complete_profile=False, outcome=OVERLOAD, diagnostic_outcome='FAILED_DIAGNOSTIC',
                capacity_credit=False, terminal_member=member, no_further_members=True,
                declaration_sha256=params['declaration_sha256']))
            return
    persist(output/'COHORT_RESULT.json', dict(version='v3-complete-cohort', kind=kind, sequence=number,
        trial_id=params['trial_id'], mode=mode, valid=True, members=members, complete_profile=True,
        declaration_sha256=params['declaration_sha256']))
