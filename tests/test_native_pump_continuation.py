"""Current Pump restores and exits through its actual monitor, without entry code."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from tests.native_inline import run_native

SCRIPT=r'''
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tests.lanes.pump.test_evidence_runtime_cutover import ProductionCutover
from meme_machine.lanes.pump import runner as native
from tests.lanes.pump.test_postgrad import MINT,pumpswap_snapshot,complete_pump_snapshot
from meme_machine.lanes.pump.paper_accounting import PaperBook
from meme_machine.lanes.pump.solana_evidence_transport import Subscription
from meme_machine.lanes.pump.solana_evidence_runtime import SWAP_SCOPE
from meme_machine.lanes.pump.postgrad import PUMPSWAP_PROGRAM
from meme_machine.runtime.terminal_reconciliation import pump_current_handoff
from meme_machine.runtime.position_continuation import PumpCurrentContinuation

fixture=ProductionCutover();fixture.setUp()
import os
allocation_env=patch.dict(os.environ,dict(MM_DIRECTIONAL_SLEEVE_DB=str(Path(fixture.temp.name)/'sleeve.sqlite'),
    MM_DIRECTIONAL_COHORT_ID='pump-current-continuation',MM_DIRECTIONAL_COMPOSITE_REQUIRED='1'))
allocation_env.start()
fixture_capital=patch.multiple(native,INITIAL_LAMPORTS=1_000_000_000,ENTRY_BUDGET=50_000_000)
fixture_capital.start()
manager=None
try:
    # Existing actual reserve/revalidation/fill fixture, including zero historical RPC.
    from meme_machine.lanes.pump.pump_evidence_execution import CachedExecutionRPC
    original_init=CachedExecutionRPC.__init__
    def virtual_execution(rpc,*args,**kwargs):
        original_init(rpc,*args,**kwargs,clock=lambda:fixture.clock[0])
    with patch.object(CachedExecutionRPC,'__init__',virtual_execution):
        fixture.test_reserved_fill_preempts_saturated_background()
    original=fixture.book.replay()
    handoff=pump_current_handoff(fixture.book)
    assert len(handoff['positions'])==1 and handoff['entry_authority'] is False
    assert fixture.book.replay()==original
    missing=Path(fixture.temp.name)/'missing-sleeve.sqlite'
    with patch.dict(os.environ,MM_DIRECTIONAL_SLEEVE_DB=str(missing)):
        try:native.restore_runtime(fixture.book,fixture.plane,fixture.confirm)
        except ValueError as exc:assert str(exc)=='pump_recovery_sleeve_missing',str(exc)
        else:raise AssertionError('restoration recreated missing allocation authority')
    assert not missing.exists()
    fixture.book.close()
    root=Path(fixture.temp.name)
    path=root/'pump-acceleration-natural-prospective.accounting.sqlite3'
    (root/'book').rename(path)
    fixture.book=PaperBook(path,run_id='gate',lane=native.STRATEGY_ID,
        policy_hash=native.policy_hash(),initial=1_000_000_000)
    # Advance the real finalized fence by one block, preserving the local history.
    slot=105
    logs=Subscription('service',SWAP_SCOPE,PUMPSWAP_PROGRAM,'logs',4)
    census=Subscription('service',SWAP_SCOPE,PUMPSWAP_PROGRAM,'census',4)
    fixture.fence.logs(logs,dict(method='logsNotification',params=dict(result=dict(context=dict(slot=slot),
        value=dict(signature='s'+str(slot),logs=[],err=None)))),105)
    fixture.fence.block(census,dict(params=dict(result=dict(value=dict(slot=slot,err=None,
        block=dict(parentSlot=slot-1,blockTime=slot,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),
            transactions=[dict(transaction=dict(signatures=['s'+str(slot)],message=dict(accountKeys=[PUMPSWAP_PROGRAM])),
                               meta=dict(logMessages=[],err=None))]))))),105)
    fixture.clock[0]=105;fixture.fence.health('heartbeat',105)
    fresh=pumpswap_snapshot(kind='real',now=104,slot=104,quote=75_000_000_000)
    fresh['available_time']=105
    graduation=complete_pump_snapshot(now=104,retired=True);graduation['kind']='real';graduation['available_time']=105
    reads=[];holder_probes=[]
    def call(method,*a,**kw):
        reads.append(method)
        assert method=='getTokenLargestAccounts',method
        return dict(context=dict(slot=fresh['slot']),value=[])
    sessions=SimpleNamespace(ensure=lambda *a:None,finish=lambda:None,
        record_holder_probe=lambda mint,snapshot,value:holder_probes.append((mint,snapshot['slot'],value)),
        rpc=SimpleNamespace(call=call),postgrad=SimpleNamespace(
            graduation_snapshot=lambda *a,**kw:graduation,pumpswap_snapshot=lambda *a,**kw:fresh))
    with patch('meme_machine.lanes.pump.solana_evidence_runtime.RuntimeEvidence',return_value=fixture.plane) as planes,\
         patch.object(native,'Sessions',return_value=sessions),\
         patch.object(native.time,'time',side_effect=lambda:fixture.clock[0]):
        manager=PumpCurrentContinuation(root,fixture.confirm)
        assert len(manager.active)==1
        first=manager.step()
        assert first['open_positions']==1,first
        held=next(iter(manager.active.values()))['lifecycle']
        assert held.position.partial_harvest_taken
        original_opened=held.position.opened_at
        plane_type=type(fixture.plane)
        manager.close();manager=None
        fixture.plane=plane_type(fixture.writer.path,owner='pump',clock=lambda:fixture.clock[0],command=fixture.fence.command)
        planes.return_value=fixture.plane
        # Reopen after the actual native partial; the next snapshot preserves the
        # existing finalized evidence interval and uses a fresh acquisition clock.
        slot=106
        fixture.fence.logs(logs,dict(method='logsNotification',params=dict(result=dict(context=dict(slot=slot),
            value=dict(signature='s'+str(slot),logs=[],err=None)))),106)
        fixture.fence.block(census,dict(params=dict(result=dict(value=dict(slot=slot,err=None,
            block=dict(parentSlot=slot-1,blockTime=slot,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),
                transactions=[dict(transaction=dict(signatures=['s'+str(slot)],message=dict(accountKeys=[PUMPSWAP_PROGRAM])),
                                   meta=dict(logMessages=[],err=None))]))))),106)
        fixture.clock[0]=106;fixture.fence.health('heartbeat',106)
        fresh=pumpswap_snapshot(kind='real',now=105,slot=105,quote=25_000_000_000)
        fresh['available_time']=106
        graduation=complete_pump_snapshot(now=105,retired=True);graduation.update(kind='real',available_time=106)
        manager=PumpCurrentContinuation(root,fixture.confirm)
        restored=next(iter(manager.active.values()))['lifecycle']
        assert restored.position.opened_at==original_opened
        assert restored.position.partial_harvest_taken
        state=manager.step()
        assert state['open_positions']==0,state
        assert state['new_entries']==0
        assert state['accounting']['settled']==1,state
        again=manager.step()
        assert again['accounting']==state['accounting']
    rows=[__import__('json').loads(raw) for raw, in fixture.book.db.execute('SELECT body FROM journal ORDER BY seq')]
    assert sum(r['action']=='filled' for r in rows)==1
    assert sum(r['action']=='settled' for r in rows)==1
    assert sum(r['action']=='partial_harvest' for r in rows)==1
    assert reads and set(reads)=={'getTokenLargestAccounts'}
    assert len(holder_probes)==2 and [row[1] for row in holder_probes]==[104,105],holder_probes
    from meme_machine.runtime.directional_sleeve import open_sleeve
    sleeve=open_sleeve('pump',1_000_000_000)
    try:
        allocation=sleeve.reconcile()
        assert allocation['reserved']==0,allocation
        assert allocation['realized']==state['accounting']['realized'],allocation
    finally:sleeve.close()
    print('native Pump reconstruction, finalized local reads, exact stop and single settlement pass')
finally:
    if manager is not None:manager.close()
    fixture.tearDown();allocation_env.stop();fixture_capital.stop()
'''

class PumpCurrentContinuationTests(unittest.TestCase):
    def test_native_recovered_position_uses_existing_monitor(self):
        result=run_native(SCRIPT,timeout=45)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
