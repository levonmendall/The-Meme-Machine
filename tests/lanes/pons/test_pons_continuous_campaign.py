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
from meme_machine.lanes.pons import pons_selective_cohort as cohort
from meme_machine.lanes.pons.evidence_queue import DeadlineEvidenceQueue


class ContinuousCampaignTests(unittest.TestCase):
    def test_terminal_writeoff_keeps_its_accounting_kind(self):
        life=dict(index=0,status='settled',settlement_kind='liquidity_writeoff',
            final_position=dict(status='settled',entry_tokens=2,
                reason='liquidity_writeoff:impossible_full_position_exit',realized=-100),
            reconciliation=dict(open_exposure=0),
            exit=dict(quote=dict(amount_out=0,executable=False,proof={'verified':True})))
        result=dict(rows=[],qualifiers=[],lifecycles=[life],discovery_sessions=[],
                    sequencer_recoveries=[],summary=dict(enrolled=1))
        with tempfile.TemporaryDirectory() as td,patch.object(cohort,'ROOT',Path(td)),patch.object(cohort,'REPORT',Path(td)/'report.json'):
            compact=cohort.persist_terminal(result)
            self.assertEqual(compact['lifecycles'][0]['settlement_kind'],'liquidity_writeoff')
            self.assertEqual(compact['lifecycles'][0]['final_position']['realized'],-100)
            archived=json.loads(gzip.decompress(Path(compact['observation_archive']['path']).read_bytes()))
            self.assertEqual(archived,result)

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
        self._campaign_probe()

    def _campaign_probe(self,blocked=False,startup=False,pressure=False):
        from meme_machine.lanes.pons import BoundaryError
        future=Future();clock_reads=[0]
        class State:
            @property
            def latest_header_timestamp(self):
                clock_reads[0]+=1
                return 0 if clock_reads[0]==1 else 65
        feed=SimpleNamespace(state=State(),connect=lambda:None,wait_for_after=lambda *a,**kw:200 if startup else 1,
            status=lambda:{},close=lambda:None)
        rpc=SimpleNamespace(telemetry=lambda:{})
        from tests.lanes.pons.test_pons_finalization import block_header
        from meme_machine.lanes.pons.pons_selective_acquisition import ImmutableEvidenceCache
        canonical_calls=[]
        def canonical_batch(calls,scope):
            canonical_calls.append(list(calls));out=[]
            for method,params in calls:
                if method=='eth_getBlockByNumber':
                    if pressure:raise BoundaryError('provider_http_429')
                    out.append(block_header(200 if params[0]=='latest' else int(params[0],16)))
                elif method=='eth_getLogs':
                    q=params[0]
                    out.append([event] if startup and int(q['fromBlock'],16)<=195<=int(q['toBlock'],16) else [])
                else:raise AssertionError(method)
            return out
        def evidence(endpoint,**kwargs):
            return SimpleNamespace(telemetry=lambda:{},cache=ImmutableEvidenceCache(),pin=None,block_reads={},factory_hints={},
                batch=canonical_batch,call=lambda m,p,scope:canonical_batch([(m,p)],scope)[0])
        def submit(function,*a,**kw):
            if function in (cohort._poll,cohort._prime_current_step) or function.__name__=='_discover_observations':
                ready=Future()
                try:ready.set_result(function(*a,**kw))
                except Exception as exc:ready.set_exception(exc)
                return ready
            if function is cohort.evaluate_candidate:
                ready=Future();ready.set_result(evaluation);return ready
            return future
        pool=SimpleNamespace(submit=submit,shutdown=lambda **kw:None)
        event=dict(transactionHash='transaction',logIndex='0x1',blockNumber='0x1',address='curve',transactionIndex='0x0',blockHash='block',
            topics=[cohort.topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)')])
        polls=[0]
        def poll(*args,**kwargs):
            polls[0]+=1
            if startup:
                if polls[0]<30:return rpc,200,[]
                future.set_result(dict(status='settled',final_position=dict(status='settled',entry_tokens=2),reconciliation=dict(open_exposure=0)))
                raise BoundaryError('injected_discovery_failure')
            if polls[0]==1:return rpc,2,[event]
            if polls[0]==2:return rpc,2,[]
            if blocked and polls[0]==3:return rpc,3,[dict(event,blockNumber='0x2',blockHash='block2',transactionHash='transaction2')]
            if blocked and polls[0]==4:return rpc,3,[]
            future.set_result(dict(status='settled',final_position=dict(status='settled',entry_tokens=2),
                reconciliation=dict(open_exposure=0)))
            raise BoundaryError('injected_discovery_failure')
        if startup:event.update(blockNumber=hex(195),blockHash=block_header(195)['hash'])
        evaluation=dict(vector=dict(current_threshold_pass=True),token='token',curve='curve',source_transaction='transaction')
        with tempfile.TemporaryDirectory() as td,ExitStack() as stack:
            root=Path(td)
            for name in ('ROOT','SKILL_DB','PROGRESS','ROWS_LOG','QUALIFIERS_LOG','PROVIDER_LOG','RECOVERY_LOG','REPORT'):
                stack.enter_context(patch.object(cohort,name,root if name=='ROOT' else root/(name+'.json')))
            for name,value in dict(TAPE_WARM_SECONDS=0,SequencerBlockClock=lambda:feed,_discovery=lambda endpoint:rpc,
                WalletSkillBook=lambda path:SimpleNamespace(close=lambda:None),
                SelectiveEvidenceContext=evidence,
                ThreadPoolExecutor=lambda **kw:pool,_poll=poll,evaluate_candidate=lambda *a,**kw:evaluation,
                public_evaluation=lambda value:dict(value),_attach_wallet_overlay=lambda *a:{'converged':False}).items():
                stack.enter_context(patch.object(cohort,name,value))
            stack.enter_context(patch('meme_machine.lanes.pons.pons_selective_acquisition.public_evaluation',side_effect=lambda value:dict(value)))
            stack.enter_context(patch.object(cohort.time,'monotonic',return_value=0))
            stack.enter_context(patch.object(cohort.time,'time',return_value=100))
            result=cohort.run('unused',campaign=True)
            self.assertEqual(result['boundary'],'injected_discovery_failure')
            self.assertEqual(len(result['lifecycles']),0 if startup and pressure else 1)
            if not (startup and pressure):self.assertEqual(result['lifecycles'][0]['final_position']['entry_tokens'],2)
            if not (startup and pressure):self.assertEqual(len((root/'completed-lifecycles.jsonl').read_text().splitlines()),1)
            self.assertTrue(result['cohort_accounting']['conservation'])
            self.assertEqual(result['cohort_accounting']['genesis'],cohort.STRATEGY_CAPITAL_QUOTE)
            if blocked:
                from meme_machine.runtime.robinhood.plane import Plane
                from meme_machine.lanes.pons.pons_attempts import Attempts
                plane=Plane(result['candidate_plane_path'])
                try:
                    rows=Attempts(plane).rows()
                    qualification=[r for r in rows if r['phase']=='qualification']
                    funding=[r for r in rows if r['phase']=='funding']
                    self.assertEqual([r['category'] for r in qualification],['QUALIFIED','QUALIFIED'])
                    self.assertEqual([(r['category'],r['reason']) for r in funding],
                        [('OTHER_EXPLICIT_REASON','same_curve_lifecycle_active')])
                    self.assertTrue(result['rows'][-1]['vector']['current_threshold_pass'])
                    self.assertEqual(result['rows'][-1]['authorization_rejection'],'same_curve_lifecycle_active')
                    disposition=funding[0]
                    self.assertFalse(disposition['execution']['entry_authorized'])
                    self.assertEqual(disposition['execution']['blocking_lifecycle'],
                        dict(curve='curve',index=0,trial_path=str(root/'trial-000.sqlite')))
                    plane.close();plane=Plane(result['candidate_plane_path'])
                    attempts=Attempts(plane)
                    attempts.record(disposition['candidate'],disposition['generation'],disposition['phase'],
                        disposition['category'],at=disposition['at'],reason=disposition['reason'],
                        decision=disposition['decision'],execution=disposition['execution'])
                    self.assertEqual(attempts.rows(),rows)
                    attempts.record(disposition['candidate'],disposition['generation']+1,'funding',
                        'QUALIFIED_BUT_CAPITAL_UNAVAILABLE',at=100.,reason='pons_capital_exhausted')
                    self.assertEqual([r['category'] for r in attempts.rows() if r['phase']=='funding'],
                        ['OTHER_EXPLICIT_REASON','QUALIFIED_BUT_CAPITAL_UNAVAILABLE'])
                    self.assertEqual(len(result['qualifiers']),1)
                finally:plane.close()
            return result,canonical_calls,polls[0]

    def test_startup_prehead_buy_is_nominated_without_a_new_trade(self):
        self._campaign_probe(startup=True)

    def test_execution_block_is_durable_after_qualification(self):
        self._campaign_probe(blocked=True)

    def test_startup_provider_failure_keeps_live_and_native_work_running(self):
        result,calls,polls=self._campaign_probe(pressure=True)
        self.assertFalse(result['current_startup_coverage']['complete'])
        self.assertEqual(result['current_startup_coverage']['coverage_gap'],'provider_http_429')
        self.assertEqual(len(result['lifecycles']),1)
        self.assertGreaterEqual(polls,3)
        self.assertEqual(len(calls),1)

    def test_terminal_boundary_retains_original_ledger_identity(self):
        life=dict(index=1,status='boundary',boundary='provider_shared_admission_deadline',
                  lifecycle_id='original-ledger',qualification_vector={'original':True})
        result=dict(rows=[],qualifiers=[],lifecycles=[life],discovery_sessions=[],
                    sequencer_recoveries=[],summary={})
        with tempfile.TemporaryDirectory() as td,patch.object(cohort,'ROOT',Path(td)),patch.object(cohort,'REPORT',Path(td)/'report.json'):
            compact=cohort.persist_terminal(result)
            self.assertEqual(compact['lifecycles'][0]['lifecycle_id'],'original-ledger')
            self.assertEqual(compact['lifecycles'][0]['status'],'boundary')
            archived=json.loads(gzip.decompress(Path(compact['observation_archive']['path']).read_bytes()))
            self.assertEqual(archived,result)
