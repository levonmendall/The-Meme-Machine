import os
from pathlib import Path
import subprocess
import sys
import unittest
from tests.native_inline import run_native

SCRIPT=r'''
import json,tempfile
from pathlib import Path
from meme_machine.runtime.continuity_state import checkpoint,recover
from meme_machine.lanes.ramses.ramses_strategy_ledger import RamsesStrategyLedger
from tests.lanes.ramses.test_ramses_connected_lifecycle import _decision
for lost_after_commit in (False,True):
 with tempfile.TemporaryDirectory() as td:
  p=Path(td);db=p/'book.sqlite';path=p/'state.json'
  book=RamsesStrategyLedger(db,paper_capital=1000,quote_asset='quote')
  book.reserve('position',pool='pool',decision=_decision(),at=10);book.open('position',at=10)
  state=dict(lifecycle_id='position',position_phase='deployed',segments=[],high_water=140)
  next_state=dict(state,position_phase='flat_quote',segments=[{'net_result':-3}],current_capital=97)
  detail=dict(segment=0,end_block=12,net_result_quote=-3,exit_reason='synthetic_test')
  def interrupted(identity,**kw):
   if lost_after_commit:book.checkpoint(identity,**kw)
   raise SystemExit('injected_process_interruption')
  try:checkpoint(book,'position',state=state,path=path,action='segment_close',detail=detail,at=12,next_state=next_state,commit=interrupted)
  except SystemExit:pass
  book.close();state=json.loads(path.read_text())
  book=RamsesStrategyLedger(db,paper_capital=1000,quote_asset='quote')
  assert recover(book,'position',state,path)
  assert state['high_water']==140 and state['current_capital']==97 and len(state['segments'])==1
  assert book.position('position')['segments_closed']==1
  assert book.db.execute("select count(*) from ramses_strategy_journal where action='segment_close'").fetchone()[0]==1
  before=book.reconcile();saved=json.loads(path.read_text())
  assert not recover(book,'position',state,path)
  checkpoint(book,'position',state=state,path=path,action='segment_close',detail=detail,at=12,next_state=dict(state,segments=[{},{}]))
  assert json.loads(path.read_text())==saved and book.reconcile()==before
  book.close()
print('native restart before/after commit, lost acknowledgement and duplicate replay passed')
'''

SHARED_BOOK_SCRIPT=r'''
import atexit,json,os,tempfile,threading
from pathlib import Path
from unittest.mock import patch
from meme_machine.runtime import lifecycle_timing as timing
from meme_machine.lanes.ramses import ramses_extended_test as extended
from meme_machine.lanes.ramses import ramses_all_pool_lifecycle as life
from meme_machine.lanes.ramses.ramses_strategy_ledger import RamsesStrategyLedger
from tests.lanes.ramses.test_ramses_connected_lifecycle import _decision
with tempfile.TemporaryDirectory() as td:
 root=Path(td);book=RamsesStrategyLedger(root/'campaign.sqlite',paper_capital=1000,quote_asset='quote')
 ready=threading.Event();release=threading.Event()
 def run(endpoint,**kw):
  native=kw['campaign_ledger']
  assert Path(native.path)==Path(book.path)
  native.reserve('existing-book-entry',pool='pool',decision=_decision(),at=10)
  native.open('existing-book-entry',at=10);ready.set()
  assert release.wait(5)
  return dict(lifecycle_id='existing-book-entry',status='open',handoff_required=True)
 timing._RAMSES_STATE['state_path']=str(root/'state.json')
 with patch.dict(os.environ,{'MM_OPERATIONAL_PHASE':'hourly'}),patch.object(life,'run',run),patch.object(life,'compact_lifecycle_result',lambda x:x):
  timing.install_ramses(extended)
  receipt=extended.run_connected('unused',campaign_ledger=book,initial_screen=dict(finalized_block=1,finalized_timestamp=10))
  assert receipt['handoff_required'] and ready.wait(5),timing._RAMSES_STATE.get('error')
  snapshot=book.reconcile()
  assert snapshot['open_positions']==1 and snapshot['committed']==100 and snapshot['available']==900
  assert len(list(root.glob('*.sqlite')))==1
  release.set();timing._RAMSES_STATE['thread'].join(5)
  assert book.reconcile()==snapshot
  state=json.loads((root/'state.json').read_text())
  assert state['lifecycle_id']=='existing-book-entry' and state['active']
  assert state['entry_at']==10 and state['current_capital']==100
 book.close();atexit.unregister(timing._ramses_write_state)
print('hourly thread retains the existing funded native book and its reserve')
'''

