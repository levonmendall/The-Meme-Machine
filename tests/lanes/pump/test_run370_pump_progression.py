"""New discovery through the unmocked production LocalPumpTape and main loop."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.lanes.pump import pump
from meme_machine.lanes.pump.solana_evidence_plane import EvidenceWriter
from meme_machine.lanes.pump.solana_evidence_service import FinalizedFence
from meme_machine.lanes.pump.solana_evidence_runtime import RuntimeEvidence,PUMP_SCOPE,SWAP_SCOPE
from meme_machine.lanes.pump.solana_evidence_transport import Subscription
from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
from meme_machine.lanes.pump import runner as lane
from tests.lanes.pump.test_postgrad import MINT,CREATOR


class Run370PumpProgression(unittest.TestCase):
    def test_new_discovery_reaches_real_local_screen_without_historical_rpc(self):
        with tempfile.TemporaryDirectory() as tmp:
            now=[104];path=Path(tmp)/'evidence';w=EvidenceWriter(path,clock=lambda:now[0])
            creation=dict(index=0,slot=10,market_time=10,event_type='create',mint=MINT,creator=CREATOR,
                initial_real_token_reserves=1000000,bonding_curve='curve',virtual_quote_reserves=30000000000,virtual_token_reserves=1000000)
            def events(tx):
                slot=tx['slot']
                if slot==10:return [creation]
                if slot not in (40,70,85,100):return []
                return [dict(index=1,slot=slot,market_time=slot,event_type='trade',mint=MINT,wallet='wallet',
                    buy=True,amount=100,quote_amount=100,real_token_reserves=300000 if slot==100 else 700000,
                    virtual_quote_reserves=30000000000,virtual_token_reserves=1000000,real_quote_reserves=10000000000)]
            f=FinalizedFence(w,endpoint_identity='a'*64,decoders={PUMP_SCOPE:events,SWAP_SCOPE:lambda _:[]})
            for slot in range(10,105):
                for scope,program in ((PUMP_SCOPE,pump.PROGRAM),(SWAP_SCOPE,'swap-program')):
                    tx=dict(transaction=dict(signatures=[scope+str(slot)],message=dict(accountKeys=[program])),meta=dict(err=None,logMessages=[]))
                    msg=dict(params=dict(result=dict(value=dict(slot=slot,err=None,block=dict(parentSlot=slot-1,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),blockTime=slot,transactions=[tx])))))
                    f.block(Subscription('service',scope,program,'census',2),msg,104,include_logs=True)
            f.health('phase','ACTIVE');f.health('heartbeat',104)
            plane=RuntimeEvidence(path,owner='pump',clock=lambda:now[0],command=f.command)
            reports=[];screens=[];original=lane._late_stream_signal
            def signal(*args):
                result=original(*args);screens.append(result[0]);return result
            session=SimpleNamespace(finish=lambda:None,history=[],
                rpc=SimpleNamespace(provider_telemetry=lambda:{},http_requests=0),
                pump=SimpleNamespace(local_finalized_time_reuses=0),
                postgrad=SimpleNamespace(held_pumpswap_probe_reuses=0,held_finalized_time_reuses=0),
                holder_probe_status=lambda:{})
            def end_iteration(_):now[0]=10000
            report_path=Path(tmp)/'native.json'
            try:
                with patch.object(lane,'REPORT',report_path),patch.object(lane,'RuntimeEvidence',return_value=plane), \
                     patch.object(lane,'Sessions',return_value=session),patch.object(lane,'PumpLogStream') as stream, \
                     patch.object(lane,'primary_rpc_url',return_value='https://solana-mainnet.g.alchemy.com/v2/offline-fixture'), \
                     patch.object(lane.ConfirmationBook,'from_files',return_value=ConfirmationBook({},60)), \
                     patch.object(lane,'_late_stream_signal',side_effect=signal), \
                     patch.object(lane.time,'time',side_effect=lambda:now[0]),patch.object(lane.time,'sleep',side_effect=end_iteration), \
                     patch.dict(lane.os.environ,{'MM_SOLANA_EVIDENCE_BROKER_DB':str(Path(tmp)/'broker')}), \
                     patch('socket.socket.connect',side_effect=AssertionError('network_forbidden')),patch('builtins.print'):
                    stream.return_value.run.side_effect=lambda stop,ready:ready.set()
                    lane.main(discovery_seconds=600)
                report=json.loads(report_path.read_text())
                self.assertEqual(report['created_mints_observed'],1)
                self.assertEqual(len(screens),1,report.get('prospect_screen_incomplete_counts'))
                self.assertEqual(screens[0].observed_at,100)
                self.assertTrue(report['prospect_screen_rejection_counts'])
                self.assertGreater(plane.counts.get('pump.complete_local_reads',0),0)
                self.assertEqual(dict(w.db.execute('SELECT * FROM counters'))['pump.foreground_historical_rpc_calls'],0)
            finally:w.close()
