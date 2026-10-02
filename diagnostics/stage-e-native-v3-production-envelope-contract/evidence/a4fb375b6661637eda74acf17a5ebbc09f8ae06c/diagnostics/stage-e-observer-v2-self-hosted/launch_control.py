"""Workflow-bound control launcher; no candidate imports or benchmark itself."""
import hashlib
import json
import os
from pathlib import Path
import sys

base=Path('/mnt/volume_nyc1_1790918115030/meme-machine-observer-v2-7a516a6a')
prep=json.loads((base/'PREPARATION.json').read_bytes())
infra=Path(prep['infrastructure_path'])
manifest=infra/'INFRASTRUCTURE.json'
if hashlib.sha256(manifest.read_bytes()).hexdigest()!=prep['infrastructure_manifest_sha256']:
    raise ValueError('launcher_infrastructure_identity')
environment=json.loads((base/'fresh-environment.json').read_bytes())
env=os.environ.copy()
env['LD_LIBRARY_PATH']=str(Path(environment['stdlib']).parent)
python='/workspace/stage-e-runtime/bin/python'
arguments=[python,'-I','-S','-B','-X',f'pycache_prefix={base}/bytecode-disabled',str(infra/'control.py'),*sys.argv[1:]]
os.execve(python,arguments,env)
