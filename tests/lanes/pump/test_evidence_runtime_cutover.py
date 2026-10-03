"""Offline production-function gates. Stream contents are explicitly synthetic."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.lanes.pump.solana_evidence_plane import EvidenceWriter,EvidenceUnavailable
from meme_machine.lanes.pump.solana_evidence_service import FinalizedFence
from meme_machine.lanes.pump.solana_evidence_transport import Subscription
from meme_machine.lanes.pump.solana_evidence_runtime import RuntimeEvidence,LocalPumpHistory,SWAP_SCOPE
from meme_machine.lanes.pump.pump_evidence_execution import execution_addresses,prepare_reserved
from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
from meme_machine.lanes.pump.paper_accounting import PaperBook
from meme_machine.lanes.pump.provider import PumpAdapter
from meme_machine.lanes.pump.postgrad import PostGraduationAdapter,WSOL,PUMPSWAP_PROGRAM
from tests.lanes.pump import pump_acceleration_natural_prospective as lane
from tests.lanes.pump.test_postgrad import MINT,CREATOR,pumpswap_pool,pumpswap_snapshot,pumpswap_pool_account,complete_pump_snapshot,mint_account,fee_config,token_account
from meme_machine.lanes.pump import pump

class ProductionCutover(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.clock=[104]
        self.writer=EvidenceWriter(Path(self.temp.name)/'evidence',clock=lambda:self.clock[0])
        # Synthetic turnover must fund the real native gas/fees under the /40 cap.
        self.events={}
        for t in range(70,105):
            wallets=range(4) if t<94 else range(20)
            self.events[t]=[dict(index=i,slot=t,market_time=t,pool=pumpswap_pool(MINT),mint=MINT,
                wallet='wallet'+str(i),buy=True,amount=(100 if t<94 else 1000)*10000,
                quote_amount=(100 if t<94 else 1000)*10000) for i in wallets]
        self.fence=FinalizedFence(self.writer,endpoint_identity='a'*64,decoders={SWAP_SCOPE:lambda tx:self.events.get(tx['slot'],[])})
        logs=Subscription('service',SWAP_SCOPE,PUMPSWAP_PROGRAM,'logs',4)
        census=Subscription('service',SWAP_SCOPE,PUMPSWAP_PROGRAM,'census',4)
        for slot in range(70,105):
            self.fence.logs(logs,dict(method='logsNotification',params=dict(result=dict(context=dict(slot=slot),value=dict(signature='s'+str(slot),logs=[],err=None)))),104)
            self.fence.block(census,dict(params=dict(result=dict(value=dict(slot=slot,err=None,block=dict(parentSlot=slot-1,blockTime=slot,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),transactions=[dict(transaction=dict(signatures=['s'+str(slot)],message=dict(accountKeys=[PUMPSWAP_PROGRAM])),meta=dict(logMessages=[],err=None))]))))),104)
        self.fence.health('phase','ACTIVE');self.fence.health('heartbeat',104)
        self.plane=RuntimeEvidence(self.writer.path,owner='pump',clock=lambda:self.clock[0],command=self.fence.command)
        self.snapshot=pumpswap_snapshot(kind='real',now=100,slot=100)
        self.confirm=ConfirmationBook({},60)
        self.state=dict(creation=dict(creator=CREATOR),pregrad_wallets=set(),graduation_time=70,
            graduation_price=[40_000_000_000,500_000_000_000_000],pool=pumpswap_pool(MINT),mint=MINT,
            history=LocalPumpHistory(self.plane,pumpswap_pool(MINT),70))
        self.state['history'].bind_snapshot(self.snapshot)
        self.book=PaperBook(Path(self.temp.name)/'book',run_id='gate',lane=lane.STRATEGY_ID,policy_hash=lane.policy_hash(),initial=1_000_000_000)
        self.network=patch('socket.socket.connect',side_effect=AssertionError('network_forbidden'));self.network.start()
    def tearDown(self):self.network.stop();self.book.close();self.plane.close();self.writer.close();self.temp.cleanup()
    def decision(self):
        events=lane._refresh_pool_events(self.state,None,100,research=True)
        signal,confirmation=lane._volume_price_signal(self.state,self.snapshot,self.state['history'].decision_rows(100),lane.MODE_POSTGRAD,0,self.confirm)
        return signal,lane.qualify(signal)
    def test_actual_strategy_construction_zero_historical_rpc(self):
        signal,q=self.decision()
        expected=[e for t,rows in self.events.items() if 70<=t<=100 for e in rows]
        direct,_=lane._volume_price_signal(dict(self.state),self.snapshot,expected,lane.MODE_POSTGRAD,0,self.confirm)
        self.assertEqual(signal,direct);self.assertEqual(q,lane.qualify(direct));self.assertTrue(q.qualified,q.reasons)
        self.assertEqual(self.state['history'].status(100)['historical_provider_calls'],0)
    def test_gap_blocks_real_decision_without_fallback(self):
        self.writer.gap(SWAP_SCOPE,95,96)
        with self.assertRaises(EvidenceUnavailable):self.decision()
    def reserve(self):
        signal,q=self.decision();self.assertTrue(q.qualified,q.reasons)
        dummy=SimpleNamespace(pump=PumpAdapter(SimpleNamespace(call=lambda *a,**k:pump.MAINNET)),postgrad=PostGraduationAdapter(SimpleNamespace(call=lambda *a,**k:pump.MAINNET)))
        self.state['execution_context']=dict(scope=SWAP_SCOPE,mint=MINT,addresses=execution_addresses(self.snapshot,dummy))
        pending={};report=dict(qualifiers=[])
        with patch.object(lane,'ACCOUNTING',self.book),patch.object(lane,'FILL_PERSISTENCE_CONTEXT',dict(plane=self.plane,postgrad={MINT:self.state},confirmations=self.confirm)),patch.object(lane.time,'time',return_value=100):
            lane._reserve_position(report,pending,{},signal,q,self.snapshot,lane.MODE_POSTGRAD)
        return report,pending
    def test_reservation_recovers_without_duplicate_journal_events(self):
        report,pending=self.reserve();before=self.book.replay()
        recovered=lane.restore_runtime(self.book,self.plane,ConfirmationBook({},60))
        self.assertEqual(self.book.replay(),before);self.assertEqual(len(recovered[2]),1)
        self.assertEqual(next(iter(recovered[2].values()))['due'],102)
    def test_reserved_fill_preempts_saturated_background(self):
        from certification.governor import Governor
        import sqlite3,time
        report,pending=self.reserve();active={};calls=[]
        governor=Governor(Path(self.temp.name)/'governor')
        with sqlite3.connect(governor.path) as db:
            db.executemany('INSERT INTO queue VALUES(?,?,?,?,?,?)',[(str(i),'solana','repair',50,time.monotonic(),time.monotonic()+30) for i in range(256)])
        context=next(iter(pending.values()))['execution_context'];pool,pool_acc,base,quote=pumpswap_pool_account()
        curve=complete_pump_snapshot(now=103,retired=True)
        dummy=SimpleNamespace(pump=PumpAdapter(SimpleNamespace(call=lambda *a,**k:pump.MAINNET)),postgrad=PostGraduationAdapter(SimpleNamespace(call=lambda *a,**k:pump.MAINNET)))
        accounts={context['addresses'][0]:curve['accounts'][0],MINT:mint_account(),dummy.pump.fee_address:fee_config(),pool:pool_acc,
            base:token_account(MINT,pool,500_000_000_000_000),quote:token_account(WSOL,pool,50_000_000_000),dummy.postgrad.fee_address:fee_config()}
        def transport(req):
            calls.extend(r['method'] for r in req)
            governor.acquire('solana','pump',1,deadline_seconds=1,methods=calls)
            return [dict(id=1,result=dict(context=dict(slot=103),value=[accounts[a] for a in context['addresses']])),dict(id=2,result=dict(context=dict(slot=103),value=[])),dict(id=3,result=pump.MAINNET)]
        rpc=SimpleNamespace(calls=0,http_requests=0,_pace=lambda _:None,transport=transport)
        session=SimpleNamespace(plane=self.plane)
        session.prepare_reserved=lambda row:prepare_reserved(session,row,new_rpc=lambda **_:rpc)
        with patch.object(lane.time,'time',return_value=104):
            lane._fill_pending(report,pending,active,session,{MINT:self.state},104,confirmations=self.confirm)
        self.assertFalse(pending,report);self.assertEqual(len(active),1,report)
        self.assertEqual(calls,['getMultipleAccounts','getTokenLargestAccounts','getGenesisHash'])
        self.assertEqual(lane.ENTRY_FILL_TIMEOUT_SECONDS,20);self.assertEqual(lane.ENTRY_DELAY_SECONDS,2)
        before=self.book.replay();restored=lane.restore_runtime(self.book,self.plane,ConfirmationBook({},60))
        self.assertFalse(restored[2]);self.assertEqual(len(restored[3]),1);self.assertEqual(self.book.replay(),before)
        self.assertTrue(report['qualifiers'][0]['fill_persistence']['persistent'])

    def test_interrupted_refresh_claim_fails_closed_without_second_round(self):
        report,pending=self.reserve();row=next(iter(pending.values()))
        self.book.checkpoint_runtime(row['lifecycle'].lifecycle_id,'execution_refresh',{'attempted':True},claim=True)
        restored=lane.restore_runtime(self.book,self.plane,ConfirmationBook({},60))[2]
        session=SimpleNamespace(plane=self.plane)
        session.prepare_reserved=lambda row:prepare_reserved(session,row,new_rpc=lambda **_:self.fail('duplicate physical refresh'))
        with patch.object(lane.time,'time',return_value=104):
            lane._fill_pending(report,restored,{},session,{MINT:self.state},104,confirmations=self.confirm)
        self.assertEqual(len(restored),1);self.assertEqual(self.book.reconcile()['open_positions'],0)
        self.assertEqual(next(iter(restored.values()))['qualifier_row']['last_fill_limitation'],'execution_refresh_interrupted')
        with patch.object(lane.time,'time',return_value=120):
            lane._fill_pending(report,restored,{},session,{MINT:self.state},120,confirmations=self.confirm)
        self.assertFalse(restored);self.assertEqual(self.book.reconcile()['open_positions'],0)

    def test_actual_main_uses_local_history_for_a_recovered_candidate(self):
        import json
        from unittest.mock import MagicMock
        # A terminal journal entry retains authenticated discovery context. Startup
        # reconstructs it without allowing a second reservation for the same entry.
        self.book.close()
        report_path=Path(self.temp.name)/'native.json'
        self.book=PaperBook(report_path.with_suffix('.accounting.sqlite3'),run_id='gate',lane=lane.STRATEGY_ID,policy_hash=lane.policy_hash(),initial=lane.INITIAL_LAMPORTS)
        report,pending=self.reserve();next(iter(pending.values()))['lifecycle'].cancel('offline_fixture_terminal',101)
        before=self.book.replay()
        current_calls=[];graduation=complete_pump_snapshot(now=100,retired=True);graduation['kind']='real'
        def call(method,*a,**k):
            current_calls.append(method)
            if method!='getTokenLargestAccounts':raise AssertionError('historical provider call:'+method)
            return dict(context=dict(slot=100),value=[])
        session=SimpleNamespace(plane=self.plane,ensure=lambda *_:None,finish=lambda:None,history=[],
            rpc=SimpleNamespace(call=call,provider_telemetry=lambda:{}),
            postgrad=SimpleNamespace(graduation_snapshot=lambda *a,**k:graduation,pumpswap_snapshot=lambda *a,**k:self.snapshot),
            execution_interest=lambda *a,**k:self.state['execution_context'])
        runtime_plane=RuntimeEvidence(self.writer.path,owner='pump',clock=lambda:self.clock[0],command=self.fence.command)
        self.clock[0]=104
        def finish_iteration(_):self.clock[0]=10000
        with patch.object(lane,'REPORT',report_path),patch.object(lane,'RuntimeEvidence',return_value=runtime_plane), \
             patch.object(lane,'Sessions',return_value=session),patch.object(lane,'PumpLogStream') as stream, \
             patch.object(lane,'primary_rpc_url',return_value='https://solana-mainnet.g.alchemy.com/v2/offline-fixture'), \
             patch.object(lane.ConfirmationBook,'from_files',return_value=self.confirm), \
             patch.object(lane.LocalPumpTape,'events_since',return_value=([],0)),patch.object(lane.LocalPumpTape,'covered',return_value=False), \
             patch.object(lane.time,'time',side_effect=lambda:self.clock[0]),patch.object(lane.time,'sleep',side_effect=finish_iteration), \
             patch.dict(lane.os.environ,{'MM_SOLANA_EVIDENCE_BROKER_DB':str(Path(self.temp.name)/'broker')}),patch('builtins.print'):
            stream.return_value.run.side_effect=lambda stop,ready:ready.set()
            lane.main(discovery_seconds=600)
        result=json.loads(report_path.read_text())
        self.assertEqual(len(result['full_evidence_candidates']),1,result['attempts'])
        self.assertTrue(result['full_evidence_candidates'][0]['qualified'])
        self.assertEqual(current_calls,['getTokenLargestAccounts'])
        self.assertEqual(self.book.replay(),before)
