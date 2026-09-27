"""Accelerated full native recenter/restart/maximum-hold management; no market claim."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT=r'''
from copy import deepcopy
import json,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from certification import position_continuation as continuation
from certification import continuity_state
from certification.terminal_reconciliation import reconcile
from robinhood_research import ramses_all_pool_lifecycle as native
from robinhood_research.ramses_campaign import CampaignBooks
from robinhood_research.ramses_strategy import USDG_ADDRESS
from robinhood_research.ramses import paper_position,paper_removal
from robinhood_tests.test_ramses_strategy import RamsesStrategyTests
from robinhood_tests.test_ramses_continuous_campaign import screen
fixture=RamsesStrategyTests()
for cut in (None,'before_rebalance','after_rebalance'):
 with tempfile.TemporaryDirectory() as td:
  root=Path(td);folder=root/'robinhood-ramses-extended-market.sqlite.campaign'
  decision=fixture._decision();capital=decision['freeze']['proposals'][0]['capital_employed']
  assert decision['qualified'],decision
  campaign=CampaignBooks(folder,screen([dict(token_y=USDG_ADDRESS,paper_capital_quote_raw=capital+1000)]))
  book=campaign.ledger(USDG_ADDRESS);book.reserve('original',pool='pool',decision=decision,at=1000);book.open('original',at=1000)
  path=root/'robinhood-ramses-continuation.json'
  state=dict(schema='ramses-position-continuation-v1',lifecycle_id='original',ledger_path=str(book.path),
   paper_capital=capital+1000,quote_asset=USDG_ADDRESS,pool='pool',entry_at=1000,entry_block=100,
   decision=decision,segments=[],rebalances=0,current_capital=capital,segment_start=100,position_phase='deployed',costs=fixture._costs())
  path.write_text(json.dumps(state));campaign.close()
  clock=[0];frontier={'number':101,'timestamp':4600};mode=['compound'];cuts=[];costs=fixture._costs()
  def current_state(decision):
   bins=decision['freeze']['proposals'][0]['bins'];center=(min(bins)+max(bins))//2
   active=center if mode[0]!='recenter' else center+(max(bins)-min(bins))
   return dict(active=active,inventory_value=capital,inventory_loss_quote=0)
  scan_count=[0]
  def scanner(*args,**kw):
   scan_count[0]+=1
   # One slow fresh range must be discarded and re-decided, never reminted.
   if mode[0]=='recenter' and scan_count[0]==2:clock[0]+=211
   saved=json.loads(path.read_text());d=saved['decision'];current=current_state(d)
   state=fixture._state();shift=current['active']-state['active'];state['active']+=shift
   state['variable'][2]+=shift;state['bins']={b+shift:v for b,v in state['bins'].items()}
   history=fixture._quiet_profitable_history()
   for row in history:row['args']['id']+=shift
   return dict(finalized_block=frontier['number'],finalized_timestamp=frontier['timestamp'],
    rows=[dict(pool='pool',decision=d,prestate=state,prehistory=history,quote_side='y',quote_token=USDG_ADDRESS,
     gas_costs=costs,features=d['features'])])
  def replay(rpc,pool,d,start,end):
   terminal=fixture._state()
   fees=[] if mode[0]=='hold' else [dict(bin_id=d['freeze']['proposals'][0]['bins'][0],supply_before=10**18,lp_fee=[1000000,1000000])]
   return dict(headers={str(start):dict(timestamp=hex(1000)),str(end):dict(timestamp=hex(frontier['timestamp']))}),dict(
    terminal_state=terminal,fee_events=fees,terminal_equality=True,events=0,transactions=0)
  def unwind(rpc,pool,d,replayed,block):
   removal=paper_removal(paper_position(d['freeze'],0),replayed['terminal_state'])
   amount=removal['amounts'][0]
   return dict(input_side='x',amount_in=amount,amount_in_left=0,amount_out=amount,slippage=0)
  class Rpc:
   def __init__(self,*a,**kw):pass
   def verify_chain(self):pass
   def call(self,*a,**kw):
    clock[0]+=100
    return dict(number=hex(frontier['number']),timestamp=hex(frontier['timestamp']))
  real_checkpoint=continuity_state.checkpoint
  def checkpoint(book,identity,**kw):
   if cut and not cuts and kw['action']=='rebalance':
    cuts.append(cut)
    def interrupted(identity,**command):
     if cut=='after_rebalance':book.checkpoint(identity,**command)
     raise SystemExit('injected_rebalance_interruption')
    kw['commit']=interrupted
   return real_checkpoint(book,identity,**kw)
  with patch.object(continuation,'time',SimpleNamespace(monotonic=lambda:clock[0],sleep=lambda n:clock.__setitem__(0,clock[0]+1),time=lambda:1000+clock[0])),patch.object(native,'BoundedMultiRpc',Rpc),patch.object(native,'_new_position_reader',side_effect=lambda endpoint,previous:previous),patch.object(native,'scan',side_effect=scanner),patch.object(native,'_position_state',side_effect=lambda rpc,pool,d,block:current_state(d)),patch.object(native,'_build_segment_replay',side_effect=replay),patch.object(native,'_unwind',side_effect=unwind),patch.object(continuity_state,'checkpoint',side_effect=checkpoint):
   for index,(elapsed,action) in enumerate(((3600,'compound'),(7200,'recenter'),(3*86400,'hold'),(604800,'hold'))):
    frontier.update(number=101+index,timestamp=1000+elapsed);mode[0]=action;scan_count[0]=0
    try:result=continuation._resume_ramses_native(root,slice_seconds=20,runtime_identity={'entry_authority':False})
    except SystemExit:
     assert cuts and index==0
     # Reopen after the actual write-ahead interruption; no market change or new
     # entry command is supplied to restore the already-authorized rebalance.
     mode[0]='hold'
     result=continuation._resume_ramses_native(root,slice_seconds=20,runtime_identity={'entry_authority':False})
    saved=json.loads(path.read_text())
    assert saved['entry_at']==1000 and saved['entry_block']==100
    proof=reconcile('ramses',root)
    if index<3:
     assert result['handoff_required'] and proof['durable_handoff'],(cut,index,result,proof)
    else:
     assert result['status']=='settled' and not result['handoff_required'],result
     assert result['pnl']['continuation_terminal_reason']=='maximum_holding_time',result
   campaign=CampaignBooks.recover(folder);book=campaign.books[USDG_ADDRESS]
   actions=[a for a, in book.db.execute('SELECT action FROM ramses_strategy_journal')]
   assert actions.count('reserve')==actions.count('open')==actions.count('settle')==1,actions
   assert actions.count('rebalance')==2,actions
   assert len(saved['recenter_deadline_misses'])==1
   assert saved['recenter_deadline_misses'][0]['elapsed_seconds']==211
   assert book.reconcile()['open_positions']==0 and book.reconcile()['committed']==0
   before=book.reconcile();campaign.close()
   again=continuation._resume_ramses_native(root,slice_seconds=20,runtime_identity={'entry_authority':False})
   assert again['terminal_replay_verified'] and again['accounting']==before
print('native repeat recenter, original seven-day hold, both rebalance crash cuts and single settlement pass')
'''

class RamsesLongHorizonTests(unittest.TestCase):
    def test_repeated_recenter_restart_and_seven_day_exit_use_native_controller(self):
        roots=os.environ.get('MM_TEST_LANE_WORKTREES')
        if not roots:self.skipTest('requires prepared native lanes')
        result=subprocess.run([sys.executable,'-c',SCRIPT],cwd=Path(roots)/'ramses',
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2])),
            capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
