"""Restore the reviewed assembly verbatim and bind the fresh runtime separately."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig

S = '7a516a6a92be9347661ac0e7f560971c171a0931'
T = '9da7d1e1625ba04c1437c63606c90f5e293bdba7'
DIGEST = '08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659'
MANIFEST_SHA = 'd60d02a32838df4658cc5943d469057ec08ece11e82301b3e85231e029c9eaa0'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root)


def main():
    root = Path(os.environ['GITHUB_WORKSPACE']).resolve()
    base = Path('/mnt/volume_nyc1_1790918115030/meme-machine-observer-v2-7a516a6a')
    proof = Path(os.environ['OBSERVER_PREPARATION_OUTPUT'])
    proof.mkdir(parents=True, exist_ok=True)
    base.mkdir(exist_ok=True)
    checkout = base/'candidate-checkout'
    if not checkout.exists():
        subprocess.run(['git','clone','--no-checkout',str(root),str(checkout)],check=True)
        subprocess.run(['git','switch','--detach',S],cwd=checkout,check=True)
    assert git(checkout,'rev-parse','HEAD').decode().strip() == S
    assert git(checkout,'rev-parse',S+'^{tree}').decode().strip() == T
    assert not git(checkout,'status','--porcelain','--untracked-files=all').strip()
    data = (root/'diagnostics/stage-e-observer-v2/REVIEWED_ASSEMBLY.json').read_bytes()
    assert sha(data) == MANIFEST_SHA
    manifest = json.loads(data)
    assert manifest['assembly_digest'] == DIGEST and len(manifest['files']) == 1241
    entries = {}
    for line in git(checkout,'ls-tree','-rz','--full-tree',S).split(b'\0'):
        if line:
            header,name = line.split(b'\t',1)
            mode,kind,blob = header.decode().split()
            assert kind == 'blob' and mode in ('100644','100755')
            entries[name.decode()] = dict(mode=mode,git_blob=blob)
    assert set(entries) == set(manifest['files'])
    assembly = base/'assembly'
    if not assembly.exists():
        source = assembly/'source'
        source.mkdir(parents=True)
        for index,(name,info) in enumerate(manifest['files'].items()):
            assert entries[name]['mode'] == info['mode'] and entries[name]['git_blob'] == info['git_blob']
            payload = git(checkout,'cat-file','blob',info['git_blob'])
            assert len(payload) == info['bytes'] and sha(payload) == info['sha256']
            target = source/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(payload)
            target.chmod(0o555 if info['mode'] == '100755' else 0o444)
            if index % 200 == 0:
                print(json.dumps(dict(phase='reconstruct_reviewed_assembly',files=index)),flush=True)
        (assembly/'assembly.json').write_bytes(data)
        (assembly/'assembly.json').chmod(0o444)
        for folder in sorted((p for p in source.rglob('*') if p.is_dir()),reverse=True):
            folder.chmod(0o555)
        source.chmod(0o555)
        assembly.chmod(0o555)
    sys.dont_write_bytecode = True
    sys.path.insert(0,str(assembly/'source'))
    from certification.stage_e_native_v2.binding import verify_assembly,environment_identity
    checked = verify_assembly(assembly,DIGEST)
    row = dict(version='fresh-host-reviewed-assembly-verification-v1',passed=True,
        candidate_sha=S,candidate_tree=T,assembly_digest=DIGEST,
        reviewed_manifest_sha256=sha(data),file_count=len(checked['files']),
        assembly=str(assembly),candidate_checkout=str(checkout),
        native_verifier_module_sha256=sha((assembly/'source/certification/stage_e_native_v2/binding.py').read_bytes()),
        historical_assembly_manifest_unchanged=True,started_trials=0,started_members=0)
    (proof/'ASSEMBLY_VERIFICATION.json').write_text(json.dumps(row,indent=2,sort_keys=True)+'\n')
    try:
        env = environment_identity()
    except Exception as exc:
        (proof/'ENVIRONMENT_BLOCKER.json').write_text(json.dumps(dict(version='runtime-binding-blocker-v1',passed=False,error_type=type(exc).__name__,reason=str(exc),python=platform.python_version(),sqlite=__import__('sqlite3').sqlite_version,started_trials=0),indent=2)+'\n')
        raise
    env.update(hostname=__import__('socket').gethostname(),cpu_count=os.cpu_count(),
        affinity=sorted(os.sched_getaffinity(0)),runtime_source='fresh self-hosted environment; separately bound from historical assembly metadata')
    (base/'fresh-environment.json').write_text(json.dumps(env,indent=2,sort_keys=True)+'\n')
    (proof/'ENVIRONMENT.json').write_bytes((base/'fresh-environment.json').read_bytes())
    verify_assembly(assembly,DIGEST)
    print(json.dumps(dict(assembly='VERIFIED',file_count=1241,python=env['python'],sqlite=env['sqlite'],dependency_digest=env['dependencies']['websockets']['digest'],started_trials=0)),flush=True)


if __name__ == '__main__':
    main()
