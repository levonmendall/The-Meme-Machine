import os
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT=r'''
import json,tempfile
from pathlib import Path
from certification.continuity_state import checkpoint,recover
from robinhood_research.ramses_strategy_ledger import RamsesStrategyLedger
from robinhood_tests.test_ramses_connected_lifecycle import _decision
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
from certification import lifecycle_timing as timing
from robinhood_research import ramses_extended_test as extended
from robinhood_research import ramses_all_pool_lifecycle as life
from robinhood_research.ramses_strategy_ledger import RamsesStrategyLedger
from robinhood_tests.test_ramses_connected_lifecycle import _decision
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
 with patch.dict(os.environ,{'MM_CERTIFICATION_PHASE':'hourly'}),patch.object(life,'run',run),patch.object(life,'compact_lifecycle_result',lambda x:x):
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
from certification.position_continuation import resume_meteora,_meteora_events
from tests.test_dlmm_independent_accounting import DurableIndependentAccounting
from tests import solana_dlmm_independent_v1 as m
case=DurableIndependentAccounting();case.setUp()
try:
 root=Path(case.tmp.name);case.path=root/'solana-dlmm-independent-v1-live.accounting.sqlite3';case.book=case.reopen()
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
 with patch('certification.position_continuation._runtime_identity',return_value=dict(phase='hourly')),patch.object(m,'_prove_network_identity'),patch.object(m,'_new_adapter',return_value=None),patch.object(m,'EvidenceBroker',return_value=SimpleNamespace(close=lambda:None)):
  result=resume_meteora(root,slice_seconds=60)
 assert result['handoff_required'] and result['verified_hold_seconds']==300
 assert _meteora_events(case.path)==events and case.book.reconcile()==before
finally:case.tearDown();case.doCleanups()
print('Meteora process cut restores compact evidence and elapsed strategy state without a shortened confirmation segment')
'''

class ContinuityTests(unittest.TestCase):
    def test_async_lifecycle_preserves_campaign_capital(self):
        self.run_native(SHARED_BOOK_SCRIPT)

    def test_smoke_boundary_also_preserves_campaign_capital(self):
        self.run_native(SHARED_BOOK_SCRIPT.replace("'MM_CERTIFICATION_PHASE':'hourly'","'MM_CERTIFICATION_PHASE':'smoke'"))

    def test_meteora_process_cut_restores_compact_mark_without_boundary_exit(self):
        self.run_native(METEORA_SCRIPT,lane='meteora')

    def test_native_checkpoint_restart_matrix(self):
        self.run_native(SCRIPT)

    def run_native(self,script,lane='ramses'):
        roots=Path(os.environ.get('MM_TEST_LANE_WORKTREES',str(Path(__file__).resolve().parents[3]/'fresh-lanes')))
        if not (roots/lane).exists():self.skipTest('prepared lane unavailable')
        repo=Path(__file__).resolve().parents[2]
        env=dict(os.environ,PYTHONPATH=str(roots/lane)+os.pathsep+str(repo))
        result=subprocess.run([sys.executable,'-c',script],env=env,cwd=roots/lane,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
