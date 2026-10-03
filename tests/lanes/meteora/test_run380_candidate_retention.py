"""Run 380 terminal candidates must not keep the program's retention floor pinned."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.lanes.meteora import dlmm
from meme_machine.lanes.meteora.solana_evidence_plane import EvidenceWriter, EvidenceUnavailable
from meme_machine.lanes.meteora.solana_evidence_service import FinalizedFence
from meme_machine.lanes.meteora.solana_evidence_transport import Subscription
from meme_machine.lanes.meteora.solana_evidence_runtime import RuntimeEvidence, METEORA_SCOPE
from tests.lanes.meteora import solana_dlmm_independent_v1 as lane

class CandidateRetentionTests(unittest.TestCase):
    def test_terminal_paths_release_only_candidate_and_preserve_position_interest(self):
        for terminal in ('compatibility', 'warmup', 'qualification', 'exception'):
            with self.subTest(terminal=terminal), tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                writer=EvidenceWriter(root/'db',clock=lambda:113)
                fence=FinalizedFence(writer,endpoint_identity='a'*64)
                sub=Subscription('service',METEORA_SCOPE,dlmm.PROGRAM,'transactions',4)
                for slot in range(99,114):
                    fence.block(sub,dict(method='blockNotification',params=dict(result=dict(value=dict(
                        slot=slot,err=None,block=dict(parentSlot=slot-1,blockTime=slot,
                        blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),transactions=[]))))),113)
                fence.health('phase','ACTIVE');fence.health('heartbeat',113)
                plane=RuntimeEvidence(writer.path,owner='meteora',clock=lambda:113,command=fence.command)
                plane.interest(METEORA_SCOPE,lower_slot=99,addresses=['open-pool'],
                    owner='meteora:position:unresolved',lifecycle='open',priority=0)
                candidate=dict(address='candidate-pool',signal_observed_at=113)
                def candidates(*args):yield candidate
                def compatible(adapter,*args):
                    if terminal=='compatibility':raise EvidenceUnavailable('unsupported_lineage_fixture')
                    if terminal=='exception':raise RuntimeError('injected_unexpected_failure')
                    return {},adapter
                with ExitStack() as stack:
                    for name,value in [('EVIDENCE_PLANE',plane),('OUT',root/'report.json'),('DLMM_BROKER_DB',root/'broker')]:
                        stack.enter_context(patch.object(lane,name,value))
                    stack.enter_context(patch.object(lane,'_prove_network_identity',return_value={'verified':True}))
                    stream=stack.enter_context(patch.object(lane,'ProgramAccountWakeStream'))
                    stream.return_value.run.side_effect=lambda stop,ready:ready.set()
                    stack.enter_context(patch.object(lane,'_campaign_candidates',side_effect=candidates))
                    stack.enter_context(patch.object(lane,'_new_adapter',return_value=object()))
                    stack.enter_context(patch.object(lane,'_fresh_supported_start',side_effect=compatible))
                    stack.enter_context(patch.object(lane,'_triggered_warmup',return_value=(
                        dict(aligned=terminal=='qualification',reason='verified_zero_flow_after_alignment'),None,{},None,None,candidate)))
                    stack.enter_context(patch.object(lane,'pre_entry_features',return_value={}))
                    stack.enter_context(patch.object(lane,'qualify',return_value=dict(passes=False,failed=['strategy_fixture_rejection'])))
                    stack.enter_context(patch('builtins.print'))
                    stack.enter_context(patch('socket.socket.connect',side_effect=AssertionError('network_forbidden')))
                    try:
                        if terminal=='exception':
                            with self.assertRaisesRegex(RuntimeError,'injected_unexpected_failure'):
                                lane.run_live(target=1,max_attempted=1,max_runtime_seconds=60)
                        else:
                            result=lane.run_live(target=1,max_attempted=1,max_runtime_seconds=60)
                            self.assertTrue(result['accounting']['reconciled'])
                            self.assertEqual(result['accounting']['unsettled'],0)
                        self.assertIsNone(lane.PROGRESS_HOOK)
                        active=writer.db.execute('SELECT owner FROM interests WHERE active=1').fetchall()
                        self.assertEqual(active,[('meteora:position:unresolved',)])
                        self.assertEqual(plane.counts.get('meteora.candidate_interests_released'),1)
                        with self.assertRaisesRegex(EvidenceUnavailable,'unresolved_lifecycle_interest'):
                            plane.command(op='release',owner='meteora:position:unresolved',scope=METEORA_SCOPE,resolved=False)
                        writer.retain(200,archive_first=False)
                        floor=writer.db.execute('SELECT value FROM meta WHERE key=?',('retention_floor:'+METEORA_SCOPE,)).fetchone()
                        self.assertEqual(int(floor[0]),99)
                        plane.command(op='release',owner='meteora:position:unresolved',scope=METEORA_SCOPE,resolved=True)
                        writer.retain(200,archive_first=False)
                        self.assertGreater(int(writer.db.execute('SELECT value FROM meta WHERE key=?',('retention_floor:'+METEORA_SCOPE,)).fetchone()[0]),112)
                    finally:
                        plane.close();writer.close()

if __name__=='__main__':unittest.main()
