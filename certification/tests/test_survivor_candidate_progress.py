"""A full discovery hot set cannot permanently starve native candidate retirement."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = r'''
import json,tempfile
from pathlib import Path
from unittest.mock import MagicMock
from certification.survivor_history import History
if LANE == 'pump':
    from meme_machine.pumpswap_survivor_runtime import Runtime
else:
    from robinhood_research.pons_survivor_runtime import Runtime

with tempfile.TemporaryDirectory() as td:
    history=History(Path(td)/'history',policy='offline-scheduler-probe',maximum_candidates=1)
    history.graduate('expired',dict(at=0))
    runtime=Runtime.__new__(Runtime)
    runtime.history=history
    runtime.now=lambda:604802
    runtime.last_error=None
    runtime._provider=lambda:None
    attempts=[]
    def discover():
        attempts.append('discovery')
        history.graduate('new',dict(at=604802))
    runtime.discover=discover
    runtime.book=MagicMock()
    runtime.book.reconcile.return_value={}
    runtime.book.replay.return_value={}
    runtime.book.positions.return_value=[]
    runtime.sleeve=MagicMock()
    runtime.sleeve.identity={'policies':{}}
    runtime.sleeve.reconcile.return_value={}
    runtime.plane=MagicMock()
    try:
        result=runtime.step(admit=True)
        assert history.get('expired')['state']=='retired', result['last_boundary']
        assert len(history.rows())==0
        assert history.get('expired')['graduation']==dict(at=0)
        history.close()
        history=History(Path(td)/'history',policy='offline-scheduler-probe',maximum_candidates=1)
        assert history.get('expired')['state']=='retired'
        assert len(history.rows())==0
    finally:
        history.close()
print('bounded native candidate retirement survives saturated discovery and restart')
'''

AGE_SCRIPT = r'''
import tempfile
from pathlib import Path
from unittest.mock import MagicMock,patch
from certification.survivor_history import History
if LANE == 'pump':
    from meme_machine import pumpswap_survivor_runtime as native
    minimum=native.POLICY['minimum_age_seconds']
else:
    from robinhood_research import pons_survivor_runtime as native
    minimum=native.POLICY['universe']['min_seconds_after_graduation']
class ReachedFreshRevalidation(RuntimeError):pass
with tempfile.TemporaryDirectory() as td:
    history=History(Path(td)/'history',policy='offline-age-binding')
    row=history.graduate('candidate',dict(at=0))
    row['block']=0;history.save(row)
    runtime=native.Runtime.__new__(native.Runtime)
    runtime.history=history;runtime.last_error=None
    runtime._provider=lambda:None;runtime.discover=lambda:None
    runtime._increment=lambda *a:None;runtime.rpc=None
    runtime.book=MagicMock();runtime.sleeve=MagicMock();runtime.plane=MagicMock()
    runtime.sleeve.identity={'policies':{}}
    runtime.plane.frontier.return_value=0
    def fresh(*a,**kw):raise ReachedFreshRevalidation()
    runtime.fresh_state=fresh
    try:
        for age in (minimum-1,minimum):
            runtime.now=lambda:age
            runtime.plane.block_time.return_value=age
            context=patch.object(native,'_latest_header',return_value=dict(number='0x0'),create=True)
            reached=False
            with context:
                try:runtime.step(admit=True)
                except ReachedFreshRevalidation:reached=True
            assert reached==(age==minimum),(LANE,age,minimum,history.get('candidate'))
    finally:history.close()
print('runtime age gate uses the actual approved policy boundary')
'''

CAPACITY_SCRIPT = r'''
import tempfile
from pathlib import Path
from certification.survivor_history import History
from robinhood_research.pons_survivor_runtime import Runtime,POLICY
from robinhood_tests.test_pons_postgrad_survivor import winner_points,NOW
with tempfile.TemporaryDirectory() as td:
 h=History(Path(td)/'history',policy='offline-runtime-reconstruction')
 row=h.graduate('candidate',dict(at=NOW-30*3600,record={}))
 row['block']=100;h.save(row)
 events=[]
 for i,g in enumerate(('1','2','3')):
  events.append(dict(id='prior'+g,at=NOW-2000+i,group=g,quote=100,buy=True,authenticated=True))
 for i,g in enumerate(('1','2','4','5','6')):
  events.append(dict(id='current'+g,at=NOW-1000+i,group=g,quote=120,buy=True,authenticated=True))
 h.append('candidate',through=NOW,events=events,points=winner_points(),complete=True)
 r=Runtime.__new__(Runtime);r.history=h;r.current=h.get('candidate');r.capital=10000
 class Quotes:
  def loss(self,n):return 100
 f=r.reconstruct(dict(block=100,at=NOW,price_index=12900),Quotes())
 d=r.qualify(f)
 assert f['execution']['capacity']['original_size']==20,f
 assert d['candidate'],d
 assert d['proposed_quote_amount']==20,d
 assert r.turnover_cap(f,d)==20
 h.close();h=History(Path(td)/'history',policy='offline-runtime-reconstruction')
 r.history=h;r.current=h.get('candidate')
 assert r.qualify(r.reconstruct(dict(block=100,at=NOW,price_index=12900),Quotes()))==d
 h.append('candidate',through=NOW,events=[],points=[],complete=False)
 r.current=h.get('candidate')
 blocked=r.qualify(r.reconstruct(dict(block=100,at=NOW,price_index=12900),Quotes()))
 assert not blocked['candidate'] and 'incomplete_continuity' in blocked['all_rejections']
 h.close()
 print('native reconstruct/qualify/capacity, restart, and continuity gate passed')
'''


PUMP_RECONSTRUCTION_SCRIPT = r'''
import tempfile
from pathlib import Path
from types import SimpleNamespace
from certification.survivor_history import History
from meme_machine.pumpswap_survivor_runtime import Runtime,SOL_USD_ACCOUNT,SWAP_SCOPE,evaluate_entry
from tests.test_pumpswap_survivor import facts
from tests.test_pumpswap_survivor_evidence import EvidenceTests
source=facts();now=source['now']
with tempfile.TemporaryDirectory() as td:
 h=History(Path(td)/'history',policy='offline-runtime-reconstruction')
 row=h.graduate('candidate',dict(at=0,pool='canonical-pump-pool',quote_amount=100,mint_amount=1))
 events=[dict(e,tokens=7) for e in source['demand_events']]
 h.append('candidate',through=now,events=events,points=[(p['at'],p['price']) for p in source['price_points']],complete=True)
 class Reader:
  def window(self,scope,lo,hi,**kw):
   assert scope==SWAP_SCOPE and kw['address']=='canonical-pump-pool' and kw['kind']=='event'
   return []
 class Plane:
  reader=Reader()
  def bounds(self,scope,lo,hi,**kw):
   assert scope==SWAP_SCOPE and lo==hi==now
   return 100,100
  def interest(self,scope,**kw):assert scope==SWAP_SCOPE and kw['addresses']==['canonical-pump-pool']
 class RPC:
  def call(self,method,params,priority):
   assert method=='getTokenLargestAccounts' and params[0]=='candidate' and params[1]['commitment']=='finalized'
   return dict(context=dict(slot=100),value=[])
 r=Runtime.__new__(Runtime);r.history=h;r.current=h.get('candidate');r.plane=Plane();r.rpc=RPC()
 r.now=lambda:now;r.confirmations=SimpleNamespace(cluster=lambda x:x)
 state=dict(mint='candidate',market_time=now,slot=100,creator='creator',
  state=dict(quote_reserve=162*10**10,base_reserve=10**10,raw_quote_reserve=162*10**10,
   base_vault='vault',mint_supply=10**12,mayhem_mode=False),
  additional_accounts={SOL_USD_ACCOUNT:EvidenceTests().oracle(published=now,previous=now-100,posted=100)})
 f=r.reconstruct(state,None);d=evaluate_entry(f)
 assert d['candidate'],d
 assert d['features']['repeat_buyers']==2 and d['features']['turnover_cap']==150,d
 h.close();h=History(Path(td)/'history',policy='offline-runtime-reconstruction')
 r.history=h;r.current=h.get('candidate')
 assert evaluate_entry(r.reconstruct(state,None))==d
 h.append('candidate',through=now,events=[],points=[],complete=False);r.current=h.get('candidate')
 blocked=evaluate_entry(r.reconstruct(state,None))
 assert not blocked['candidate'] and 'authoritative_evidence' in blocked['all_rejections']
 h.close()
print('native Pump reconstruction, oracle/concentration, qualification, restart and continuity gate passed')
'''

class SurvivorCandidateProgressTests(unittest.TestCase):
    def test_capacity_cannot_prevent_expired_candidate_retirement(self):
        self.run_native(SCRIPT)

    def test_runtime_binds_frozen_policy_minimum_age(self):
        self.run_native(AGE_SCRIPT)

    def test_pons_runtime_binds_approved_turnover_capacity(self):
        self.run_native(CAPACITY_SCRIPT,lanes=('pons',))

    def test_pump_native_reconstruction_and_missing_continuity(self):
        self.run_native(PUMP_RECONSTRUCTION_SCRIPT,lanes=('pump',))

    def run_native(self,body,lanes=('pump','pons')):
        root_value=os.environ.get('MM_TEST_LANE_WORKTREES')
        if not root_value:
            self.skipTest('requires canonical prepared native lanes')
        roots=Path(root_value).resolve()
        repo=Path(__file__).resolve().parents[2]
        for lane in lanes:
            with self.subTest(lane=lane):
                self.assertTrue((roots/lane).is_dir(), 'prepared lane missing')
                script='LANE='+repr(lane)+'\n'+body
                proc=subprocess.run([sys.executable,'-c',script],cwd=roots/lane,
                    env=dict(os.environ,PYTHONPATH=str(repo)),capture_output=True,
                    text=True,timeout=20)
                self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
