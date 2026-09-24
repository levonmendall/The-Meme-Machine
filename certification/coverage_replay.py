"""One final, read-only historical replay before successor collection."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from certification.prospective_program import GitHub,git,ROOT
from certification.run import source_integrity,manifest
from certification.journal import digest
from certification.coverage_successor import PREDECESSOR_RUN,PREDECESSOR_SHA,PREDECESSOR_ARCHIVE

EXTRACT_RUN=35945640187
EXTRACT_ARTIFACT=10786398294
EXTRACT_DIGEST='sha256:b2f9a2e3dc41efbb080b6ccb11ebcdd33b53172ca4984ed9243a1a038a3baee3'


def run(worktrees,output):
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    root=out/'retained';root.mkdir()
    api=GitHub()
    archive,item=api.artifact(EXTRACT_RUN,f'preserved-coverage-evidence-{EXTRACT_RUN}')
    if item['id']!=EXTRACT_ARTIFACT or item['digest']!=EXTRACT_DIGEST:raise ValueError('coverage_derivative_identity')
    with archive:
        for member in archive.infolist():
            path=(root/member.filename).resolve()
            if not path.is_relative_to(root) or ((member.external_attr>>16)&0o170000)==0o120000:raise ValueError('coverage_archive_path')
        archive.extractall(root)
    provenance=json.loads((root/'provenance.json').read_text())
    if (provenance['source_run']!=PREDECESSOR_RUN or provenance['source_sha']!=PREDECESSOR_SHA
            or 'sha256:'+provenance['archive_sha256']!=PREDECESSOR_ARCHIVE or provenance['market_requests']!=0):
        raise ValueError('coverage_original_archive_identity')
    verified=[]
    for row in provenance['files']:
        path=root/row['path']
        if not path.exists():
            if row['path']=='certification-hourly/shared-solana-evidence.sqlite':continue
            raise ValueError('coverage_missing_original_member')
        with path.open('rb') as f:observed=hashlib.file_digest(f,'sha256').hexdigest()
        if observed!=row['sha256'] or path.stat().st_size!=row['bytes']:raise ValueError('coverage_original_member_digest')
        verified.append(row['path'])
    identities=source_integrity(worktrees)
    env={k:v for k,v in os.environ.items() if not k.startswith(('MM_','GH_','GITHUB_')) and not any(s in k.upper() for s in ('TOKEN','SECRET','PRIVATE_KEY'))}
    def lane_replay(lane):
        source=Path(worktrees).resolve()/lane
        cmd=[sys.executable,str(ROOT/'certification/terminal_reconciliation.py'),'--lane',lane,
             '--root',str(root/'certification-native/hourly'/lane),'--source-root',str(source)]
        proc=subprocess.run(cmd,cwd=source,env=env,capture_output=True,text=True,timeout=60)
        proof=json.loads(proc.stdout)
        if proc.returncode or proof.get('verified') is not True or proof.get('open_positions')!=0:raise ValueError('coverage_native_terminal:'+lane)
        if lane=='meteora':
            path=out/'meteora-replay.json'
            cmd=[sys.executable,str(ROOT/'certification/replay_meteora_supply_interval.py'),
                '--raw-evidence',str(root/'certification-hourly/meteora/rpc-evidence.jsonl.gz'),
                '--lane-root',str(source),'--output',str(path)]
            proc=subprocess.run(cmd,cwd=source,env=env,capture_output=True,text=True,timeout=60)
            if proc.returncode:raise ValueError('coverage_meteora_replay:'+proc.stderr[-1000:])
            acquisition=json.loads(path.read_text())
        else:
            cmd=[sys.executable,str(ROOT/'certification/coverage_replay_lanes.py'),'--lane',lane,
                 '--artifact-root',str(root),'--source-root',str(source)]
            proc=subprocess.run(cmd,cwd=source,env=env,capture_output=True,text=True,timeout=60)
            if proc.returncode:raise ValueError('coverage_acquisition_replay:'+lane+':'+proc.stderr[-1000:])
            acquisition=json.loads(proc.stdout)
        return dict(native_terminal=proof,acquisition_replay=acquisition)
    with ThreadPoolExecutor(max_workers=4) as pool:
        lanes=dict(zip(('pump','meteora','pons','ramses'),pool.map(lane_replay,('pump','meteora','pons','ramses'))))
    row=dict(schema='final-preserved-coverage-replay-v1',passed=True,integration_sha=git('rev-parse','HEAD'),
        source_run=PREDECESSOR_RUN,source_sha=PREDECESSOR_SHA,original_artifact_digest=PREDECESSOR_ARCHIVE,
        derivative_artifact_id=item['id'],derivative_artifact_digest=item['digest'],verified_original_files=verified,
        source_manifest_hash=digest(manifest()),source_diff_hashes=identities,lanes=lanes,
        predecessor_remains_censored=True,historical_blocks_admitted=0,natural_market_requests=0,
        limitations=['Never captured source pages, expired timely decisions, provider failures and missing full entry evidence cannot be recreated.',
                     'Retained facts are replayed only where technically valid; improved logic does not admit the old Pump settlement.'])
    (out/'result.json').write_text(json.dumps(row,sort_keys=True,indent=2)+'\n')
    print(json.dumps(dict(passed=True,source_run=PREDECESSOR_RUN,native_flat={l:v['native_terminal']['open_positions']==0 for l,v in lanes.items()},predecessor_remains_censored=True)))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worktrees',required=True);p.add_argument('--output',required=True);a=p.parse_args();run(a.worktrees,a.output)
