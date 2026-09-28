"""Six real native books cross the actual campaign snapshot/restore boundary.

Provider observations are deterministic fixtures. This proves state transport and
native reconciliation, not current-market evidence health or profitability.
"""
import json
import io
import shutil
import zipfile
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from certification import campaign_state as state
from certification.autonomous_positions import native_proof,live_ids
from certification.autonomous_window import stage,verify_snapshot,extract_artifact
from certification.market_assurance import native_positions,continuity

COMMON=r'''
import json,os,sys
from pathlib import Path
from unittest.mock import patch
from certification.offline_tests import install_network_guard
install_network_guard()
sys.path.insert(0,os.getcwd())
root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
run=Path(sys.argv[2]);run.mkdir(parents=True,exist_ok=True)
from certification.directional_sleeve import open_sleeve,policies
protocol=json.loads(Path(__import__('certification').__file__).parent.joinpath('profitability_protocol.json').read_text())
os.environ.update(MM_DIRECTIONAL_COMPOSITE_REQUIRED='1',MM_DIRECTIONAL_COHORT_ID=protocol['cohort_id'],
 MM_DIRECTIONAL_SLEEVE_DB=str(root/'directional-sleeve.sqlite'),MM_CERTIFICATION_RUN_ID='gate')
os.environ['MM_CERTIFICATION_RPC_CACHE_DB']=str(run/'shared-robinhood-evidence.sqlite')
'''
PUMP=r'''
from tests.test_evidence_runtime_cutover import ProductionCutover
from meme_machine.pump_evidence_execution import CachedExecutionRPC
from certification.archive_native import copy_snapshot
case=ProductionCutover();case.setUp()
try:
 original=CachedExecutionRPC.__init__
 def virtual(rpc,*args,**kwargs):original(rpc,*args,**kwargs,clock=lambda:case.clock[0])
 with patch.object(CachedExecutionRPC,'__init__',virtual):case.test_reserved_fill_preempts_saturated_background()
 records=[]
 copy_snapshot(Path(case.temp.name)/'book',root/'pump-acceleration-natural-prospective.accounting.sqlite3',records)
 copy_snapshot(case.writer.path,run/'solana-evidence-plane.sqlite',records)
 assert not any(r.get('error_type') for r in records),records
finally:case.tearDown()
capital=1_000_000_000
from meme_machine.pumpswap_survivor import POLICY_HASH,STRATEGY_ID,POLICY
folder=root/'pump-survivor'
'''
PONS=r'''
from contextlib import chdir
from robinhood_tests.test_pons_current_recovery import CurrentRecoveryTests
from robinhood_research import pons_selective_paper as native
class Captured(BaseException):pass
with chdir(root),patch.object(native,'resume_lifecycle',side_effect=Captured()):
 try:CurrentRecoveryTests().case('pons-selective-continuation-v1-cohort','runner_mark')
 except Captured:pass
 else:raise AssertionError('actual native partial was not captured')
capital=native.STRATEGY_CAPITAL_QUOTE
from robinhood_research.pons_postgrad_survivor import POLICY_HASH,STRATEGY_VERSION as STRATEGY_ID,POLICY
folder=root/'pons-selective-continuation-v1-cohort/pons-survivor'
from certification.robinhood.plane import Plane
plane=Plane(run/'shared-robinhood-evidence.candidates.sqlite');plane.close()
'''
SURVIVOR=r'''
from contextlib import nullcontext
from certification.survivor_paper_book import PaperBook
from certification.survivor_history import History
from certification.survivor_commit import commit,monitor,restore_risk
from certification.tests.test_survivor_risk_boundaries import POLICIES
lane=sys.argv[3];folder.mkdir(parents=True,exist_ok=True)
book=PaperBook(folder/'paper.sqlite',run_id='gate',lane=STRATEGY_ID,policy_hash=POLICY_HASH,initial=capital)
sleeve=open_sleeve(lane,capital)
history=History(folder/'history.sqlite',policy=POLICY_HASH)
row=history.graduate('survivor-candidate',dict(at=0,identity='fixture-authenticated-graduation'))
history.append(row['id'],through=3600,events=[],points=[(0,'100'),(3600,'110')],complete=True)
regime=dict(at=1,base_id='base',high_reset_cycle='cycle',buyer_population=['a'])
decision=dict(candidate=True,policy_hash=POLICY_HASH,features=dict(independent_buyers=20))
sleeve.observe(row['id'],strategy=STRATEGY_ID,at=1,state='qualified',evidence=decision,regime=regime)
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
 def exit_quote(self,qty):return dict(quantity=qty,net_proceeds=32,gas=0)
 def validate_exit(self,e,qty,now):assert e['quantity']==qty
adapter=Adapter();adapter.at=3600
identity='gate:'+STRATEGY_ID+':partial'
receipt=commit(book=book,sleeve=sleeve,identity=identity,candidate=row['id'],generation=1,
 strategy=STRATEGY_ID,policy_hash=POLICY_HASH,decision=decision,regime=regime,at=3600,
 target=100,minimum=10,retention_bps=6500 if lane=='pump' else 6000,ordinary_limit=600,
 stress_limit=600,adapter=adapter,qualify=lambda facts:facts)
assert receipt['status']=='filled',receipt
adapter.at=3601
obs=dict(id='original-partial',at=3601,after_cost_return_bps=POLICIES[lane]['first_profit_bps'],
 net_exit_proceeds=125,exit_liquidity_valid=True)
action=monitor(book=book,sleeve=sleeve,identity=identity,observation=obs,policy=POLICIES[lane],adapter=adapter)
assert action['action']=='partial_exit'
row=history.get(row['id']);row.update(position=identity,state='runner');history.save(row)
assert restore_risk(book,identity)['realization_taken']
book.close();sleeve.close();history.close()
'''
METEORA=r'''
from tests.test_dlmm_independent_accounting import DurableIndependentAccounting
from tests import solana_dlmm_independent_v1 as native
from meme_machine.dlmm_independent_accounting import PaperBook
case=DurableIndependentAccounting();case.setUp()
try:
 case.path=root/'solana-dlmm-independent-v1-live.accounting.sqlite3'
 case.book=PaperBook(case.path,run_id='gate',policy_hash=native.digest(case.policy),capital=1_000_000_000)
 count=[0]
 def observe(*args):
  count[0]+=1
  if count[0]>1:raise SystemExit('cut after first native mark')
  return case.observe(*args)
 with patch.object(native,'_rotate',side_effect=lambda a,*args:a),patch.object(native,'_observe_window',side_effect=observe):
  try:native._lifecycle(None,case.entry['pool'],case.entry,case.features,case.policy,None,[],book=case.book)
  except SystemExit:pass
  else:raise AssertionError('native mark cut not reached')
finally:case.doCleanups()
'''
RAMSES=r'''
from robinhood_research.ramses_campaign import CampaignBooks
from robinhood_research.ramses_strategy import USDG_ADDRESS
from robinhood_tests.test_ramses_strategy import RamsesStrategyTests
from robinhood_tests.test_ramses_continuous_campaign import screen
fixture=RamsesStrategyTests();decision=fixture._decision();capital=decision['freeze']['proposals'][0]['capital_employed']
campaign=CampaignBooks(root/'robinhood-ramses-extended-market.sqlite.campaign',
 screen([dict(token_y=USDG_ADDRESS,paper_capital_quote_raw=capital+1000)]))
book=campaign.ledger(USDG_ADDRESS);book.reserve('original-ramses',pool='pool',decision=decision,at=1000);book.open('original-ramses',at=1000)
path=root/'robinhood-ramses-continuation.json'
path.write_text(json.dumps(dict(schema='ramses-position-continuation-v1',lifecycle_id='original-ramses',
 ledger_path=str(book.path),paper_capital=capital+1000,quote_asset=USDG_ADDRESS,pool='pool',entry_at=1000,entry_block=100,
 decision=decision,segments=[],rebalances=0,current_capital=capital,segment_start=100,position_phase='deployed',costs=fixture._costs())))
campaign.close()
'''

