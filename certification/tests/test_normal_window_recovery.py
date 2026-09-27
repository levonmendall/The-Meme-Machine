"""Native recovered management and discovery share the original campaign books."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

RAMSES_SCRIPT=r'''
import atexit,json,os,tempfile,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from certification import lifecycle_timing as timing,position_continuation as continuation
from certification.terminal_reconciliation import reconcile
from robinhood_research import BoundaryError,ramses_extended_test as extended,ramses_all_pool_lifecycle as native
from robinhood_research.ramses_campaign import CampaignBooks
from robinhood_tests.test_ramses_continuous_campaign import screen,ASSET
from robinhood_tests.test_ramses_connected_lifecycle import _decision
with tempfile.TemporaryDirectory() as td:
 root=Path(td);folder=root/'robinhood-ramses-extended-market.sqlite.campaign'
 campaign=CampaignBooks(folder,screen([dict(token_y=ASSET,paper_capital_quote_raw=1000)]))
 book=campaign.ledger(ASSET);decision=_decision()
 book.reserve('original',pool='pool',decision=decision,at=10);book.open('original',at=10)
 path=root/'robinhood-ramses-continuation.json'
 path.write_text(json.dumps(dict(schema='ramses-position-continuation-v1',lifecycle_id='original',
  ledger_path=str(book.path),paper_capital=1000,quote_asset=ASSET,pool='pool',entry_at=10,entry_block=1,
  decision=decision,segments=[],rebalances=0,current_capital=100,segment_start=1,position_phase='deployed',
  costs=dict(mint=1,unwind=1,rebalance=1))))
 before=campaign.reconcile();campaign.close()
 assert reconcile('ramses',root)['durable_handoff']
 claim=dict(identity={'frozen':'exact'},campaign_id='same-campaign',authorization_hash='same-authority',
  window=dict(index=1,positions={'ramses':['original']}))
 ready=threading.Event();release=threading.Event();clock=[0]
 def scan(*args,**kwargs):
  ready.set();assert release.wait(5),'recovery blocked discovery caller'
  return dict(rows=[])
 class Rpc:
  def __init__(self,*a,**k):pass
  def verify_chain(self):pass
  def call(self,*a,**kw):
   clock[0]+=100
   raise BoundaryError('provider_http_429')
 rpc=Rpc()
 def sleep(seconds):clock[0]+=1
 real_resume=continuation._resume_ramses_native
 def bounded(*a,**kw):
  kw['slice_seconds']=20
  return real_resume(*a,**kw)
 with patch.dict(os.environ,MM_CERTIFICATION_PHASE='hourly'),patch('certification.campaign_state.restored_window',return_value=claim),patch.object(continuation,'_resume_ramses_native',side_effect=bounded),patch.object(continuation,'time',SimpleNamespace(monotonic=lambda:clock[0],sleep=sleep,time=lambda:1000)),patch.object(native,'BoundedMultiRpc',Rpc),patch.object(native,'_new_position_reader',return_value=rpc),patch.object(native,'scan',side_effect=scan):
  timing.install_ramses(extended)
  campaign=CampaignBooks.recover(folder)
  assert ready.wait(5)
  assert campaign.reconcile()==before
  thread=timing._RAMSES_STATE['thread'];assert thread.is_alive()
  original_sidecar=path.read_bytes()
  # Actual production discovery calls the selector; it stays observable and
  # capacity-censored, while other lanes retain their own entry authority.
  for _ in range(3):assert extended.select_qualifier(screen([])) is None
  assert timing.ramses_continuation_snapshot()['state']['observations_while_occupied']==3
  assert path.read_bytes()==original_sidecar,'discovery overwrote controller checkpoint'
  try:CampaignBooks.recover(folder)
  except RuntimeError as exc:assert str(exc)=='ramses_recovery_duplicate_controller'
  else:raise AssertionError('duplicate recovered worker')
  release.set();thread.join(5);assert not thread.is_alive()
  assert timing._RAMSES_STATE['error'] is None,timing._RAMSES_STATE['error']
  after=campaign.reconcile();assert after==before
  proof=reconcile('ramses',root);assert proof['durable_handoff'],proof
  saved=json.loads(path.read_text())
  assert saved['entry_at']==10 and saved['entry_block']==1
  assert saved['last_controller']['boundary']=='provider_http_429'
  assert saved['last_native_version']==campaign.books[ASSET].position('original')['version']
  actions=[a for a, in campaign.books[ASSET].db.execute('SELECT action FROM ramses_strategy_journal')]
  assert actions.count('reserve')==actions.count('open')==1
  assert actions.count('monitor')==1 and actions.count('settle')==0
  assert saved['result']['handoff_required'] and 'state' not in saved['result']
 campaign.close();atexit.unregister(timing._ramses_write_state)
print('actual Ramses recovery worker, concurrent discovery, provider hold and durable handoff pass')
'''

class NormalWindowRecoveryTests(unittest.TestCase):
    def test_existing_ramses_position_starts_native_monitor_while_discovery_continues(self):
        roots=os.environ.get('MM_TEST_LANE_WORKTREES')
        if not roots:self.skipTest('requires prepared native lanes')
        repo=Path(__file__).resolve().parents[2]
        result=subprocess.run([sys.executable,'-c',RAMSES_SCRIPT],cwd=Path(roots)/'ramses',
            env=dict(os.environ,PYTHONPATH=str(repo)),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
