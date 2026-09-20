from contextlib import ExitStack
from concurrent.futures import Future
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from robinhood_research import pons_selective_cohort as cohort
from robinhood_research.evidence_queue import DeadlineEvidenceQueue


class ContinuousCampaignTests(unittest.TestCase):
    def test_large_result_is_preserved_exactly_under_bounded_terminal_view(self):
        result=dict(rows=[dict(evidence='x'*13_000_000)],qualifiers=[],lifecycles=[dict(
            index=0,final_position=dict(status='settled',entry_tokens=2),reconciliation=dict(open_exposure=0),
            full_evidence='proof')],discovery_sessions=[],sequencer_recoveries=[],summary=dict(enrolled=1))
        with tempfile.TemporaryDirectory() as td,patch.object(cohort,'ROOT',Path(td)),patch.object(cohort,'REPORT',Path(td)/'report.json'):
            compact=cohort.persist_terminal(result)
            archive=Path(compact['observation_archive']['path'])
            self.assertEqual(json.loads(gzip.decompress(archive.read_bytes())),result)
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),compact['observation_archive']['sha256'])
            self.assertLess((Path(td)/'report.json').stat().st_size,2000)
            self.assertEqual(compact['lifecycles'][0]['final_position']['entry_tokens'],2)

    def test_provider_checkpoint_is_bounded_and_keeps_archive_identity(self):
        result=dict(started_at=0,rows=[],qualifiers=[],lifecycles=[],discovery_sessions=[dict(id=i) for i in range(1000)],sequencer_recoveries=[])
        with tempfile.TemporaryDirectory() as td,patch.object(cohort,'ROOT',Path(td)),patch.object(cohort,'PROGRESS',Path(td)/'progress.json'):
            snapshot=cohort._checkpoint(result,cursor=1,feed=SimpleNamespace(status=lambda:{}),rpc=SimpleNamespace(telemetry=lambda:{}),phase='discovery')
            self.assertEqual(len(snapshot['discovery_sessions']),16)
            self.assertEqual(snapshot['discovery_session_count'],1000)
            self.assertEqual(len(result['discovery_sessions']),1000)

    def test_queue_terminal_preserves_original_deadline_for_expiry_and_eviction(self):
        events=[];queue=DeadlineEvidenceQueue(limit=1,on_terminal=lambda row,reason:events.append((dict(row),reason)))
        def event(n):return dict(transactionHash=str(n),logIndex='0x1',blockNumber='0x1')
        queue.enqueue(event(1),now=10)
        queue.enqueue(event(2),now=9) # Earliest authenticated observation keeps priority.
        self.assertEqual(events[0][1],'capacity_evicted')
        self.assertEqual(events[0][0]['deadline'],15)
        self.assertIsNone(queue.pop(now=14))
        self.assertEqual(events[1][1],'expired_before_evidence')
        self.assertEqual(events[1][0]['queued_at'],9)
        self.assertEqual(events[1][0]['deadline'],14)
        self.assertEqual(queue.telemetry()['max_depth'],1)

    def test_discovery_failure_drains_admitted_future_and_initializes_one_book(self):
        from robinhood_research import BoundaryError
        future=Future();clock_reads=[0]
        class State:
            @property
            def latest_header_timestamp(self):
                clock_reads[0]+=1
                return 0 if clock_reads[0]==1 else 65
        feed=SimpleNamespace(state=State(),connect=lambda:None,wait_for_after=lambda *a,**kw:1,
            status=lambda:{},close=lambda:None)
        rpc=SimpleNamespace(telemetry=lambda:{})
        pool=SimpleNamespace(submit=lambda *a,**kw:future,shutdown=lambda **kw:None)
        event=dict(transactionHash='transaction',logIndex='0x1',blockNumber='0x1',address='curve',
            topics=[cohort.topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)')])
        polls=[0]
        def poll(*args,**kwargs):
            polls[0]+=1
            if polls[0]==1:return rpc,2,[event]
            future.set_result(dict(status='settled',final_position=dict(status='settled',entry_tokens=2),
                reconciliation=dict(open_exposure=0)))
            raise BoundaryError('injected_discovery_failure')
        evaluation=dict(vector=dict(current_threshold_pass=True),token='token',curve='curve',source_transaction='transaction')
        with tempfile.TemporaryDirectory() as td,ExitStack() as stack:
            root=Path(td)
            for name in ('ROOT','SKILL_DB','PROGRESS','ROWS_LOG','QUALIFIERS_LOG','PROVIDER_LOG','RECOVERY_LOG','REPORT'):
                stack.enter_context(patch.object(cohort,name,root if name=='ROOT' else root/(name+'.json')))
            for name,value in dict(TAPE_WARM_SECONDS=0,SequencerBlockClock=lambda:feed,_discovery=lambda endpoint:rpc,
                WalletSkillBook=lambda path:SimpleNamespace(close=lambda:None),
                SelectiveEvidenceContext=lambda endpoint:SimpleNamespace(telemetry=lambda:{}),
                ThreadPoolExecutor=lambda **kw:pool,_poll=poll,evaluate_candidate=lambda *a,**kw:evaluation,
                public_evaluation=lambda value:dict(value),_attach_wallet_overlay=lambda *a:{'converged':False}).items():
                stack.enter_context(patch.object(cohort,name,value))
            stack.enter_context(patch.object(cohort.time,'monotonic',return_value=0))
            stack.enter_context(patch.object(cohort.time,'time',return_value=100))
            result=cohort.run('unused',campaign=True)
            self.assertEqual(result['boundary'],'injected_discovery_failure')
            self.assertEqual(len(result['lifecycles']),1)
            self.assertEqual(result['lifecycles'][0]['final_position']['entry_tokens'],2)
            self.assertEqual(len((root/'completed-lifecycles.jsonl').read_text().splitlines()),1)
            self.assertTrue(result['cohort_accounting']['conservation'])
            self.assertEqual(result['cohort_accounting']['genesis'],cohort.STRATEGY_CAPITAL_QUOTE)