class AutonomousNativeHandoff(unittest.TestCase):
    def test_all_six_native_regimes_reconcile_after_snapshot_and_relocated_restore(self):
        value=os.environ.get('MM_TEST_LANE_WORKTREES')
        if not value:self.skipTest('requires prepared native lanes')
        sources=Path(value);repo=Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);work=root/'source';output=root/'output';run=output/'certification-hourly';identity=state.identity()
            scripts={'pump':PUMP+SURVIVOR,'pons':PONS+SURVIVOR,'meteora':METEORA,'ramses':RAMSES}
            for lane,script in scripts.items():
                process=subprocess.run([sys.executable,'-c',COMMON+script,str(work/lane),str(run),lane],
                    cwd=sources/lane,env=dict(os.environ,PYTHONPATH=str(repo)),capture_output=True,text=True,timeout=40)
                self.assertEqual(process.returncode,0,lane+'\n'+process.stdout+process.stderr)
            before={lane:native_proof(lane,work/lane,sources/lane) for lane in state.LANES}
            positions={lane:native_positions(work/lane,lane) for lane in state.LANES}
            self.assertEqual({lane:len(live_ids(row)) for lane,row in positions.items()},
                             {'pump':2,'pons':2,'meteora':1,'ramses':1})
            self.assertTrue(all(row['durable_handoff'] for row in before.values()))
            window=dict(campaign_id='native-handoff-fixture',index=0,workflow_run_id=1,
                        native_run_id='gate',authorization_hash='a'*64)
            terminal=dict(status='FINISHED',phase='hourly',integration_sha=identity['integration_sha'],
                implementation_hash=identity['implementation_hash'],lanes={lane:dict(exit_code=0,
                accounting_reconciled=True,terminal_reconciliation=proof) for lane,proof in before.items()})
            (run/'result.json').write_text(json.dumps(terminal))
            artifact=stage(work,output,'hourly')
            self.assertTrue(verify_snapshot(artifact)['snapshot_complete'])
            capsule=state.seal(output/'capsule',worktrees=work,run=run,window=window,
                               terminal=terminal,expected_identity=identity)
            from unittest.mock import patch
            from certification import autonomous_transfer
            from certification.tests.test_autonomous_transfer import ArtifactAPI,preserve
            review=dict(passed=True,identity=identity,state_hash=capsule['state_hash'])
            (output/'window-review.json').write_text(json.dumps(review))
            (output/'smoke-continuation-state.json').write_text('{}')
            (artifact/'assurance').mkdir()
            (artifact/'assurance/market-assurance.json').write_text('{}')
            prior_claim=dict(identity=identity,campaign_id=window['campaign_id'],
                authorization_hash=window['authorization_hash'],window=dict(window,mode='hourly'))
            api=ArtifactAPI()
            with patch.object(autonomous_transfer,'PART_BYTES',256*1024):
                reference,transport=preserve(api,output,root/'transport',prior_claim)
                self.assertGreater(len(transport['parts']),1)
                downloaded=extract_artifact(api,reference,root/'downloaded')
            self.assertNotIn(transport['native_artifact']['name'],api.downloads)
            self.assertEqual(json.loads((downloaded/'transfer-proof.json').read_text())['state_hash'],capsule['state_hash'])
            # No absolute path back to the old worker can supply missing state.
            shutil.rmtree(work);shutil.rmtree(output)

            prior=dict(window,state_hash=capsule['state_hash'],positions={lane:live_ids(row) for lane,row in positions.items()},
                       discovery_window=window,artifact=reference)
            claim=dict(schema='autonomous-paper-window-claim-v1',identity=identity,campaign_id=window['campaign_id'],
                authorization_hash=window['authorization_hash'],certificate=dict(identity,passed=True),previous=prior,
                window=dict(index=1,mode='hourly',seconds=3600,workflow_run_id=2,native_run_id='gate',
                            entry_authority=True,nonce='c'*32,parent_state_hash=capsule['state_hash'],positions=prior['positions']))
            successor=root/'relocated';runtime=root/'relocated-runtime';runtime.mkdir()
            state.prepare_window(claim,worktrees=successor,run=runtime,prior_state=downloaded/'capsule',phase='hourly',seconds=3600)
            compact_survivor='''import json,sqlite3,sys
from pathlib import Path
from certification.survivor_paper_book import PaperBook
path=Path(sys.argv[1])
with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
    identity=json.loads(db.execute('SELECT body FROM genesis').fetchone()[0])
book=PaperBook(path,**identity)
assert book._archive() is not None
assert book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0]==0
assert book.replay()['verified'] is True
book.close()
'''
            for lane in ('pump','pons'):
                folder='pump-survivor' if lane=='pump' else 'pons-selective-continuation-v1-cohort/pons-survivor'
                process=subprocess.run([sys.executable,'-c',compact_survivor,str(successor/lane/folder/'paper.sqlite')],
                    cwd=sources/lane,env=dict(os.environ,PYTHONPATH=str(repo),
                        MM_AUTONOMOUS_STATE_RECEIPT=str(runtime/'restored-campaign-state.json'),
                        MM_CERTIFICATION_RUN_ID='gate'),capture_output=True,text=True,timeout=30)
                self.assertEqual(process.returncode,0,process.stdout+process.stderr)
            reopen='''import sys
from pathlib import Path
from robinhood_research.ramses_campaign import CampaignBooks
book=CampaignBooks.recover(Path(sys.argv[1])/'robinhood-ramses-extended-market.sqlite.campaign')
assert book.reconcile()['open_positions']==1
book.close()
'''
            process=subprocess.run([sys.executable,'-c',reopen,str(successor/'ramses')],cwd=sources/'ramses',
                env=dict(os.environ,PYTHONPATH=str(repo),MM_CERTIFICATION_RPC_CACHE_DB=str(runtime/'shared-robinhood-evidence.sqlite')),
                capture_output=True,text=True,timeout=30)
            self.assertEqual(process.returncode,0,process.stdout+process.stderr)
            for lane in state.LANES:
                restored=native_proof(lane,successor/lane,sources/lane)
                self.assertEqual(restored['accounting'],before[lane]['accounting'],lane)
                self.assertEqual(restored['open_positions'],before[lane]['open_positions'])
                self.assertTrue(restored['durable_handoff'])
                after=native_positions(successor/lane,lane)
                proof=continuity(positions[lane],after)
                self.assertEqual(proof['status'],'pass',(lane,proof))
                self.assertEqual(after['natural_entries'],positions[lane]['natural_entries'])
                for path in (successor/lane).rglob('*'):
                    if path.is_file() and path.read_bytes()[:16]==b'SQLite format 3\x00':
                        with sqlite3.connect(path) as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))

            from certification.survivor_history import History
            for lane in ('pump','pons'):
                folder=successor/lane/('pump-survivor' if lane=='pump' else 'pons-selective-continuation-v1-cohort/pons-survivor')
                with sqlite3.connect(folder/'history.sqlite') as db:
                    policy=json.loads(db.execute("SELECT body FROM meta WHERE key='policy'").fetchone()[0])
                history=History(folder/'history.sqlite',policy=policy)
                history.append('survivor-candidate',through=14400,events=[],points=[(14400,'120')],complete=True)
                row=history.get('survivor-candidate')
                self.assertEqual(row['graduation']['at'],0)
                self.assertEqual(row['through'],14400)
                self.assertIn(row['position'],prior['positions'][lane])
                history.close()
            from copy import deepcopy
            from certification.autonomous_window import bound_window
            next_window=bound_window(claim)
            next_terminal=deepcopy(terminal)
            for lane in state.LANES:
                next_terminal['lanes'][lane]['terminal_reconciliation']=native_proof(lane,successor/lane,sources/lane)
            second=state.seal(root/'second-capsule',worktrees=successor,run=runtime,window=next_window,
                              terminal=next_terminal,expected_identity=identity)
            position_claim=deepcopy(claim)
            position_claim['previous']=dict(next_window,state_hash=second['state_hash'],
                positions=prior['positions'],discovery_window=next_window,artifact={'digest':'sha256:'+'d'*64})
            position_claim['window'].update(index=2,mode='position',seconds=3000,workflow_run_id=3,
                entry_authority=False,parent_state_hash=second['state_hash'])
            position_root=root/'position-only';position_runtime=position_root/'certification-position'
            state.restore(root/'second-capsule',worktrees=position_root/'certification-native/position',
                run=position_runtime,expected_identity=identity,expected_state_hash=second['state_hash'],
                campaign_id=window['campaign_id'],prior_index=1,authorization_hash=window['authorization_hash'])
            (position_root/'autonomous-position-authority.json').write_text(json.dumps(position_claim))
            code='''import sys,json
from certification.position_continuation import _runtime_identity
row=_runtime_identity(sys.argv[1],sys.argv[2])
assert row['entry_authority'] is False
print(json.dumps(row))
'''
            for lane in state.LANES:
                result=subprocess.run([sys.executable,'-c',code,str(position_root),lane],cwd=sources/lane,
                    env=dict(os.environ,PYTHONPATH=str(repo)),capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,lane+'\n'+result.stdout+result.stderr)
                self.assertEqual(json.loads(result.stdout)['campaign_id'],window['campaign_id'])
                proof=native_proof(lane,position_root/'certification-native/position'/lane,sources/lane)
                self.assertEqual(proof['accounting'],before[lane]['accounting'])

            process=subprocess.run([sys.executable,'-c',reopen,str(position_root/'certification-native/position/ramses')],
                cwd=sources/'ramses',env=dict(os.environ,PYTHONPATH=str(repo),
                    MM_CERTIFICATION_RPC_CACHE_DB=str(position_runtime/'shared-robinhood-evidence.sqlite')),
                capture_output=True,text=True,timeout=30)
            self.assertEqual(process.returncode,0,process.stdout+process.stderr)

            # Exercise the production position workflow adapter with all six
            # real restored states and a real child-process failure. Only the
            # external evidence transport is replaced; native replay is actual.
            from unittest.mock import patch
            from certification import autonomous_positions as adapter
            predecessor=root/'adapter-predecessor';predecessor.mkdir()
            shutil.copytree(root/'second-capsule',predecessor/'capsule')
            output=root/'adapter-failure';output.mkdir()
            processes=[];commands=[];closed=[]
            real_popen=subprocess.Popen
            def launch_child(command,**kwargs):
                if 'certification.position_continuation' not in command:
                    return real_popen(command,**kwargs)
                lane=command[command.index('--lane')+1];commands.append(command)
                authority=Path(kwargs['env']['MM_AUTONOMOUS_POSITION_STATE'])/'autonomous-position-authority.json'
                value=json.loads(authority.read_text())
                self.assertFalse(value['window']['entry_authority'])
                self.assertEqual(value['identity'],identity)
                self.assertEqual(value['window']['positions'],prior['positions'])
                code='import sys;sys.exit(7)' if lane=='pons' else 'import time;time.sleep(60)'
                process=real_popen([sys.executable,'-c',code],**kwargs);processes.append(process)
                return process
            class EvidenceFixture:
                def __init__(self,*args):pass
                def start(self):pass
                def check(self):return dict(lanes={lane:dict(usable=True) for lane in ('pump','meteora')})
                def snapshot(self):return dict(fixture='provider-free-process-failure')
                def close(self):closed.append(True);return dict(clean=True)
            with patch.object(subprocess,'Popen',side_effect=launch_child), \
                    patch('certification.evidence_supervisor.EvidenceProcess',EvidenceFixture):
                with self.assertRaisesRegex(ValueError,'autonomous_position_process_failed'):
                    adapter.run(position_claim,sources,output,predecessor)
            self.assertEqual(len(commands),4);self.assertEqual(closed,[True])
            self.assertTrue(all(process.poll() is not None for process in processes))
            self.assertFalse((output/'capsule').exists())
            self.assertTrue(verify_snapshot(output/'artifact')['snapshot_complete'])
            failure=json.loads((output/'position-state/certification-position/failure.json').read_text())
            self.assertEqual(failure['status'],'FAILED');self.assertFalse(failure['entry_authority'])
            for lane in state.LANES:
                copied=output/'artifact/certification-native/position'/lane
                self.assertEqual(native_proof(lane,copied,sources/lane)['accounting'],before[lane]['accounting'])
