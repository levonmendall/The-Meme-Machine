"""Current Pons D1 lifecycle churn through preserved campaign capsules."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
from certification import campaign_state as transfer
from certification.tests import test_robinhood_window_archive as robinhood_fixture
from certification.journal import canonical

# The native D1 trial sequence, now issued under real window identity and carrying
# the cohort's actual qualifier/lifecycle checkpoint across each handoff.
POPULATE=r'''
import json,os,sys
from pathlib import Path
from unittest.mock import patch
from certification.offline_tests import install_network_guard
install_network_guard()
from robinhood_research.evidence import Store,digest
from robinhood_research.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
from robinhood_research.pons_selective_capital import CohortCapital
from robinhood_research.pons_selective_continuation import POLICY_HASH,reentry_regime_reset
from robinhood_research.pons_selective_cohort import _next_trial_index,_qualifier_count
from robinhood_tests.test_pons_partial_accounting import PartialAccountingTests
from certification.robinhood.pons import save_cohort_checkpoint
from certification.robinhood.plane import Plane,project_native_position
from certification.robinhood.accounting import project
from robinhood_research.pipeline import Pipeline
from certification.lifecycle_identity import issue
root=Path(sys.argv[1]);plane_path=Path(sys.argv[2]);window=json.loads(sys.argv[3]);count=int(sys.argv[4])
os.chdir(root);folder=Path('pons-selective-continuation-v1-cohort');folder.mkdir(exist_ok=True)
os.environ.update(MM_DIRECTIONAL_SLEEVE_DB=str(root/'directional-sleeve.sqlite'),MM_DIRECTIONAL_COHORT_ID='original-paper-books')
case=PartialAccountingTests();guard=CohortCapital(folder/'pons-selective-cohort-capital.sqlite',1000000)
plane=Plane(plane_path,clock=lambda:window['index']*3600+100.)
saved=plane.checkpoint_read('pons_cohort')
result=saved['result'] if saved else dict(candidate_plane_path=str(plane_path),policy_hash=POLICY_HASH,qualifiers=[],lifecycles=[])
result['candidate_plane_path']=str(plane_path)
for kind,name in result.get('native_archive_paths',{}).items():
 p=Path(name);result[kind]=[json.loads(x) for x in p.read_text().splitlines() if x] if p.exists() else []
result['native_archive_paths']=dict(qualifiers=str(folder/'qualifiers.jsonl'),lifecycles=str(folder/'completed-lifecycles.jsonl'))
from certification.pons_window_archive import LOGS
result['native_archive_paths'].update({k:str(folder/v) for k,v in LOGS.items()})
for k in LOGS:result.setdefault(k,[])
pipe=Pipeline(folder/'opportunity-pipeline.sqlite','pons','frozen')
with patch('certification.campaign_state.active_window',return_value={k:window[k] for k in ('campaign_id','authorization_hash','index','workflow_run_id')}):
 for i in range(count):
  n=_next_trial_index(result);at=window['index']*3600+i*10;identity=issue('trial:'+str(n));path=folder/('trial-'+str(n)+'.sqlite');curve='curve:'+str(n)
  features=case.features(at);features.update(token_age_seconds=100,asof=at)
  plane.observe(curve,'pons',str(n),{},ordering=(n,),watermark={},interpretation={},observed=at,deadline=at+500,priority=4)
  work=plane.claim(key=curve);assert plane.finish(work,result={'vector':features});assert plane.consume(curve,work['generation'])
  store=Store(path);paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000000,delay=1,natural_policy_hash=POLICY_HASH,on_commit=guard.observe)
  guard.reserve(identity,120,at=at,decision_hash=digest(features),trial_path=path)
  paper.reserve(identity,market='m',amount=100,gas_budget=20,now=at,features=features)
  paper.advance(identity,now=at+1,action='entry',quote=case.quote(at+1,'buy',100,1000))
  paper.advance(identity,now=at+2,action='exit_intent',exit_tokens=500)
  paper.advance(identity,now=at+3,action='exit',quote=case.quote(at+3,'sell',500,52))
  paper.advance(identity,now=at+4,action='exit_intent')
  p=paper.advance(identity,now=at+5,action='exit',quote=case.quote(at+5,'sell',500,54))
  guard.settle(identity,p,at=at+5);store.close()
  result['qualifiers'].append(dict(index=n,curve=curve,vector=features,wallet_convergence={'converged':False}))
  result['lifecycles'].append(dict(index=n,curve=curve,lifecycle_id=identity,status='settled',final_position=p,reconciliation={'open_exposure':0},realized_pnl_quote=p['pnl']))
  project_native_position(plane_path,'pons',curve,p,ledger_path=path,policy=POLICY_HASH)
 for kind,name in result['native_archive_paths'].items():Path(name).write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in result[kind]))
 save_cohort_checkpoint(result,cursor=window['index']*count+count,phase='finalizing')
while project(plane,pipe)==256:pass
assert guard.reconcile()['reserved']==0
print(json.dumps(dict(accounting=guard.reconcile(),next_index=_next_trial_index(result),qualified=_qualifier_count(result))))
pipe.close();plane.close()
'''

class PonsTerminalArchive(unittest.TestCase):
    def initialize(self):
        fixture=robinhood_fixture.RobinhoodWindowArchive();f,pons,ramses=fixture.initialize();self.addCleanup(fixture.doCleanups)
        roots=os.environ.get('MM_TEST_LANE_WORKTREES')
        if not roots:self.skipTest('requires prepared native lanes')
        self.native=Path(roots)/'pons';self.fixture=fixture
        (f.lanes/'pons/directional-sleeve.sqlite').unlink()
        return f
    def populate(self,f,index,count=4):
        lane=f.lanes/'pons'
        for name in ('robinhood_research','robinhood_tests'):
            link=lane/name
            if not link.exists():link.symlink_to(self.native/name,target_is_directory=True)
        window=dict(f.window,index=index,workflow_run_id=index+1)
        result=subprocess.run([sys.executable,'-c',POPULATE,str(lane),str(f.run/'shared-robinhood-evidence.candidates.sqlite'),canonical(window),str(count)],
            cwd=self.native,env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2])),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return window,json.loads(result.stdout)
    def test_changing_trials_capital_and_reentry_plateau(self):
        f=self.initialize();sizes=[];last=None
        for index in range(6):
            window,before=self.populate(f,index)
            if last:window['parent_state_hash']=last
            output,runtime,artifact=self.fixture.staged(f,index)
            body=transfer.seal(output/'capsule',worktrees=f.lanes,run=runtime,window=window,terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
            folder=output/'capsule/files/pons/pons-selective-continuation-v1-cohort'
            # Current-window re-entry vectors/trials remain exact; older expired
            # trials, capital entries and controllers leave the hot copy.
            self.assertEqual(len(list(folder.glob('trial-*.sqlite'))),4)
            self.assertEqual(len((folder/'qualifiers.jsonl').read_text().splitlines()),4)
            with sqlite3.connect(folder/'pons-selective-cohort-capital.sqlite') as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM capital_positions').fetchone()[0],4)
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            if index:self.assertEqual(body['pons_terminal_handoff']['retired_count'],4)
            self.assertEqual(before['next_index'],4*(index+1));self.assertEqual(before['qualified'],4*(index+1))
            next_work=f.root/'next-lanes';next_run=f.root/'next-run'
            transfer.restore(output/'capsule',worktrees=next_work,run=next_run,expected_identity=f.identity,expected_state_hash=body['state_hash'],campaign_id=window['campaign_id'],prior_index=index,authorization_hash=window['authorization_hash'])
            sizes.append(sum(p.stat().st_size for p in next_work.rglob('*') if p.is_file())+sum(p.stat().st_size for p in next_run.rglob('*') if p.is_file()))
            shutil.rmtree(f.lanes);shutil.rmtree(f.run);next_work.rename(f.lanes);next_run.rename(f.run);last=body['state_hash']
        self.assertLessEqual(max(sizes[2:])-min(sizes[2:]),65536,sizes)
        # The archived controller must pass the real normal-window recovery
        # boundary, retaining cumulative trial identity and recent re-entry.
        f.body=body;f.capsule=output/'capsule';claim=f.claim(index=6)
        claim['previous'].update(index=5,workflow_run_id=6,discovery_window=window)
        claim['previous']['positions']={lane:['original-paper-books:position'] if lane in ('pump','pons') else [] for lane in transfer.LANES}
        claim['window']['positions']=claim['previous']['positions']
        transfer.prepare_window(claim,worktrees=f.target,run=f.target_run,phase='hourly',seconds=3600,prior_state=f.capsule)
        code=r'''
import json,os,sys
from pathlib import Path
from contextlib import chdir
from unittest.mock import patch
from certification import campaign_state
from certification.robinhood.pons import recover_cohort
from robinhood_research.pons_selective_cohort import _next_trial_index,_qualifier_count
from robinhood_research.pons_selective_continuation import POLICY_HASH
from robinhood_research.pons_selective_capital import CohortCapital
expected=json.loads(sys.argv[1]);root=Path(sys.argv[2]);runtime=Path(sys.argv[3])
with chdir(root),patch.object(campaign_state,'identity',return_value=expected),patch.dict(os.environ,
 MM_AUTONOMOUS_STATE_RECEIPT=str(runtime/'restored-campaign-state.json'),MM_CERTIFICATION_RUN_ID='original-paper-books'):
 value=recover_cohort(runtime/'shared-robinhood-evidence.candidates.sqlite',POLICY_HASH)
 assert _next_trial_index(value)==24 and _qualifier_count(value)==24
 assert [x['index'] for x in value['qualifiers']]==list(range(20,24))
 assert value['autonomous_predecessor']['index']==5
 book=CohortCapital(root/'pons-selective-continuation-v1-cohort/pons-selective-cohort-capital.sqlite',1000000)
 assert book.reconcile()==json.loads(sys.argv[4])
 # A transport receipt alone is not successor discovery authority.
 path=runtime/'autonomous-window-claim.json';claim=json.loads(path.read_text())
 claim['window'].update(mode='position',entry_authority=False);path.write_text(json.dumps(claim))
 try:recover_cohort(runtime/'shared-robinhood-evidence.candidates.sqlite',POLICY_HASH)
 except ValueError:pass
 else:raise AssertionError('position-only receipt granted discovery')
 assert book.reconcile()==json.loads(sys.argv[4])
'''
        result=subprocess.run([sys.executable,'-c',code,canonical(f.identity),str(f.target/'pons'),str(f.target_run),canonical(before['accounting'])],cwd=self.native,
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2])),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        print('Pons D1 changing terminal trials: 24 trials, retained 4; hot bytes',sizes)

    def test_compaction_cuts_recover_from_preserved_predecessor_and_reject_corruption(self):
        from certification import pons_terminal_archive as archive
        from certification.autonomous_window import checksum,verify_snapshot
        f=self.initialize();self.populate(f,0);window,before=self.populate(f,1)
        window['parent_state_hash']=f.body['state_hash']
        output,runtime,artifact=self.fixture.staged(f,1)
        source=f.lanes/'pons/pons-selective-continuation-v1-cohort/pons-selective-cohort-capital.sqlite'
        original=checksum(source)
        for cut in ('before_commit','after_books'):
            capsule=output/cut
            with patch.object(archive,'externalize',return_value=None):
                transfer.seal(capsule,worktrees=f.lanes,run=runtime,window=window,terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
            (capsule/'campaign-state.json').unlink()
            code=r'''
import json,sys
from pathlib import Path
from unittest.mock import patch
from certification import pons_terminal_archive as a
from robinhood_research.pons_selective_capital import CohortCapital
original=CohortCapital._reconcile
calls=[0]
def fail(self,db):
 if a.anchor(db):raise SystemExit('before commit')
 return original(self,db)
try:
 if sys.argv[4]=='before_commit':
  with patch.object(CohortCapital,'_reconcile',fail):a._compact(sys.argv[1],sys.argv[2],json.loads(sys.argv[3]))
 else:
  with patch.object(a,'_publish_controller',side_effect=SystemExit('after books')):a._compact(sys.argv[1],sys.argv[2],json.loads(sys.argv[3]))
except SystemExit:pass
else:raise AssertionError('cut not exercised')
'''
            result=subprocess.run([sys.executable,'-c',code,str(capsule),str(artifact),canonical(window),cut],cwd=self.native,
                env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2])),capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertFalse((capsule/'campaign-state.json').exists());self.assertEqual(checksum(source),original)
            with sqlite3.connect(capsule/'files/pons/pons-selective-continuation-v1-cohort/pons-selective-cohort-capital.sqlite') as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM capital_positions').fetchone()[0],8 if cut=='before_commit' else 4)
                with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM capital_journal')
        good=output/'recovered'
        body=transfer.seal(good,worktrees=f.lanes,run=runtime,window=window,terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
        self.assertEqual(body['pons_terminal_handoff']['retired_count'],4)
        self.assertTrue(verify_snapshot(artifact)['snapshot_complete'])
        # A recovered expired identity cannot recreate allocation or settle twice.
        code=r'''
import json,os,sqlite3,sys
from pathlib import Path
from unittest.mock import patch
from certification.lifecycle_identity import issue
from certification.pons_terminal_archive import anchor,controller_anchor
from robinhood_research.pons_selective_capital import CohortCapital
from robinhood_research.pons_selective_cohort import _next_trial_index,_qualifier_count
root=Path(sys.argv[1]);os.chdir(root);path=root/'pons-selective-continuation-v1-cohort/pons-selective-cohort-capital.sqlite'
book=CohortCapital(path,1000000);before=book.reconcile();window=json.loads(sys.argv[2])
with patch('certification.campaign_state.active_window',return_value=dict(window,index=0)):old=issue('trial:0')
with patch('certification.campaign_state.active_window',return_value=dict(window,index=2)):
 try:book.reserve(old,120,at=7200,decision_hash='old',trial_path='trial-0.sqlite')
 except ValueError:pass
 else:raise AssertionError('archived entry replay')
assert book.reconcile()==before
with sqlite3.connect(path) as db:
 value=anchor(db);value['folded']['realized']+=1
 db.execute('UPDATE capital_archive SET body=?',(json.dumps(value),))
try:book.reconcile()
except ValueError:pass
else:raise AssertionError('corrupt capital anchor accepted')
'''
        result=subprocess.run([sys.executable,'-c',code,str(good/'files/pons'),canonical(window)],cwd=self.native,
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2])),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
