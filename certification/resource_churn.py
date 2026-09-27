"""Offline owner-level resource measurement; no strategy or market authority.

This is a discriminator, not a passing machinery certificate. It reuses native
owners and existing snapshot/capsule fixtures, and retains every measurement.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys


def measure(root):
    root=Path(root);tables={};files={};wal=0
    for path in sorted(root.rglob('*')):
        if not path.is_file():continue
        relative=str(path.relative_to(root));size=path.stat().st_size
        files[relative]=size
        if path.name.endswith('-wal'):wal+=size
        with path.open('rb') as stream:header=stream.read(16)
        if header!=b'SQLite format 3\x00':continue
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            names=[x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for name in names:
                quoted='"'+name.replace('"','""')+'"'
                tables[relative+':'+name]=db.execute('SELECT COUNT(*) FROM '+quoted).fetchone()[0]
    return dict(tables=tables,files=files,bytes=sum(files.values()),wal_bytes=wal,
                db_bytes=sum(n for name,n in files.items() if any(k.startswith(name+':') for k in tables)))


def grouped_tables(sample):
    result={}
    for key,count in sample['tables'].items():
        key=re.sub(r'trial-\d+\.sqlite:', 'trial-*.sqlite:',key)
        result[key]=result.get(key,0)+count
    return result


def controller(windows=12):
    """Exercise the real controller with the existing Git/Actions transport fixture."""
    from certification.tests.test_autonomous_control import AutonomousControllerTests,IDENTITY,CAMPAIGN,REF
    from certification import autonomous_control as control
    fixture=AutonomousControllerTests();fixture.setUp();samples=[]
    try:
        control.authorize(fixture.api,IDENTITY,CAMPAIGN,REF,99,1,maximum_windows=windows)
        fixture.start(1,2);fixture.finish(2);fixture.api.terminal(2);fixture.api.run(3)
        control.accept_smoke(fixture.api,IDENTITY,CAMPAIGN,fixture.state()['previous']['artifact']['digest'],3)
        actor=3
        for index in range(windows):
            run=index+4;fixture.start(actor,run);fixture.finish(run);actor=run
            state=fixture.state();raw=json.dumps(state,sort_keys=True).encode()
            samples.append(dict(bytes=len(raw),wal_bytes=0,db_bytes=0,files={},tables={
                'controller:recent_events':len(state['recent_events']),
                'controller:window':int(bool(state['window'])),
                'controller:predecessor':int(bool(state['previous'])),
                'controller:position_ids':sum(map(len,state['previous']['positions'].values()))}))
    finally:fixture.doCleanups()
    return samples


def classify(samples):
    result={}
    groups=[grouped_tables(s) for s in samples]
    keys=sorted(set().union(*groups))
    for key in keys:
        values=[s.get(key,0) for s in groups]
        deltas=[b-a for a,b in zip(values,values[1:])]
        state='LINEAR' if deltas and min(deltas)>0 else 'BOUNDED' if len(values)>=3 and len(set(values[-3:]))==1 else 'UNKNOWN'
        result[key]=dict(classification=state,counts=values,rows_per_window=(values[-1]-values[0])/(len(values)-1))
    return result


def snapshots(root,window,book,name):
    from certification.archive_native import copy_snapshot
    target=root/'preserved'/str(window)/name;target.parent.mkdir(parents=True,exist_ok=True)
    source=Path(book.db.execute('PRAGMA database_list').fetchone()[2]);records=[]
    copy_snapshot(source,target,records)
    if records[0].get('error_type'):raise ValueError(records)
    authority=dict(schema='preserved-native-prefix-v1',snapshot_sha256=records[0]['sha256'],
        snapshot_name=name,state_hash=str(window).zfill(64),artifact={'digest':'sha256:'+'a'*64},
        campaign_id='resource-churn-fixture',window_index=window)
    book._compact_preserved(target,authority)
    book.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')


def directional(root,windows,count):
    from certification.survivor_paper_book import PaperBook
    from certification.sleeve_reservations import SleeveReservations
    hot=root/'hot';hot.mkdir(parents=True);samples=[]
    book=PaperBook(hot/'paper.sqlite',run_id='churn',lane='survivor',policy_hash='frozen',initial=1000000)
    sleeve=SleeveReservations(hot/'sleeve.sqlite',lane='pump',capital=1000000,
        policies={'current':'a','survivor':'b'},cohort='churn')
    try:
        for window in range(windows):
            for index in range(count):
                n=window*count+index;at=window*3600+index*10;identity='churn:'+str(n);candidate='candidate:'+str(n)
                sleeve.observe(candidate,strategy='survivor',at=at,state='qualified',evidence={'n':n},regime={'n':n})
                sleeve.reserve(identity,strategy='survivor',amount=100,at=at)
                book.reserve(identity,100,at,{'candidate':candidate})
                if index%2:
                    with sleeve.commit_fence(identity):pass
                    book.transition(identity,'filled',at+1,amount=100,tokens=100,evidence={'execution':{'gas':0}})
                    book.transition(identity,'partial_harvest',at+2,amount=25,tokens=25,evidence={'execution':{'gas':0}})
                    book.transition(identity,'settled',at+3,amount=75,evidence={'execution':{'gas':0}})
                else:book.transition(identity,'cancelled',at+1)
                sleeve.release(identity,pnl=0,at=at+4,terminal_hash='native:'+str(n),native_verified=True,cancelled=not index%2)
            before=book.reconcile();snapshots(root,window,book,'paper.sqlite');snapshots(root,window,sleeve,'sleeve.sqlite')
            assert book.reconcile()==before and sleeve.reconcile()['available']==1000000
            samples.append(measure(hot))
    finally:book.close();sleeve.close()
    return samples


def robinhood(root,windows,count):
    from certification.tests.test_robinhood_window_archive import RobinhoodWindowArchive
    from certification.robinhood.plane import Plane,canonical
    from certification.robinhood.accounting import project,high_water
    from certification import campaign_state as transfer
    fixture=RobinhoodWindowArchive();f,pons,ramses=fixture.initialize();samples=[];parent=None
    try:
        for window in range(windows):
            plane=Plane(f.run/'shared-robinhood-evidence.candidates.sqlite',clock=lambda:float(window*3600+100))
            pipeline=fixture.native_pipeline('pons')(pons,'pons','frozen')
            try:
                for index in range(count):
                    n=window*count+index;at=window*3600+index;key='curve:'+str(n)
                    plane.observe(key,'pons',str(n),{'n':n},ordering=(n,),watermark={'n':n},
                        interpretation={'policy':'frozen'},observed=at,deadline=window*3600+500,priority=4)
                    work=plane.claim(key=key);assert work is not None
                    assert plane.finish(work,result={'rejected':'frozen'}) and plane.consume(key,work['generation'])
                    plane.rolling_put(key,str(n),at,n,{'n':n},{'authority':'authenticated_receipt_header'})
                    plane.put('domain:header_hash',str(n),{'number':n},{'authority':'authenticated_alchemy'})
                    plane.put('ramses_route_v1',str(n),{'cost':n},{'authority':'authenticated_alchemy'})
                through=high_water(plane)
                while project(plane,pipeline,through=through)==256:pass
            finally:plane.close();pipeline.close()
            output,runtime,artifact=fixture.staged(f,window)
            identity=dict(f.window,index=window,workflow_run_id=window+1)
            if parent:identity['parent_state_hash']=parent
            body=transfer.seal(output/'capsule',worktrees=f.lanes,run=runtime,window=identity,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
            next_work=f.root/'next-lanes';next_run=f.root/'next-run'
            transfer.restore(output/'capsule',worktrees=next_work,run=next_run,
                expected_identity=f.identity,expected_state_hash=body['state_hash'],campaign_id=identity['campaign_id'],
                prior_index=window,authorization_hash=identity['authorization_hash'])
            samples.append(measure(next_run))
            # Preserve raw predecessor artifacts and capsule for diagnosis.
            shutil.copytree(output,root/('window-'+str(window)))
            shutil.rmtree(f.lanes);shutil.rmtree(f.run)
            next_work.rename(f.lanes);next_run.rename(f.run);parent=body['state_hash']
    finally:fixture.doCleanups()
    return samples


NATIVE=r'''
import json,os,sys
from pathlib import Path
from certification.offline_tests import install_network_guard
install_network_guard()
sys.path.insert(0,os.getcwd())
from certification.resource_churn import measure
lane=sys.argv[1];root=Path(sys.argv[2]);root.mkdir(parents=True);windows=int(sys.argv[3]);count=int(sys.argv[4]);samples=[]
if lane=='pons':
 from robinhood_research.evidence import Store,digest
 from robinhood_research.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
 from robinhood_research.pons_selective_capital import CohortCapital
 from robinhood_research.pons_selective_continuation import POLICY_HASH
 from robinhood_tests.test_pons_partial_accounting import PartialAccountingTests
 from certification.robinhood.pons import save_cohort_checkpoint
 from certification.robinhood.plane import Plane,project_native_position
 case=PartialAccountingTests();guard=CohortCapital(root/'capital.sqlite',1000000)
 plane_path=root/'candidate.sqlite'
 result=dict(candidate_plane_path=str(plane_path),policy_hash=POLICY_HASH,qualifiers=[],lifecycles=[])
 for w in range(windows):
  for i in range(count):
   n=w*count+i;at=w*3600+i*10;identity='trial:'+str(n);path=root/('trial-'+str(n)+'.sqlite')
   store=Store(path);paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000000,delay=1,natural_policy_hash=POLICY_HASH,on_commit=guard.observe)
   features=case.features(at);guard.reserve(identity,120,at=at,decision_hash=digest(features),trial_path=path)
   paper.reserve(identity,market='m',amount=100,gas_budget=20,now=at,features=features)
   paper.advance(identity,now=at+1,action='entry',quote=case.quote(at+1,'buy',100,1000))
   paper.advance(identity,now=at+2,action='exit_intent',exit_tokens=500)
   paper.advance(identity,now=at+3,action='exit',quote=case.quote(at+3,'sell',500,52))
   paper.advance(identity,now=at+4,action='exit_intent')
   p=paper.advance(identity,now=at+5,action='exit',quote=case.quote(at+5,'sell',500,54))
   guard.settle(identity,p,at=at+5);store.close()
   result['qualifiers'].append(dict(index=n,curve='curve:'+str(n),vector=features))
   result['lifecycles'].append(dict(index=n,curve='curve:'+str(n),final_position=p))
   project_native_position(plane_path,'pons','curve:'+str(n),p,ledger_path=path,policy=POLICY_HASH)
  save_cohort_checkpoint(result,cursor=w*count+count,phase='finalizing')
  assert guard.reconcile()['reserved']==0
  sample=measure(root);sample['tables'].update({'controller:qualifiers':len(result['qualifiers']),
   'controller:lifecycles':len(result['lifecycles']),
   'controller:reentry_vectors':len({q['curve']:q['vector'] for q in result['qualifiers']})})
  samples.append(sample)
elif lane=='meteora':
 from meme_machine.dlmm_independent_accounting import PaperBook,NAMESPACE
 from tests import solana_dlmm_independent_v1 as native
 book=PaperBook(root/'book.sqlite',run_id='churn',policy_hash=native.digest(native.load_policy()),capital=1000000)
 policy=native.load_policy()
 for w in range(windows):
  for i in range(count):
   n=w*count+i;identity=NAMESPACE+':churn:'+str(n);at=(w*3600+i*10)*10**9
   book.append(identity,'reserve',{'amount':102},at_ns=at)
   mark={'ending_sol_lamports':102,'pnl_lamports':0}
   book.append(identity,'entry',dict(capital=100,entry_cost=1,exit_cost=1,policy=policy,position={},entry_state={},mark=mark),at_ns=at+1)
   book.append(identity,'settle',{'mark':mark},at_ns=at+2)
  assert book.reconcile()['unsettled']==0
  samples.append(measure(root))
elif lane=='ramses':
 from robinhood_research.ramses_campaign import CampaignBooks
 from robinhood_research.ramses_strategy import USDG_ADDRESS,STRATEGY_DOMAIN
 from robinhood_tests.test_ramses_strategy import RamsesStrategyTests
 from robinhood_tests.test_ramses_continuous_campaign import screen
 fixture=RamsesStrategyTests();decision=fixture._decision();capital=decision['freeze']['proposals'][0]['capital_employed']
 campaign=CampaignBooks(root/'campaign',screen([dict(token_y=USDG_ADDRESS,paper_capital_quote_raw=capital+1000)]))
 book=campaign.ledger(USDG_ADDRESS)
 for w in range(windows):
  for i in range(count):
   n=w*count+i;identity='ramses:'+str(n);at=1000+w*3600+i*10
   book.reserve(identity,pool='pool:'+str(n),decision=decision,at=at);book.open(identity,at=at)
   book.checkpoint(identity,action='segment_close',detail={'n':n},at=at+1)
   book.checkpoint(identity,action='rebalance',detail={'proposal_hash':decision['freeze']['proposals'][0].get('proposal_hash','a'*64)},at=at+2)
   p=book.settle(identity,pnl={'strategy_domain':STRATEGY_DOMAIN,'net_result_quote':0},at=at+3)
   campaign.record('terminal',p)
  assert campaign.reconcile()['open_positions']==0
  book.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');samples.append(measure(root))
 campaign.close()
print(json.dumps(samples))
'''


def run(roots,output,windows=6,count=20,owners=None):
    from certification.run import source_integrity
    from certification.offline_tests import install_network_guard
    if windows<3 or count<2 or count>200 or windows>168:raise ValueError('bounded_measurement_required')
    owners=set(owners or ('directional','robinhood','pons','meteora','ramses','controller'))
    if owners-{'directional','robinhood','pons','meteora','ramses','controller'}:raise ValueError('unknown_owner')
    source=source_integrity(roots)
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    os.environ['MM_TEST_LANE_WORKTREES']=str(roots)
    install_network_guard();results={}
    for owner,driver in [('directional',directional),('robinhood',robinhood)]:
        if owner not in owners:continue
        path=output/owner;path.mkdir()
        samples=driver(path,windows,count)
        results[owner]=dict(samples=samples,tables=classify(samples))
        (output/'measurement.json').write_text(json.dumps(results,indent=2))
    for lane in ('pons','meteora','ramses'):
        if lane not in owners:continue
        completed=subprocess.run([sys.executable,'-c',NATIVE,lane,str(output/lane),str(windows),str(count)],
            cwd=Path(roots)/lane,env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1])),
            capture_output=True,text=True,timeout=120)
        if completed.returncode:raise RuntimeError(lane+':'+completed.stdout+completed.stderr)
        samples=json.loads(completed.stdout);results[lane]=dict(samples=samples,tables=classify(samples))
        (output/'measurement.json').write_text(json.dumps(results,indent=2))
    if 'controller' in owners:
        samples=controller(max(12,windows));results['controller']=dict(samples=samples,tables=classify(samples))
    report=dict(schema='autonomous-owner-churn-measurement-v1',source=source,windows=windows,
        identities_per_window=count,provider_calls=0,market_authority=False,owners=results)
    (output/'measurement.json').write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--worktrees',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--windows',type=int,default=6);parser.add_argument('--count',type=int,default=20)
    parser.add_argument('--owners',nargs='+')
    args=parser.parse_args();result=run(args.worktrees,args.output,args.windows,args.count,args.owners)
    for owner,value in result['owners'].items():
        print(owner,'bytes:',[s['bytes'] for s in value['samples']])
        print(json.dumps({k:v for k,v in value['tables'].items() if v['classification']!='BOUNDED'},sort_keys=True))
