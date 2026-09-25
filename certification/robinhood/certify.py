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


def provider_gates(output):
    requirements={
        'canonical_provider_configuration':'test_configuration_rejects_alternate_authority_and_missing',
        'provider_role_isolation':'test_public_and_shadow_never_have_canonical_cache_or_authority',
        'aggregate_shared_governor_ceiling':'test_aggregate_governor_concurrent_lane_clients',
        'canonical_failover_absent':'test_chain_required_before_shared_evidence_and_no_rescue',
        'shared_evidence_reuse':'test_one_authority_and_mandatory_shared_store',
        'credential_isolation':'test_candidate_provenance_reports_archives_and_crash_output_are_secret_free',
        'physical_logical_accounting':'test_batch_is_one_physical_n_logical_and_shared_reuse_zero',
        'provider_telemetry':'test_retry_counts_distinct_wire_attempts',
        'provider_identity_continuity':'test_session_and_configuration_identity_continuity',
        'provider_crash_accounting':'test_process_death_preserves_unresolved_physical_attempt',
    }
    proven={}
    for lane in ('pons','ramses'):
        path=Path(output)/'components'/(lane+'.json')
        rows=json.loads(path.read_text()).get('tests',[]) if path.exists() else []
        proven[lane]={r['id'].rsplit('.',1)[-1] for r in rows if r['result']=='PROVEN' and 'ProviderAuthorityTests' in r['id']}
    gates={name:all(test in proven[lane] for lane in proven) for name,test in requirements.items()}
    gates['public_sequencer_non_authority']='test_acquisition_refuses_public_client_even_after_chain_verification' in proven['pons'] and 'test_route_broker_duplicate_committed_result_and_public_refusal' in proven['ramses']
    gates['evidence_plane_bypass_prevention']='test_broker_coalesces_and_fences_provider_completion' in proven['pons'] and 'test_route_broker_duplicate_committed_result_and_public_refusal' in proven['ramses']
    return gates


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
    gates.update(provider_gates(out))
    attempts=out/'network-attempts.txt'
    gates['no_external_network_attempts']=not attempts.exists() or not attempts.read_text().strip()
    gates['source_unchanged']=source_integrity(roots)==identities and git('rev-parse','HEAD')==sha
    integration_integrity()
    result=dict(integration_sha=sha,source_diff_hashes=identities,gates=gates,
        passed=all(gates.values()),deterministic_non_market_certification='PASS' if all(gates.values()) else 'FAIL',
        overall_task_acceptance=('Robinhood Evidence Plane + authenticated Alchemy provider architecture complete and offline-certified' if all(gates.values()) else 'OFFLINE_CERTIFICATION_FAILED'),
        prospective_operational_validation='DEFERRED: coverage, censoring, physical requests, CU, 429 behavior, latency, throughput and market load',
        paper_only=True,market_run_started=False,deployment_performed=False,
        provider_calls_during_offline_replay=0,
        limitation='Open controllers with incomplete native context retain exposure and fail closed; tests do not claim automatic reconstruction of that context.')
    (out/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps(result,sort_keys=True));return 0 if result['passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worktrees',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();raise SystemExit(run(a.worktrees,a.output))