METEORA_SCRIPT=r'''
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from meme_machine.runtime.position_continuation import restore_meteora_strategy
from meme_machine.runtime.terminal_reconciliation import meteora_handoff
from contextlib import closing
def _meteora_events(path):
 with closing(case.book.connect()) as db:return list(case.book.events(db))
from tests.lanes.meteora.test_dlmm_independent_accounting import DurableIndependentAccounting
from meme_machine.lanes.meteora import runner as m
case=DurableIndependentAccounting();case.setUp()
try:
 root=Path(case.tmp.name);case.policy=m.load_policy();case.path=root/'solana-dlmm-independent-v1-live.accounting.sqlite3';case.book=case.reopen()
 calls=[0]
 def observe(*args):
  calls[0]+=1
  if calls[0]>1:raise RuntimeError('synthetic_process_cut_after_one_mark')
  return case.observe(*args)
 with patch.object(m,'_rotate',side_effect=lambda a,*args:a),patch.object(m,'_observe_window',side_effect=observe):
  try:m._lifecycle(None,case.entry['pool'],case.entry,case.features,case.policy,None,[],book=case.book)
  except RuntimeError as exc:assert str(exc)=='synthetic_process_cut_after_one_mark'
 events=_meteora_events(case.path);marks=[e for e in events if e['action']=='mark']
 assert len(marks)==1
 progress=marks[0]['data']['strategy_progress']
 assert progress['effective_start'] is None and progress['effective_start_hash']==m.digest(case.entry)
 before=case.book.reconcile()
 recovered=restore_meteora_strategy(case.book,m)
 proof=meteora_handoff(events,case.book.reconcile(),case.book.replay_economics(m._build_position,m._advance_position,m._mark))
 assert proof['verified_hold_seconds']==300 and recovered['elapsed']==300
 assert recovered['identity']==marks[0]['identity']
 assert _meteora_events(case.path)==events and case.book.reconcile()==before
finally:case.tearDown();case.doCleanups()
print('Meteora process cut restores compact evidence and elapsed strategy state without a shortened confirmation segment')
'''

METEORA_ASYNC_SCRIPT=METEORA_SCRIPT[:METEORA_SCRIPT.index(" recovered=restore_meteora_strategy")]+r'''
 import os,threading,time
 from contextlib import chdir
 from meme_machine.runtime.position_continuation import restore_meteora_strategy
 from meme_machine.runtime.lifecycle_timing import install_meteora
 recovered=restore_meteora_strategy(case.book,m)
 ready=threading.Event();release=threading.Event();finished=threading.Event()
 observed=[0]
 def next_segment(*args):
  observed[0]+=1
  if observed[0]>1:
   finished.set()
   return dict(verified=False,reason='synthetic_provider_interruption'),None,None,None,None
  ready.set()
  assert release.wait(5), 'discovery was blocked by recovered lifecycle'
  return case.observe(*args)
 with chdir(root),patch.dict(os.environ,MM_OPERATIONAL_PHASE='hourly'),patch.object(m,'_prove_network_identity'),patch.object(m,'_new_adapter',return_value=None),patch.object(m,'EvidenceBroker',return_value=SimpleNamespace(close=lambda:None)),patch.object(m,'_rotate',side_effect=lambda a,*args:a),patch.object(m,'_observe_window',side_effect=next_segment):
  install_meteora(m)
  proxy,_=m._position_lifecycle(None,recovered['entry']['pool'],recovered['entry'],recovered['features'],recovered['policy'],None,[],book=case.book,identity=recovered['identity'],recovered=recovered)
  assert ready.wait(5)
  assert proxy['handoff_required'] and proxy['lifecycle_id']==recovered['identity']
  assert case.book.reconcile()==before
  # This executes on the discovery caller while the real native monitor is blocked.
  discovery_progress=['authenticated candidate while existing capital remains occupied']
  assert discovery_progress and case.book.reconcile()['open_positions']==1
  release.set();assert finished.wait(5),proxy
  workers=[t for t in threading.enumerate() if t.name=='meteora-position-continuation']
  for worker in workers:worker.join(5);assert not worker.is_alive()
  assert not proxy['complete'] and proxy['handoff_required'],proxy
  assert proxy['verified_hold_seconds']==600
  final=case.book.reconcile();assert final['settled']==0 and final['unsettled']==1,final
  journal=_meteora_events(case.path)
  for action in ('reserve','entry'):assert sum(e['action']==action for e in journal)==1
  assert sum(e['action']=='mark' for e in journal)==2
  assert sum(e['action']=='settle' for e in journal)==0
  assert restore_meteora_strategy(case.book,m)['elapsed']==600
  assert journal[2]['data']['entry_state']==recovered['entry']
  assert case.book.replay_economics(m._build_position,m._advance_position,m._mark)['verified']
finally:
 if 'release' in locals():release.set()
 case.tearDown();case.doCleanups()
print('recovered native Meteora lifecycle runs alongside discovery without reentry or a reset clock')
'''

class ContinuityTests(unittest.TestCase):
    def test_meteora_recovered_native_lifecycle_does_not_block_discovery(self):
        self.run_native(METEORA_ASYNC_SCRIPT,lane="meteora")

    def test_async_lifecycle_preserves_campaign_capital(self):
        self.run_native(SHARED_BOOK_SCRIPT)

    def test_repeated_management_uses_same_funded_book(self):
        self.run_native(SHARED_BOOK_SCRIPT.replace("'MM_OPERATIONAL_PHASE':'hourly'","'MM_OPERATIONAL_PHASE':'smoke'"))

    def test_meteora_process_cut_restores_compact_mark_without_boundary_exit(self):
        self.run_native(METEORA_SCRIPT,lane='meteora')

    def test_native_checkpoint_restart_matrix(self):
        self.run_native(SCRIPT)

    def run_native(self,script,lane='ramses'):
        result=run_native(script,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
