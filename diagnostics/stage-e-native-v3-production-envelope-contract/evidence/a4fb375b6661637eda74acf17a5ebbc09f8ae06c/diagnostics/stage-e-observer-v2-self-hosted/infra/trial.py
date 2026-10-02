"""One complete measured cohort. No rerun, retry, alternate cohort or warmup."""
import json
import os
from pathlib import Path
import subprocess
import time
import bound_runtime as bound
from core import BASE,COHORT,MODES,clean_env,persist,read,runtime_command,storage


def main():
    params=bound.PARAMS;number=params['sequence'];mode=params['mode']
    if type(number) is not int or not 1<=number<=6 or MODES[number-1]!=mode:
        raise ValueError('trial_order')
    output=Path(params['output']);members=[]
    for index,(member,frames) in enumerate(COHORT,1):
        disk=storage()
        folder=output/f'm{index}';folder.mkdir(exist_ok=False)
        anchor=folder/'anchor.bin';anchor.write_bytes(b'\0'*8)
        member_params=folder/'params.json'
        row=dict(params,member=member,frames=frames,output=str(folder),
            runtime=str(folder/'d'),anchor=str(anchor))
        persist(member_params,row)
        persist(output/'MEMBERS_STARTED.json',dict(sequence=number,started=index,
            members=[m['member'] for m in members]+[member],mode=mode))
        with (folder/'member.log').open('wb') as log:
            child=subprocess.Popen(runtime_command('bootstrap.py','--member'),
                cwd=BASE/'candidate-checkout',env=clean_env(member_params),stdout=log,stderr=subprocess.STDOUT)
            try:code=child.wait(timeout=frames*.27+240)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:child.wait(timeout=15)
                except subprocess.TimeoutExpired:child.kill();child.wait()
                persist(folder/'INTERRUPTION.json',dict(reason='member_process_timeout',member=member))
                raise
        result=read(folder/'MEMBER_RESULT.json') if (folder/'MEMBER_RESULT.json').exists() else None
        source=read(folder/'SOURCE_RECEIPT.json') if (folder/'SOURCE_RECEIPT.json').exists() else None
        members.append(dict(member=member,frames=frames,exit_code=code,
            workload_valid=result and result['workload_valid'],
            observation_valid=result and result['observation_valid'],source=source,
            storage_before=disk,storage_after=storage()))
        persist(output/'COHORT_PROGRESS.json',dict(sequence=number,mode=mode,members=members))
        if code or not members[-1]['workload_valid'] or not members[-1]['observation_valid']:
            raise ValueError('started_member_invalid:'+member)
    if len(members)!=4:raise ValueError('incomplete_cohort')
    persist(output/'TRIAL_RESULT.json',dict(version='observer-complete-cohort-trial-v1',
        sequence=number,mode=mode,valid=True,members=members,
        workload_identity='native-full-cohort-pressure-v2',declaration_sha256=params['declaration_sha256']))
