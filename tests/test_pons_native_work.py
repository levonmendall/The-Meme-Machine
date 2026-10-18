"""Real private child + native fair selection/publication; synthetic inputs.

Root/unit/clock acquisition premises use the existing simulated prewrite
fixture. Scalar policy facts and sizing receipts are synthetic. Native History,
qualification, Plane, Attempts, nonfinancial publication and denial are real.
No market provider, monetary book, boot-prefix or full-market claim is involved.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import sqlite3
import unittest
from unittest.mock import patch

from meme_machine.operational import normal_pons_boot as pons
from meme_machine.runtime.journal import digest
from tests import test_normal_pons_boot as owner_fixture


@contextmanager
def native_fixture(cap,*,count=3):
    from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
    from meme_machine.lanes.pons.pons_attempts import Attempts
    from meme_machine.runtime.directional_sleeve import open_sleeve
    from meme_machine.runtime.pons_economic_cohort import PonsEconomicCohorts
    from tests.test_isolated_native_admission import IsolatedNativeAdmissionTests
    from tests.lanes.pons.test_pons_postgrad_survivor import PonsPostgradSurvivorTests,NOW
    from types import SimpleNamespace
    case=IsolatedNativeAdmissionTests();case.setUp()
    try:
        resources,now=case.owned(NOW)
        runtime=Runtime.__new__(Runtime);runtime.native_resources=resources
        runtime.now=lambda:now[0];runtime.history=resources.survivor_history('pons')
        runtime.sleeve=open_sleeve('pons',None,native_resources=resources)
        runtime.plane=resources.pons_plane();runtime.attempts=Attempts(runtime.plane)
        runtime.candidate_history=resources.candidate_history()
        meter=PonsEconomicCohorts('actual-child-synthetic-native-work',
            'https://robinhood-mainnet.g.alchemy.com/v2/SYNTHETIC_NATIVE_WORK',native_owner=cap)
        runtime.economic_cohorts=meter;runtime.history.economic_cohorts=meter
        facts=PonsPostgradSurvivorTests().cycle_facts()
        graduation=deepcopy(facts['rally_cycle_context']['graduation'])
        header=dict(number='0xb',hash='0x'+'11'*32,timestamp=hex(NOW))
        for index in range(count):
            candidate='native-token' if index==0 else 'other-token-'+str(index)
            runtime.history.graduate(candidate,graduation)
            runtime.history.append_block(candidate,block=11,header=header,events=[],points=[(NOW,'1')])
        with patch('meme_machine.lanes.pons.pons_survivor_runtime.time.time',return_value=NOW):
            decision=runtime.qualify(facts)
        assert decision['candidate'] is True
        yield SimpleNamespace(runtime=runtime,meter=meter,work=meter.native_work,
            resources=resources,case=case,at=NOW,decision=decision,
            state=dict(block=11,block_hash=header['hash'],at=NOW,market_time=NOW))
        case.assert_no_money(resources)
    finally:case.tearDown()


def inventory(fixture):
    from meme_machine.runtime.pons_native_work import survivor_inputs
    with survivor_inputs(fixture.runtime.history,fixture.work) as frame:
        rows=fixture.runtime.history.rows()
    frame.eligibility(rows,admit=True)
    return frame,rows


def request(fixture,frame,rows):
    row=fixture.runtime.history.qualification_turn(rows,fixture.at)
    return row,frame.request(row)


def publish(fixture,row,issued):
    regime=dict(at=fixture.at,rally_cycle=fixture.decision['rally_cycle'])
    with patch('meme_machine.lanes.pons.pons_survivor_runtime.time.time',return_value=fixture.at):
        return fixture.runtime._publish_qualification(row,fixture.decision,regime,
            state=fixture.state,native_request=issued)


def run_native_case(cap,mode):
    with native_fixture(cap) as f:
        frame,rows=inventory(f);row,issued=request(f,frame,rows)
        assert issued is not None
        if mode=='native_publication':
            saved,_,_=publish(f,row,issued)
            assert f.work.evaluations.snapshot()['completed_cohorts']==1
            assert f.work.evaluations.snapshot()['pending_units']==0
            turn=f.work.snapshot()['latest_turn']
            assert (turn['input_count'],turn['eligible_count'],turn['actual_evaluation_requests'],
                turn['eligible_unselected'])==(3,3,1,2)
            assert f.runtime.attempts.rows(saved['id'])[0]['category']=='QUALIFIED'
            assert not f.runtime._allocation_allowed(saved,f.decision)
            assert f.runtime.history.get(saved['id'])['funding_denial']['reason']=='isolated_native_no_allocation'
            # Repeated unselected inventory is not a new evaluation obligation.
            for _ in range(12):inventory(f)
            assert f.work.evaluations.snapshot()['completed_cohorts']==1
            assert f.work.evaluations.snapshot()['active_cohorts']==0
            assert f.work.snapshot()['state']=='MEASURING'
        elif mode=='nested_commit':
            with f.runtime.history.transaction():
                with f.runtime.history.transaction():publish(f,row,issued)
                assert f.work.evaluations.snapshot()['completed_cohorts']==0
                assert f.runtime.history.get(row['id'])['decision']['candidate']
            assert f.work.evaluations.snapshot()['completed_cohorts']==1
        elif mode=='rollback':
            try:
                with f.runtime.history.transaction():
                    publish(f,row,issued)
                    raise RuntimeError('original-native-error')
            except RuntimeError as error:assert str(error)=='original-native-error'
            else:raise AssertionError('original error swallowed')
            assert 'decision' not in f.runtime.history.get(row['id'])
            assert f.work.evaluations.snapshot()['completed_cohorts']==0
            assert f.work.snapshot()['state']=='UNKNOWN'
        elif mode=='commit_failure':
            f.runtime.history.db.set_authorizer(lambda action,a,b,c,d:
                sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_TRANSACTION and a=='COMMIT' else sqlite3.SQLITE_OK)
            try:
                try:
                    with f.runtime.history.transaction():publish(f,row,issued)
                except sqlite3.DatabaseError:pass
                else:raise AssertionError('native COMMIT unexpectedly passed')
            finally:f.runtime.history.db.set_authorizer(None)
            assert not f.runtime.history.db.in_transaction
            assert 'decision' not in f.runtime.history.get(row['id'])
            assert f.work.evaluations.snapshot()['completed_cohorts']==0
        elif mode=='postcommit_failure':
            trace=[];f.runtime.history.db.set_trace_callback(trace.append)
            with patch.object(f.work.evaluations,'observe',side_effect=RuntimeError('observer-only')):
                with f.runtime.history.transaction():publish(f,row,issued)
            f.runtime.history.db.set_trace_callback(None)
            assert trace.count('COMMIT')==1 and 'ROLLBACK' not in trace
            assert f.runtime.history.get(row['id'])['decision']['candidate']
            assert f.work.snapshot()['state']=='UNKNOWN'
        elif mode=='request_generation':
            # A later real selection is not completion of the older request.
            next_frame,next_rows=inventory(f)
            selected=f.runtime.history.get(row['id'])
            newer=f.runtime.history.qualification_turn([selected],f.at)
            assert newer['qualification_attempt']!=row['qualification_attempt']
            next_frame.request(newer)
            publish(f,newer,issued)
            result=f.work.evaluations.snapshot()
            assert result['completed_cohorts']==0 and result['pending_units']==2
            assert result['state']=='UNKNOWN'
            assert f.runtime.history.get(row['id'])['decision']['candidate']
        elif mode=='bounded_census':
            from meme_machine.runtime.pons_native_work import survivor_inputs
            trace=[];f.runtime.history.db.set_trace_callback(trace.append)
            ordinary=f.runtime.history.rows();baseline=tuple(trace);trace.clear()
            with patch('meme_machine.runtime.pons_native_work.MAX_ROWS',2):
                with survivor_inputs(f.runtime.history,f.work):observed=f.runtime.history.rows()
            f.runtime.history.db.set_trace_callback(None)
            assert ordinary==observed and tuple(trace)==baseline
            assert f.work.snapshot()['state']=='UNKNOWN'
            assert len(observed)==3
            with native_fixture(cap) as bounded:
                anchor=bounded.runtime.history.rows()[0]['graduation']
                bounded.runtime.history.graduate('x'*257,anchor)
                before=bounded.runtime.history.rows()
                with survivor_inputs(bounded.runtime.history,bounded.work):
                    after=bounded.runtime.history.rows()
                assert before==after and len(after)==4
                assert bounded.work.snapshot()['state']=='UNKNOWN'
        else:raise AssertionError(mode)
        value=f.work.snapshot()
        assert value['held_protection_closure']=='UNESTABLISHED'
        assert value['full_market_rate']=='UNKNOWN' and not value['readiness_authority']
        assert value['current_consumer_closure']=='UNESTABLISHED'
        assert not hasattr(f.runtime,'book')


class PonsNativeWorkTests(unittest.TestCase):
    def test_caller_facade_cannot_issue_a_native_observer(self):
        from types import SimpleNamespace
        from meme_machine.runtime.pons_native_work import PonsNativeWork
        with self.assertRaisesRegex(ValueError,'pons_native_work_owner_required'):
            PonsNativeWork(SimpleNamespace(require_owner=lambda:None,native_owner=object()))

    def child(self,mode):
        case=owner_fixture.NativePonsOwnerTests();case.setUp();self.addCleanup(case.doCleanups)
        anchor=('        pons.require_pons_owner_context(cap,initial=True)\n'
                '        with ThreadPoolExecutor(max_workers=1) as pool:\n')
        self.assertEqual(owner_fixture.CHILD.count(anchor),1)
        script=owner_fixture.CHILD.replace(anchor,
            '        pons.require_pons_owner_context(cap,initial=True)\n'
            '        from tests.test_pons_native_work import run_native_case\n'
            '        run_native_case(cap,mode)\n'
            '        with ThreadPoolExecutor(max_workers=1) as pool:\n')
        channel=pons.PonsOwnerLaunch(case.context)
        with patch.object(owner_fixture,'CHILD',script):child=case.launch(channel,mode=mode)
        value=case.bind(channel,child);raw=child.stdout.readline()
        self.assertTrue(raw,child.stderr.read() if child.poll() is not None else 'closed stdout')
        self.assertEqual(json.loads(raw)['identity_sha256'],pons.digest(value));case.finish(child)

    def test_actual_policy_plane_attempt_history_publication_and_funding_denial(self):self.child('native_publication')
    def test_nested_native_savepoint_does_not_publish_before_outer_commit(self):self.child('nested_commit')
    def test_original_outer_rollback_keeps_request_unsettled(self):self.child('rollback')
    def test_original_commit_failure_keeps_request_unsettled(self):self.child('commit_failure')
    def test_postcommit_observer_failure_preserves_native_commit_and_return(self):self.child('postcommit_failure')
    def test_new_attempt_cannot_settle_older_native_request(self):self.child('request_generation')
    def test_inventory_overflow_keeps_original_sql_and_rows(self):self.child('bounded_census')
