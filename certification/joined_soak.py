"""Joined accelerated PAPER campaign: native owners and preserved successors.

All transport observations are deterministic; no market/profitability authority.
The initial diagnostic can fail early on measured growth. A passing certificate
requires the complete 168-window run and the complementary frozen proof set.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import resource
from unittest.mock import patch

from certification.journal import canonical,digest


def children():
    # Read the mounted proc namespace directly; container getpid() can name a
    # different PID namespace. Existing hosted PID ownership tests are unchanged.
    return sorted({pid for p in Path('/proc/self/task').glob('*/children') for pid in p.read_text().split()})


def survivor(root,run,lane,window):
    from certification.survivor_paper_book import PaperBook
    from certification.survivor_history import History,compact_restored_history
    from certification.survivor_commit import commit,monitor,restore_risk
    from certification.survivor_terminal_archive import compact
    from certification.directional_sleeve import open_sleeve
    from certification.lifecycle_identity import issue
    from certification.tests.test_survivor_risk_boundaries import POLICIES
    from contextlib import nullcontext
    if lane=='pump':
        from meme_machine.pumpswap_survivor import STRATEGY_ID,POLICY_HASH,POLICY
        minimum_age=POLICY['minimum_age_seconds'];maximum_age=POLICY['maximum_age_seconds']
        folder=root/'pump-survivor'
    else:
        from robinhood_research.pons_postgrad_survivor import STRATEGY_VERSION as STRATEGY_ID,POLICY_HASH,POLICY
        minimum_age=POLICY['universe']['min_seconds_after_graduation'];maximum_age=POLICY['universe']['max_seconds_after_graduation']
        folder=root/'pons-selective-continuation-v1-cohort/pons-survivor'
    folder.mkdir(parents=True,exist_ok=True)
    book=PaperBook(folder/'paper.sqlite',run_id='joined',lane=STRATEGY_ID,policy_hash=POLICY_HASH,initial=1000000)
    sleeve=open_sleeve(lane,1000000);history=History(folder/'history.sqlite',policy=POLICY_HASH)
    compact_restored_history(history,lane=lane);compact(book,sleeve,history)
    position_only=os.environ.get('MM_AUTONOMOUS_POSITION_STATE') is not None
    now=window['index']*3600+100
    decision=dict(candidate=True,policy_hash=POLICY_HASH,features=dict(independent_buyers=20))
    class Adapter:
        def now(self):return self.at
        def fresh_state(self,candidate):return {'at':self.at}
        def fresh_quotes(self,s,b):return self
        def reconstruct(self,s,q):return decision
        def turnover_cap(self,f,d):return 100
        def loss(self,n):return 100
        def entry(self,n):return dict(cost=n,quantity=400,gas=0)
        def generation_fence(self,*a):return nullcontext()
        def validate_current(self,*a):pass
        def exit_quote(self,qty):return dict(quantity=qty,net_proceeds=32 if qty<400 else 125,gas=0)
        def validate_exit(self,e,qty,now):assert e['quantity']==qty
    adapter=Adapter();adapter.at=now
    # Retain aging candidates through the approved minimum rather than starting
    # every window from a fresh synthetic age. The raw history crosses capsules.
    for row in history.rows():
        age=now-row['graduation']['at']
        history.append(row['id'],through=now,events=[],points=[(now,str(100+age//3600))],complete=True)
        if row.get('position'):
            identity=row['position'];risk=restore_risk(book,identity)
            assert risk['realization_taken']
            action=monitor(book=book,sleeve=sleeve,identity=identity,
                observation=dict(id='protect:'+str(now),at=now,after_cost_return_bps=-3000,
                    net_exit_proceeds=30,exit_liquidity_valid=True),policy=POLICIES[lane],adapter=adapter)
            assert action['action']=='full_exit',action
            row=history.get(row['id']);row.update(position=None,state='completed');history.save(row)
        elif not position_only and age>=minimum_age and row['state'] not in ('completed','rejected'):
            regime=dict(at=now,base_id=row['id'],high_reset_cycle='cycle',buyer_population=['a'])
            sleeve.observe(row['id'],strategy=STRATEGY_ID,at=now,state='qualified',evidence=decision,regime=regime)
            identity=issue('joined:'+lane+':'+row['id'])
            receipt=commit(book=book,sleeve=sleeve,identity=identity,candidate=row['id'],generation=1,
                strategy=STRATEGY_ID,policy_hash=POLICY_HASH,decision=decision,regime=regime,at=now,
                target=100,minimum=10,retention_bps=6500 if lane=='pump' else 6000,
                ordinary_limit=600,stress_limit=600,adapter=adapter,qualify=lambda facts:facts)
            assert receipt['status']=='filled',receipt
            adapter.at=now+1
            action=monitor(book=book,sleeve=sleeve,identity=identity,
                observation=dict(id='partial:'+str(now),at=now+1,after_cost_return_bps=POLICIES[lane]['first_profit_bps'],
                    net_exit_proceeds=125,exit_liquidity_valid=True),policy=POLICIES[lane],adapter=adapter)
            assert action['action']=='partial_exit',action
            row=history.get(row['id']);row.update(position=identity,state='runner');history.save(row)
        # Production aging fence; completed state stays available until this age.
        if age>maximum_age and not row.get('position'):history.retire(row,expired_before=now-maximum_age)
    if not position_only:
        candidate='aged:'+str(window['index'])
        try:history.graduate(candidate,dict(at=now,identity=candidate))
        except ValueError as exc:
            if str(exc)!='survivor_candidate_capacity':raise
            # The existing capacity guard refuses discovery, while the same
            # window continues native aging and position management above.
            assert len(history.rows())==history.maximum_candidates
            history.set_meta('joined_capacity_refusals',(history.get_meta('joined_capacity_refusals') or 0)+1)
    history.close();sleeve.close();book.close()


def pump(root,run,window):
    from meme_machine.paper_accounting import PaperBook
    from meme_machine.pump_acceleration_strategy import STRATEGY_ID,policy_hash
    from meme_machine.pump_acceleration_paper import PumpAccelerationPaperLifecycle
    from tests.test_pump_acceleration_paper import qualification
    from certification.lifecycle_identity import issue
    book=PaperBook(root/'pump-acceleration-natural-prospective.accounting.sqlite3',run_id='joined',lane=STRATEGY_ID,policy_hash=policy_hash(),initial=1000000)
    for n in range(2):
        at=window['index']*3600+n*100+100;identity=issue('joined:current:'+str(window['index'])+':'+str(n))
        life=PumpAccelerationPaperLifecycle(book=book,lifecycle_id=identity)
        life.reserve(qualification(),1000,at)
        with life.sleeve.commit_fence(identity):life.fill(100,1000,at+2,'pump.fun')
        life.authenticate_graduation(at+3,True)
        assert life.mark(1300,at+4,80,True)['partial_harvest_bps']==2500
        life.harvest(25,325,at+5)
        before=life.snapshot();life.sleeve.close()
        life=PumpAccelerationPaperLifecycle.restore(book,identity)
        from certification.directional_sleeve import bind_pump_recovered_allocation
        bind_pump_recovered_allocation(book,life)
        assert life.snapshot()['position']==before['position']
        assert life.mark(800,at+6,80,True)['exit_reason']
        life.settle(800,at+7)
    book.close()


def pons(root,run,window):
    # Reuse the measured D1 native trial/re-entry fixture, unchanged execution.
    from certification.tests.test_pons_terminal_archive import POPULATE
    args=sys.argv;sys.argv=['joined',str(root),str(run/'shared-robinhood-evidence.candidates.sqlite'),canonical(window),'2']
    try:exec(POPULATE.replace("'original-paper-books'","'joined'"),{'__name__':'__joined_native__'})
    finally:sys.argv=args


def meteora(root,run,window):
    from tests.test_dlmm_independent_accounting import DurableIndependentAccounting
    from tests import solana_dlmm_independent_v1 as native
    from meme_machine.dlmm_independent_accounting import PaperBook
    case=DurableIndependentAccounting();case.setUp()
    try:
        case.path=root/'solana-dlmm-independent-v1-live.accounting.sqlite3'
        case.book=PaperBook(case.path,run_id='test',policy_hash=native.digest(case.policy),capital=1000000000,
            economic_replay=(native._build_position,native._advance_position,native._mark))
        def exit_next(position,*args):return ['range_boundary'],{},native._mark(position),0
        with patch.object(native,'_segment_exit',side_effect=exit_next):result=case.run_lifecycle()
        assert result['complete']
    finally:case.doCleanups()


def ramses(root,run,window):
    from robinhood_research.ramses_campaign import CampaignBooks
    from robinhood_research.ramses_strategy import USDG_ADDRESS,STRATEGY_DOMAIN
    from robinhood_tests.test_ramses_strategy import RamsesStrategyTests
    from robinhood_tests.test_ramses_continuous_campaign import screen
    from certification.lifecycle_identity import issue
    fixture=RamsesStrategyTests();decision=fixture._decision();capital=decision['freeze']['proposals'][0]['capital_employed']
    folder=root/'robinhood-ramses-extended-market.sqlite.campaign'
    campaign=CampaignBooks.recover(folder) if folder.exists() else CampaignBooks(folder,screen([dict(token_y=USDG_ADDRESS,paper_capital_quote_raw=capital+1000)]))
    book=campaign.ledger(USDG_ADDRESS)
    identity=issue('joined:ramses:'+str(window['index']));at=window['index']*3600+100
    book.reserve(identity,pool='pool',decision=decision,at=at);book.open(identity,at=at)
    for n in range(2):
        book.checkpoint(identity,action='monitor',detail={'observed':n},at=at+n*4+1)
        book.checkpoint(identity,action='segment_close',detail={'segment':n},at=at+n*4+2)
        book.checkpoint(identity,action='rebalance',detail={'proposal_hash':'b'*64},at=at+n*4+3)
    position=book.settle(identity,pnl={'strategy_domain':STRATEGY_DOMAIN,'net_result_quote':1},at=at+10)
    campaign.record('natural_lifecycle',position);campaign.close()


def evidence(run,hour):
    from meme_machine import solana_evidence_service as service
    from meme_machine.solana_evidence_plane import EvidenceReader,EvidenceUnavailable
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from tests.test_solana_evidence_plane import record,proof
    now=1800000000+hour*3600;slot=100+hour*2;path=run/'solana-evidence-plane.sqlite'
    with patch.object(service.time,'time',return_value=now):
        state=service.ServiceState(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
        writer=state.writer;writer.clock=lambda:now
        try:
            if hour:
                writer.reconnect('pump',slot);reader=EvidenceReader(path)
                try:assert not reader.covered('pump',slot,slot+1,as_of=now)
                finally:reader.close()
            writer.ingest([replace(record(slot=slot,observed=now-300),market_time=now-300)],proof=proof(slot,slot,at=now-300,repair=bool(hour)))
            writer.ingest([replace(record(slot=slot+1,observed=now),market_time=now)],proof=proof(slot+1,slot+1,at=now))
            writer.interest('joined:'+str(hour),'pump',lower_slot=slot+1);writer.release('joined:'+str(hour),'pump')
            state.fence.expire_candidates(now)
            while True:
                snapshot=state.archive_plan()
                if not snapshot:break
                plan,receipt=writer.prepare_and_write_archive(path,snapshot);state.archive_commit(plan,receipt)
            state.retention()
            assert writer.db.execute('SELECT COUNT(*) FROM gaps WHERE repaired IS NULL').fetchone()[0]==0
            assert writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]==1
        finally:state.close()


def worker(args):
    sys.path.insert(0,str(args.sources/args.worker))
    from certification.offline_tests import install_network_guard
    install_network_guard()
    root=args.root/'hot/lanes'/args.worker;run=args.root/'hot/certification-position';window=json.loads((run/'window.json').read_text())
    root.mkdir(parents=True,exist_ok=True);os.chdir(root)
    os.environ.update(MM_DIRECTIONAL_COMPOSITE_REQUIRED='1',MM_DIRECTIONAL_SLEEVE_DB=str(root/'directional-sleeve.sqlite'),
        MM_DIRECTIONAL_COHORT_ID='joined',MM_CERTIFICATION_RUN_ID='joined',MM_CERTIFICATION_RPC_CACHE_DB=str(run/'shared-robinhood-evidence.sqlite'))
    claim=json.loads((run/'autonomous-window-claim.json').read_text());position_only=claim['window']['mode']=='position'
    if position_only:
        os.environ['MM_AUTONOMOUS_POSITION_STATE']=str(args.root/'hot')
        if claim['window']['positions'][args.worker]:
            from certification.position_continuation import _runtime_identity
            assert _runtime_identity(args.root/'hot',args.worker)['entry_authority'] is False
    else:
        if (run/'restored-campaign-state.json').exists():os.environ['MM_AUTONOMOUS_STATE_RECEIPT']=str(run/'restored-campaign-state.json')
        os.environ['MM_AUTONOMOUS_WINDOW_CLAIM']=str(run/'autonomous-window-claim.json')
    # Survivor prefix restore precedes any new current-strategy journal tail.
    if args.worker in ('pump','pons'):survivor(root,run,args.worker,window)
    if not position_only:
        if args.worker in ('meteora','ramses'):os.chdir(args.sources/args.worker)
        globals()[args.worker](root,run,window)
    (args.root/(args.worker+'-resources.json')).write_text(canonical(dict(
        fd=len(list(Path('/proc/self/fd').iterdir())),threads=threading.active_count(),
        children=children(),
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)))


def run(args):
    from certification import campaign_state as state
    from certification.autonomous_window import stage,verify_snapshot
    from certification.autonomous_positions import native_proof,live_ids
    from certification.market_assurance import native_positions
    from certification.resource_churn import measure,grouped_tables
    from certification.run import source_integrity
    source_integrity(args.sources)
    root=args.root;root.mkdir(parents=True,exist_ok=False);work=root/'hot/lanes';runtime=root/'hot/certification-position';runtime.mkdir(parents=True)
    identity=state.identity();parent=None;prior=None;samples=[]
    # Empty durable transport DB: no fabricated evidence or balances.
    from contextlib import closing
    with closing(sqlite3.connect(runtime/'shared-robinhood-evidence.sqlite')) as db:
        db.execute('CREATE TABLE fixture_transport(identity PRIMARY KEY)');db.commit()
    from certification.robinhood.plane import Plane
    Plane(runtime/'shared-robinhood-evidence.candidates.sqlite').close()
    base_fd=len(list(Path('/proc/self/fd').iterdir()));base_threads=threading.active_count()
    result=dict(schema='joined-paper-seven-day-v1',identity=identity,passed=False,paper_only=True,market_collection=False,samples=samples,base_fd=base_fd,base_threads=base_threads)
    try:
        for hour in range(args.windows):
            window=dict(campaign_id='joined-seven-day',authorization_hash='a'*64,index=hour,workflow_run_id=hour+1,native_run_id='joined')
            if parent:window['parent_state_hash']=parent
            claim=dict(schema='autonomous-paper-window-claim-v1',identity=identity,campaign_id=window['campaign_id'],authorization_hash=window['authorization_hash'],
                certificate=dict(identity,passed=True),previous=prior,window=dict(index=hour,workflow_run_id=hour+1,native_run_id='joined',mode='hourly' if hour else 'smoke',
                seconds=3600 if hour else 600,entry_authority=True,nonce='b'*32,parent_state_hash=parent,positions=(prior or {}).get('positions',{})))
            position_only=bool(hour%24==23 and prior and any(prior['positions'].values()))
            phase='position' if position_only else 'hourly'
            if position_only:
                claim['window'].update(mode='position',seconds=3000,entry_authority=False)
                state.restore(root/'previous/capsule',worktrees=work,run=runtime,expected_identity=identity,expected_state_hash=parent,
                    campaign_id=window['campaign_id'],prior_index=hour-1,authorization_hash=window['authorization_hash'])
                (root/'hot/autonomous-position-authority.json').write_text(canonical(claim))
                (runtime/'autonomous-window-claim.json').write_text(canonical(claim))
            elif prior:state.prepare_window(claim,worktrees=work,run=runtime,phase='hourly',seconds=3600,prior_state=root/'previous/capsule')
            else:(runtime/'autonomous-window-claim.json').write_text(canonical(claim))
            (runtime/'window.json').write_text(canonical(window))
            def child(lane):
                process=subprocess.run([sys.executable,'-m','certification.joined_soak','--worker',lane,'--sources',str(args.sources),'--root',str(root)],
                    capture_output=True,text=True,timeout=90)
                (root/(lane+'.log')).write_text(process.stdout+process.stderr)
                if process.returncode:raise ValueError('joined_native_worker:'+lane+':'+process.stderr[-3000:])
            # Shared evidence and sleeve owners execute concurrently, just as the
            # supervisor does; each lane is isolated in its pinned import tree.
            with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(child,state.LANES))
            evidence(runtime,hour)
            proof={lane:native_proof(lane,work/lane,args.sources/lane) for lane in state.LANES}
            projections={lane:native_positions(work/lane,lane) for lane in state.LANES}
            assert all(p.get('verified') is True for p in proof.values()),proof
            assert all(not p['violations'] for p in projections.values()),projections
            positions={lane:live_ids(p) for lane,p in projections.items()}
            hot=measure(root/'hot')
            terminal=dict(status='FINISHED',phase='position_continuation' if position_only else 'hourly',integration_sha=identity['integration_sha'],implementation_hash=identity['implementation_hash'],
                lanes={lane:dict(exit_code=0,accounting_reconciled=True,terminal_reconciliation=p) for lane,p in proof.items()})
            output=root/'next';output.mkdir();shutil.copytree(runtime,output/('certification-'+phase))
            (output/('certification-'+phase)/'result.json').write_text(canonical(terminal))
            # Exact native modules are reachable by seal's existing isolated
            # archive workers, but never included in the state snapshot.
            for lane in state.LANES:
                for name in ('meme_machine','robinhood_research','robinhood_tests','tests'):
                    if (args.sources/lane/name).is_dir() and not (work/lane/name).exists():(work/lane/name).symlink_to(args.sources/lane/name,target_is_directory=True)
            from certification.autonomous_window import checksum
            controller=work/'pons/pons-selective-continuation-v1-cohort/qualifiers.jsonl'
            controller_before=checksum(controller)
            artifact=stage(work,output,phase);assert verify_snapshot(artifact)['snapshot_complete']
            assert checksum(controller)==controller_before,'source_controller_changed_during_staging'
            capsule=state.seal(output/'capsule',worktrees=work,run=output/('certification-'+phase),window=window,terminal=terminal,expected_identity=identity,preserved_artifact=artifact,discovery_window=prior['discovery_window'] if position_only else window)
            sample=measure(output/'capsule/files');sample.update(hour=hour,fd=len(list(Path('/proc/self/fd').iterdir())),threads=threading.active_count(),accounting=proof,
                preseal=hot,positions=positions,mode=phase,projection_violations=False,
                children=children(),
                workers={lane:json.loads((root/(lane+'-resources.json')).read_text()) for lane in state.LANES})
            samples.append(sample)
            sample['fd_targets']={p.name:os.readlink(p) for p in Path('/proc/self/fd').iterdir() if p.exists()}
            assert sample['fd']<=base_fd+2 and sample['threads']==base_threads
            result.update(windows_completed=hour+1,virtual_seconds=(hour+1)*3600)
            (root/'result.json').write_text(canonical(result))
            print(canonical(dict(hour=hour,hot_bytes=sample['bytes'],positions=positions)),flush=True)
            # Fail early only on a measured new HOT owner; immutable predecessor
            # accumulation is intentional and excluded from this measurement.
            if hour>=11:
                groups=[grouped_tables(s) for s in samples[-8:]]
                leaks={key:[g.get(key,0) for g in groups] for key in groups[-1]
                    if key.endswith((':journal',':positions')) and '/pump-survivor/' not in key and '/pons-survivor/' not in key and all(b.get(key,0)>a.get(key,0) for a,b in zip(groups,groups[1:]))}
                if leaks:raise ValueError('joined_measured_linear_hot_growth:'+canonical(leaks))
            prior=dict(window,state_hash=capsule['state_hash'],positions=positions,discovery_window=prior['discovery_window'] if position_only else window,
                artifact={'digest':'sha256:'+digest(verify_snapshot(artifact))})
            parent=capsule['state_hash'];work.rename(output/'drained-lanes');runtime.rename(output/'drained-runtime');runtime.mkdir()
            previous=root/'previous'
            if previous.exists():
                cold=root/'preserved'/str(hour-1);cold.parent.mkdir(exist_ok=True);previous.rename(cold)
            output.rename(previous)
        # One more actual successor restores the terminally drained original
        # books, without executing any worker or manufacturing entry authority.
        assert not any(prior['positions'].values()),'joined_terminal_not_drained'
        claim['previous']=prior
        claim['window'].update(index=args.windows,workflow_run_id=args.windows+1,
            mode='hourly',seconds=3600,entry_authority=True,parent_state_hash=parent,positions=prior['positions'])
        state.prepare_window(claim,worktrees=root/'final-successor/lanes',run=root/'final-successor/run',
            phase='hourly',seconds=3600,prior_state=root/'previous/capsule')
        final={lane:native_proof(lane,root/'final-successor/lanes'/lane,args.sources/lane) for lane in state.LANES}
        assert all(final[lane]['accounting']==capsule['accounting'][lane]['accounting'] for lane in state.LANES)
        result.update(measurement_complete=args.windows>=168,passed=False,pending=['joined_matrix_acceptance'],
            terminal_drained=True,final_successor_accounting_exact=True)
        from certification.resource_churn import controller
        result['controller']=controller(168)
    except BaseException as exc:
        result.update(error_type=type(exc).__name__,error=str(exc));raise
    finally:(root/'result.json').write_text(canonical(result))


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--sources',type=Path,required=True)
    p.add_argument('--worker',choices=('pump','pons','meteora','ramses'));p.add_argument('--windows',type=int,default=192)
    a=p.parse_args();a.root=a.root.resolve();a.sources=a.sources.resolve()
    worker(a) if a.worker else run(a)

if __name__=='__main__':main()
