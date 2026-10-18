"""Actual native Current submission/commit returns, synthetic private fixtures.

No live provider, financial book, normal boot acquisition or throughput claim.
The original child fixture simulates root/unit/clock premises; PID/IPC, native
candidate/Attempts/checkpoint/consumption SQLite and funding denial are real.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch

from meme_machine.operational import normal_pons_boot as pons
from tests import test_normal_pons_boot as owner_fixture
from tests.test_pons_native_work import native_fixture


@contextmanager
def current_fixture(cap,*,queued=False):
    from meme_machine.runtime.robinhood.pons import Broker
    from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
    from tests.lanes.pons.test_pons_finalization import observation
    from tests.lanes.pons.test_pons_selective_continuation import vector,state
    with native_fixture(cap) as f:
        f.runtime.plane.economic_cohorts=f.meter
        f.queue=Broker(f.runtime.plane.path,POLICY_HASH,clock=lambda:f.at,
            source='https://robinhood-mainnet.g.alchemy.com/v2/SYNTHETIC_NATIVE_WORK',
            plane=f.runtime.plane)
        f.work=f.meter.current_work
        for n in (1,2,3):assert f.queue.enqueue(observation(n),now=f.at)
        f.scheduled=f.queue.pop(now=f.at)
        assert f.scheduled is not None and len(f.queue.rows)==3
        f.value=dict(vector=vector(strategy_capital_quote=f.resources.basis('pons',500)['realized_equity']),
            token='native-current-token',curve=f.scheduled['event']['address'],
            evaluation_completed_at=f.at,candidate=dict(state=state()))
        assert f.value['vector']['current_threshold_pass']
        with ThreadPoolExecutor(max_workers=1) as pool:
            release=threading.Event();entered=threading.Event()
            if queued:
                def blocked():entered.set();assert release.wait(2)
                blocker=pool.submit(blocked);assert entered.wait(2)
            f.future=pool.submit(lambda:f.value)
            f.request=f.work.issued(f.queue,f.scheduled,f.future)
            assert f.request is not None
            try:
                if not queued:assert f.future.result(2) is f.value
                yield f
            finally:
                release.set()
                if queued:blocker.result(2)
        f.queue.close()


def decide(f,*,request=None):
    from meme_machine.lanes.pons import pons_selective_cohort as cohort
    request=f.request if request is None else request
    key=f.scheduled['key'];generation=f.scheduled['work']['generation']
    assert cohort._current_decision(f.queue,request,key,generation,'qualified')
    return cohort._record_qualification(f.runtime.attempts,key,generation,f.value,'QUALIFIED',
        at=f.at,explanation={},native_request=request)


def checkpoint(f,*,changed=False):
    from meme_machine.runtime.robinhood.pons import save_cohort_checkpoint
    result=dict(candidate_plane_path=f.runtime.plane.path,rows=[dict(
        candidate_identity=f.scheduled['key'],candidate_generation=f.scheduled['work']['generation'],
        vector=dict(f.value['vector'],current_threshold_pass=False) if changed else f.value['vector'])],qualifiers=[],lifecycles=[])
    save_cohort_checkpoint(result,100,'candidate_consumed',plane=f.runtime.plane)
    return result


def run_native_case(cap,mode):
    with current_fixture(cap,queued=mode=='cancel_queued') as f:
        if mode=='native_current':
            assert f.queue.finish(f.scheduled,f.value,.01)
            decide(f)
            from meme_machine.lanes.pons import pons_selective_cohort as cohort
            assert not cohort._allocation_allowed(f.queue,f.scheduled,f.value,f.runtime.attempts,
                native_resources=f.resources)
            checkpoint(f);assert f.queue.acknowledge(f.scheduled)
            state=f.work.snapshot()
            assert all(value['completed_cohorts']==1 and value['pending_units']==0
                for value in state['stages'].values())
            assert state['pending_inventory']['count']==3
            assert f.runtime.plane.db.execute('SELECT count(*) FROM result_consumption').fetchone()[0]==1
            assert f.runtime.attempts.rows(f.scheduled['key'])[-1]['reason']=='isolated_native_no_allocation'
        elif mode=='finish_commit_failure':
            f.runtime.plane.db.set_authorizer(lambda action,a,b,c,d:
                sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_TRANSACTION and a=='COMMIT' else sqlite3.SQLITE_OK)
            try:
                try:f.queue.finish(f.scheduled,f.value,.01)
                except sqlite3.DatabaseError:pass
                else:raise AssertionError('original COMMIT unexpectedly passed')
            finally:f.runtime.plane.db.set_authorizer(None)
            assert not f.runtime.plane.db.in_transaction
            assert f.runtime.plane.get(f.scheduled['key'])['result'] is None
            assert f.work.stages['NATIVE_PREPARATION'].snapshot()['completed_cohorts']==0
        elif mode=='qualified_attempt_commit_failure':
            assert f.queue.finish(f.scheduled,f.value,.01)
            from meme_machine.lanes.pons import pons_selective_cohort as cohort
            assert cohort._current_decision(f.queue,f.request,f.scheduled['key'],f.scheduled['work']['generation'],'qualified')
            f.runtime.plane.db.set_authorizer(lambda action,a,b,c,d:
                sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_TRANSACTION and a=='COMMIT' else sqlite3.SQLITE_OK)
            try:
                try:cohort._record_qualification(f.runtime.attempts,f.scheduled['key'],f.scheduled['work']['generation'],
                    f.value,'QUALIFIED',at=f.at,explanation={},native_request=f.request)
                except sqlite3.DatabaseError:pass
                else:raise AssertionError('attempt COMMIT unexpectedly passed')
            finally:f.runtime.plane.db.set_authorizer(None)
            assert f.runtime.attempts.rows(f.scheduled['key'])==[]
            assert f.work.stages['NATIVE_EVALUATION'].snapshot()['completed_cohorts']==0
        elif mode=='checkpoint_commit_failure':
            assert f.queue.finish(f.scheduled,f.value,.01);decide(f)
            f.runtime.plane.db.set_authorizer(lambda action,a,b,c,d:
                sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_TRANSACTION and a=='COMMIT' else sqlite3.SQLITE_OK)
            try:
                try:checkpoint(f)
                except sqlite3.DatabaseError:pass
                else:raise AssertionError('checkpoint COMMIT unexpectedly passed')
            finally:f.runtime.plane.db.set_authorizer(None)
            assert f.queue.acknowledge(f.scheduled)
            assert f.work.stages['NATIVE_WORK_DISPOSITION'].snapshot()['completed_cohorts']==0
        elif mode=='generation_superseded':
            from tests.lanes.pons.test_pons_finalization import observation
            old=f.scheduled;event=dict(old['event'])
            event.update(observation(9,block=101),address=old['event']['address'])
            assert f.queue.enqueue(event,now=f.at)
            assert not f.queue.finish(old,f.value,.01)
            newer=f.queue.pop(now=f.at);assert newer['work']['generation']!=old['work']['generation']
            assert len(f.queue.rows)==3
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(lambda:f.value)
                issued=f.work.issued(f.queue,newer,future)
                assert issued is not None;future.result(2)
            f.scheduled=newer;f.request=issued
            assert f.queue.finish(newer,f.value,.01);decide(f);checkpoint(f);f.queue.acknowledge(newer)
            for value in f.work.snapshot()['stages'].values():
                assert value['completed_cohorts']==1 and value['pending_units']==1
        elif mode=='observer_failure':
            trace=[];f.runtime.plane.db.set_trace_callback(trace.append)
            with patch.object(f.work.stages['NATIVE_PREPARATION'],'observe',side_effect=RuntimeError('observer-only')):
                assert f.queue.finish(f.scheduled,f.value,.01)
            f.runtime.plane.db.set_trace_callback(None)
            assert f.runtime.plane.get(f.scheduled['key'])['result'] is not None
            assert trace.count('COMMIT')==2 and 'ROLLBACK' not in trace
            assert f.work.snapshot()['state']=='UNKNOWN'
        elif mode=='inventory_bound':
            trace=[];f.runtime.plane.db.set_trace_callback(trace.append)
            before=f.queue.rows;ordinary=tuple(trace);trace.clear()
            with patch('meme_machine.runtime.pons_current_work.MAX_ROWS',2):after=f.queue.rows
            f.runtime.plane.db.set_trace_callback(None)
            assert before==after and tuple(trace)==ordinary and len(after)==3
            assert f.work.snapshot()['state']=='UNKNOWN'
        elif mode=='cancel_queued':
            from concurrent.futures import CancelledError
            assert f.future.cancel()
            try:f.future.result(2)
            except CancelledError:pass
            else:raise AssertionError('original cancellation swallowed')
            assert f.runtime.plane.get(f.scheduled['key'])['claim']==f.scheduled['work']['claim']
            assert f.runtime.plane.get(f.scheduled['key'])['result'] is None
            for stage in f.work.stages.values():
                value=stage.snapshot()
                assert value['pending_units']==1 and value['completed_cohorts']==0
        elif mode=='retained_replay':
            from meme_machine.runtime.pons_economic_cohort import PonsEconomicCohorts
            endpoint='https://robinhood-mainnet.g.alchemy.com/v2/SYNTHETIC_NATIVE_WORK'
            assert f.queue.finish(f.scheduled,f.value,.01)
            replay=PonsEconomicCohorts('new-observer-over-retained-native-outbox',endpoint,native_owner=cap)
            f.runtime.plane.economic_cohorts=replay
            pending=list(f.queue.committed());assert len(pending)==1
            assert f.queue.acknowledge(pending[0][0])
            for stage in replay.current_work.stages.values():
                value=stage.snapshot()
                assert value['expected_units']==0 and value['completed_cohorts']==0
            assert replay.current_work.snapshot()['restored_prefix_closure']=='UNESTABLISHED'
        elif mode=='wallet_overlay':
            from meme_machine.lanes.pons import pons_selective_cohort as cohort
            from meme_machine.runtime.pons_current_work import overlaid
            assert f.queue.finish(f.scheduled,f.value,.01)
            book=cohort.WalletSkillBook(str(f.resources.root/'wallet-skill.sqlite'))
            try:overlay=cohort._attach_wallet_overlay(f.value['vector'],book)
            finally:book.close()
            overlaid(f.runtime.plane,f.request,f.value['vector'],overlay)
            decide(f);checkpoint(f);f.queue.acknowledge(f.scheduled)
            assert all(stage.snapshot()['completed_cohorts']==1 for stage in f.work.stages.values())
        elif mode=='checkpoint_body':
            assert f.queue.finish(f.scheduled,f.value,.01);decide(f)
            checkpoint(f,changed=True)
            assert f.queue.acknowledge(f.scheduled)
            assert f.work.stages['NATIVE_WORK_DISPOSITION'].snapshot()['completed_cohorts']==0
            assert f.work.snapshot()['state']=='UNKNOWN'
        else:raise AssertionError(mode)
        state=f.work.snapshot()
        assert state['restored_prefix_closure']=='UNESTABLISHED'
        assert state['source_closure']=='UNESTABLISHED' and state['full_market_rate']=='UNKNOWN'
        assert not state['readiness_authority'] and not hasattr(f.runtime,'book')


class PonsCurrentWorkTests(unittest.TestCase):
    def child(self,mode):
        case=owner_fixture.NativePonsOwnerTests();case.setUp();self.addCleanup(case.doCleanups)
        anchor=('        pons.require_pons_owner_context(cap,initial=True)\n'
                '        with ThreadPoolExecutor(max_workers=1) as pool:\n')
        self.assertEqual(owner_fixture.CHILD.count(anchor),1)
        script=owner_fixture.CHILD.replace(anchor,
            '        pons.require_pons_owner_context(cap,initial=True)\n'
            '        from tests.test_pons_current_work import run_native_case\n'
            '        run_native_case(cap,mode)\n'
            '        with ThreadPoolExecutor(max_workers=1) as pool:\n')
        channel=pons.PonsOwnerLaunch(case.context)
        with patch.object(owner_fixture,'CHILD',script):child=case.launch(channel,mode=mode)
        value=case.bind(channel,child);raw=child.stdout.readline()
        self.assertTrue(raw,child.stderr.read() if child.poll() is not None else 'closed stdout')
        self.assertEqual(json.loads(raw)['identity_sha256'],pons.digest(value));case.finish(child)

    def test_actual_current_native_commits_denial_checkpoint_and_consumption(self):self.child('native_current')
    def test_original_result_commit_failure_cannot_publish_preparation(self):self.child('finish_commit_failure')
    def test_original_attempt_commit_failure_cannot_publish_evaluation(self):self.child('qualified_attempt_commit_failure')
    def test_original_checkpoint_failure_cannot_publish_work_completion(self):self.child('checkpoint_commit_failure')
    def test_superseded_native_generation_is_not_completed_by_successor(self):self.child('generation_superseded')
    def test_postcommit_observer_failure_never_retries_or_rolls_back_native_result(self):self.child('observer_failure')
    def test_pending_inventory_bound_preserves_original_query_and_output(self):self.child('inventory_bound')
    def test_actual_queued_future_cancellation_and_owner_join_never_fabricate_completion(self):self.child('cancel_queued')
    def test_retained_native_outbox_replay_is_not_a_new_submitted_request(self):self.child('retained_replay')
    def test_original_postdecision_wallet_overlay_preserves_exact_qualification_link(self):self.child('wallet_overlay')
    def test_matching_generation_with_changed_checkpoint_vector_cannot_complete_work(self):self.child('checkpoint_body')
