"""Install immutable external infrastructure, generate tape, prove pretrial gates."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'infra'))
from core import ASSEMBLY,BASE,INFRA,PYTHON,clean_env,file_sha,persist,read,storage


def main():
    output=Path(os.environ['OBSERVER_PREPARATION_OUTPUT'])
    disk=storage()
    if os.environ['GITHUB_RUN_ATTEMPT']!='1':raise ValueError('rerun_forbidden')
    source=BASE/'assembly/source';sys.path.insert(0,str(source))
    from certification.stage_e_native_v2.binding import verify_assembly,environment_identity
    verify_assembly(BASE/'assembly',ASSEMBLY)
    env=read(BASE/'fresh-environment.json')
    fresh=environment_identity()
    assert fresh=={k:v for k,v in env.items() if k not in ('hostname','cpu_count','affinity','runtime_source')}
    entries={p.name:dict(sha256=file_sha(p),bytes=p.stat().st_size,executable=p.name=='child.sh')
        for p in sorted(INFRA.iterdir()) if p.is_file()}
    identity=hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    target=BASE/'infrastructure'/identity
    target.mkdir(parents=True,exist_ok=False)
    for name,info in entries.items():
        shutil.copyfile(INFRA/name,target/name);(target/name).chmod(0o555 if info['executable'] else 0o444)
    infra_sha=persist(target/'INFRASTRUCTURE.json',dict(version='external-observer-infrastructure-v1',
        files=entries,content_digest=identity,source_commit=os.environ['GITHUB_SHA'],
        outside_reviewed_assembly=True))
    (target/'INFRASTRUCTURE.json').chmod(0o444);target.chmod(0o555)
    os_tools={name:dict(path=shutil.which(name),sha256=file_sha(shutil.which(name)))
        for name in ('ps','git','sh','unshare')}
    persist(output/'INFRASTRUCTURE.json',read(target/'INFRASTRUCTURE.json'))
    from tape import generate
    generate(output)
    audit_dir=output/'bootstrap';audit_dir.mkdir(exist_ok=False)
    anchor=audit_dir/'anchor.bin';anchor.write_bytes(b'\0'*8)
    params=audit_dir/'params.json'
    persist(params,dict(environment=env,infrastructure_manifest_sha256=infra_sha,
        output=str(audit_dir),anchor=str(anchor),os_tools=os_tools))
    command=['unshare','--net',PYTHON,'-I','-S','-B','-X',f'pycache_prefix={BASE}/bytecode-disabled',
        str(target/'bootstrap.py'),'--audit']
    child_env=clean_env(params);child_env['MM_OBSERVER_INFRA']=str(target)
    subprocess.run(command,cwd=BASE/'candidate-checkout',env=child_env,check=True,timeout=120)
    for filename in ('DIFFERENTIAL_PROOF.json','SEMANTIC_CLOCK_AUDIT.json','BOOTSTRAP_PROOF.json'):
        shutil.copyfile(audit_dir/filename,output/filename)
    verify_assembly(BASE/'assembly',ASSEMBLY)
    row=dict(version='external-observer-preparation-v1',passed=True,
        infrastructure_path=str(target),infrastructure_manifest_sha256=infra_sha,
        environment_sha256=file_sha(BASE/'fresh-environment.json'),
        assembly_digest=ASSEMBLY,tape_manifest_sha256=file_sha(BASE/'tape/TAPE.json'),
        preparation_workflow_sha=os.environ['GITHUB_SHA'],preparation_run_id=os.environ['GITHUB_RUN_ID'],
        os_tools=os_tools,storage_before=disk,storage_after=storage(),
        proof_hashes={name:file_sha(output/name) for name in ('GENERATOR_EQUIVALENCE.json',
            'DIFFERENTIAL_PROOF.json','SEMANTIC_CLOCK_AUDIT.json','BOOTSTRAP_PROOF.json')},
        started_trials=0,started_members=0,retries=0,invalid_pairs=0)
    persist(output/'PREPARATION.json',row)
    persist(BASE/'PREPARATION.json',row)
    (BASE/'PREPARATION.json').chmod(0o444)
    print(json.dumps(dict(preparation='VERIFIED',started_trials=0,tape_sha256=row['tape_manifest_sha256'])),flush=True)


if __name__=='__main__':main()
