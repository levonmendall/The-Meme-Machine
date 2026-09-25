"""Manual deterministic Robinhood certification. No market/deployment entrypoint."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from certification.run import ROOT, git, integration_integrity, source_integrity


def run(worktrees,output):
    integration_integrity();sha=git('rev-parse','HEAD')
    roots=Path(worktrees).resolve();out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    identities=source_integrity(roots)
    env={k:v for k,v in os.environ.items() if not k.startswith(('MM_','GH_','GITHUB_','RENDER_'))
        and not any(part in k.upper() for part in ('TOKEN','SECRET','PRIVATE_KEY'))}
    env['PYTHONUNBUFFERED']='1'
    with tempfile.TemporaryDirectory() as guard_dir:
        # Inherited by every test child. Only local mocked transports are allowed.
        Path(guard_dir,'sitecustomize.py').write_text('''import sys,ipaddress,os
from pathlib import Path
def guard(event,args):
    if event!='socket.connect':return
    address=args[1]
    if not isinstance(address,tuple):return
    host=str(address[0])
    try:local=ipaddress.ip_address(host).is_loopback
    except ValueError:local=host=='localhost'
    if local:return
    with Path(os.environ['ROBINHOOD_OFFLINE_ATTEMPTS']).open('a') as f:f.write('blocked_external_socket\\n')
    raise RuntimeError('robinhood_certification_external_socket_forbidden')
sys.addaudithook(guard)
''')
        env['PYTHONPATH']=guard_dir+os.pathsep+str(ROOT)
        env['ROBINHOOD_OFFLINE_ATTEMPTS']=str(out/'network-attempts.txt')
        jobs={
            'components':['-m','certification.non_market','--worktrees',str(roots),'--output',str(out/'components')],
            'supervisor':['-m','unittest','discover','-s','certification/tests','-v'],
            'policy':['-m','certification.protocol_freeze','--output',str(out/'policy.json')],
            'pons_replay':['-m','certification.robinhood.replay','--fixture',str(ROOT/'certification/evidence/robinhood-runs-355-368.json.gz'),'--pons',str(roots/'pons'),'--output',str(out/'pons-replay.json')],
            'ramses_replay':['-m','certification.robinhood.replay_ramses','--fixture',str(ROOT/'certification/evidence/ramses-run364-initial.json.gz'),'--ramses',str(roots/'ramses'),'--output',str(out/'ramses-replay.json')],
            'native_crash':['-m','certification.crash_matrix','--worktrees',str(roots),'--output',str(out/'native-crash')],
            'restart':['-m','certification.restart_safety','--worktrees',str(roots),'--output',str(out/'restart')],
            'integrated':['-m','certification.integrated_acceptance','--worktrees',str(roots),'--output',str(out/'integrated')],
            'resource':['-m','tests.resource_check'],
        }
        def job(name):
            with (out/(name+'.log')).open('wb') as stream:
                result=subprocess.run([sys.executable,*jobs[name]],cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=600)
            return result.returncode==0
        # Do not run two copies of a native lane suite concurrently.
        with ThreadPoolExecutor(max_workers=2) as pool:
            names=['components','supervisor'];gates=dict(zip(names,pool.map(job,names)))
        for name in jobs:
            if name not in gates:gates[name]=job(name)
    attempts=out/'network-attempts.txt'
    gates['no_external_network_attempts']=not attempts.exists() or not attempts.read_text().strip()
    gates['source_unchanged']=source_integrity(roots)==identities and git('rev-parse','HEAD')==sha
    integration_integrity()
    result=dict(integration_sha=sha,source_diff_hashes=identities,gates=gates,
        passed=all(gates.values()),deterministic_non_market_certification='PASS' if all(gates.values()) else 'FAIL',
        overall_task_acceptance='NOT_PROVEN: retained traces cannot measure Pons coverage/censoring improvement',
        paper_only=True,market_run_started=False,deployment_performed=False,
        provider_calls_during_offline_replay=0,
        limitation='Open controllers with incomplete native context retain exposure and fail closed; tests do not claim automatic reconstruction of that context.')
    (out/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps(result,sort_keys=True));return 0 if result['passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worktrees',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();raise SystemExit(run(a.worktrees,a.output))
