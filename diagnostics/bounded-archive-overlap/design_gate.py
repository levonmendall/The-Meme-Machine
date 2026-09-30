"""One-record deterministic allocation boundary, not a pressure workload."""
import argparse,copy,hashlib,json,os,platform,resource,sqlite3,subprocess,time,traceback
from dataclasses import replace
from pathlib import Path
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_provider_config import AlchemyEndpoint
from tests.test_run381_retention_progress import record

def git(root,*args):
    return subprocess.check_output(['git',*args],cwd=root,text=True).strip()

def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('reference','prototype'),required=True)
    p.add_argument('--output',required=True);a=p.parse_args();out=Path(a.output)
    out.mkdir(parents=True,exist_ok=False)
    now=time.time();path=out/'runtime'/'db'
    state=ServiceState(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
    row=replace(record(),identity='bounded-allocation-boundary',signature='bounded-allocation-boundary',
        market_time=int(now)-185,observed_at=now,payload={'padding':'Z'*(13*1024*1024)})
    started=time.monotonic();error=None;prepared=None
    result=dict(mode=a.mode,fixture='one legitimate 13-MiB body, no lookahead',
        pressure_workload=False,material_execution=False,provider_calls=0,
        ingestion_cap=16*1024*1024,unchanged_native_worker_body_target=16*1024*1024,
        root_initial_reservation=750,lookahead_reserved_fraction=250,
        prototype_current_body_allocation=12*1024*1024,lookahead_exists=False)
    try:
        raw=row.serialized_body()[1];result['actual_body_bytes']=len(raw.encode())
        state.writer.ingest([row])
        snapshot=state.writer.archive_snapshot(now-180,max_records=750)
        assert snapshot and len(snapshot['rows'])==1
        result['encoded_bytes']=snapshot['encoded_bytes']
        if a.mode=='prototype':
            from meme_machine.solana_bounded_overlap import ArchiveFlight,prepare_and_write_archive
            flight=ArchiveFlight()
            flight.hold(snapshot,state.fence.session,time.monotonic())
            result['carrier_before_worker']=flight.check(state.last_measured_archive_receipt)
            result['actual_serialized_arguments_bytes']=flight.serial_bytes
            prepared=prepare_and_write_archive(path,copy.deepcopy(flight.prepared),max_bytes=16*1024*1024)
        else:
            prepared=state.writer.prepare_and_write_archive(path,snapshot,max_bytes=16*1024*1024)
        plan,receipt=prepared
        assert len(plan)==1
        remaining=state.archive_commit_slice(plan,receipt)
        assert not remaining
        result['accepted']=True
    except BaseException as exc:
        error=type(exc).__name__+':'+str(exc)
        result['accepted']=False;result['error']=error
        result['stack']=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name)
                         for f in traceback.extract_tb(exc.__traceback__)]
    finally:
        result['archived_records']=(state.writer.db.execute(
            "SELECT value FROM counters WHERE key='archived_records'").fetchone() or [0])[0]
        result['hot_records']=state.writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0]
        result['integrity']=state.writer.db.execute('PRAGMA integrity_check').fetchone()[0]
        result['archive_files']=len(list(path.parent.glob('*.archive/*.gz')))
        result['elapsed_seconds']=time.monotonic()-started
        result['peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result['environment']=dict(python=platform.python_version(),sqlite=sqlite3.sqlite_version,
            websockets=__import__('importlib.metadata',fromlist=['version']).version('websockets'),
            os=platform.platform(),cpu_count=os.cpu_count(),affinity=sorted(os.sched_getaffinity(0)),
            load=list(os.getloadavg()),run_id=os.getenv('GITHUB_RUN_ID'),
            attempt=os.getenv('GITHUB_RUN_ATTEMPT'),runner=os.getenv('RUNNER_NAME'))
        result['paper_only']=True;result['canonical_authority']=False
        state.close()
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print('ALLOCATION_BOUNDARY '+json.dumps(result,sort_keys=True),flush=True)
    # The following comparison, not the fixture process's return code, owns the gate.
if __name__=='__main__':main()
