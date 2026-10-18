"""Actual private Current capture/FULL windows, not market-rate evidence.

The storage fixture is synthetic and acquisition/root-install premises are the
existing native fixture's. Original canonical ingestion, anonymous owner IPC,
prewrite replay, source snapshots and FULL history transactions actually run.
One-row windows use the original ConsumerReader's admitted limit=1 API; they do
not change production's 5000-row default or issue per-event strategy work.
"""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from tests import test_pump_current_input_native as native

ORIGINAL_ROWS=native.native_rows

def create_rows(first,count,*,available=native.NOW):
    rows=[]
    for row in ORIGINAL_ROWS(first,count,available=available):
        payload=dict(row.payload);event=dict(payload['event'])
        event.update(event_type='create',bonding_curve='storage-curve:'+row.identity)
        payload['event']=event
        rows.append(replace(row,payload=payload))
    return rows


def changed(script,old,new):
    if script.count(old)!=1:raise AssertionError('native fixture anchor changed')
    return script.replace(old,new,1)


CHILD=changed(native.CHILD,'from tests.test_pump_current_input_native import initial_generation',
'''from tests.test_pump_current_input_native import initial_generation
from tests import test_pump_current_input_native as native_fixture
from tests.test_native_ordered_current import create_rows''')
CHILD=changed(CHILD,"fixture=json.loads(sys.stdin.readline());locator,record=fixture['locator'],fixture['record'];role=fixture['role']",
"""fixture=json.loads(sys.stdin.readline());locator,record=fixture['locator'],fixture['record'];role=fixture['role']
if fixture.get('creates'):native_fixture.native_rows=create_rows""")
CHILD=changed(CHILD,"                views=[];sequence=0;physical=[];capture_cost=[];".rstrip(';'),
'''                bulk=None
                if fixture.get('windows'):
                    count=fixture['windows']
                    # Warm identical original history first, outside either
                    # measured arm; no observed completion is issued here.
                    plain=LocalPumpTape(plane);cursor=0
                    for _ in range((count+4999)//5000+1):
                        events,cursor=plain.events_since(cursor)
                        assert events==[]
                    original_discovery=reader.discovery
                    def one_row(sequence,*,as_of,limit=5000):
                        return original_discovery(sequence,as_of=as_of,limit=1)
                    reader.discovery=one_row
                    phases={};saved=[];real_observe=work.inputs.observe
                    def late_first(cid,rows):
                        if not saved:
                            saved.append((cid,rows));return
                        real_observe(cid,rows)
                    work.inputs.observe=late_first
                    for name,target in (('plain',plain),('observed',tape)):
                        counts=dict(queries=0,frontier_queries=0,key_queries=0)
                        from meme_machine.runtime import native_work_cohort as common_module
                        from meme_machine.runtime import pump_current_work as work_module
                        from meme_machine.runtime import pump_current_input_prefix as prefix_module
                        from contextlib import ExitStack
                        hashes={}
                        def counted(module):
                            actual=module.checksum;label=module.__name__;hashes[label]=0
                            def digest(value):
                                hashes[label]+=1;return actual(value)
                            return digest
                        def query(sql):
                            counts['queries']+=1
                            counts['frontier_queries']+=int('source_generation_frontier' in sql)
                            counts['key_queries']+=int('INDEXED BY candidate_outbox_scope' in sql)
                        original.db.set_trace_callback(query)
                        cursor=0;started=time.perf_counter();cpu=time.thread_time()
                        with ExitStack() as stack:
                            for module in (common_module,work_module,prefix_module):
                                stack.enter_context(patch.object(module,'checksum',counted(module)))
                            for turn in range(count):
                                events,cursor=target.events_since(cursor)
                                assert events==[] and not original.db.in_transaction
                                if target.native_work is not None:target.native_work.finish()
                        phases[name]=dict(wall=time.perf_counter()-started,cpu=time.thread_time()-cpu,
                            cursor=cursor,windows=count,metadata_hash_calls=hashes,**counts)
                        original.db.set_trace_callback(None)
                    before=work.inputs.snapshot()
                    assert len(saved)==1 and before['active_cohorts']==1
                    expected=dict(work.inputs.active[saved[0][0]]['expected'])
                    highest=work.inputs.native_highest
                    # Delay only the observational publication of an actual
                    # first native FILTERED outcome, not the native operation.
                    real_observe(*saved[0]);after=work.inputs.snapshot()
                    bulk=dict(phases=phases,before=before,after=after,
                        evaluation=work.evaluations.snapshot(),
                        highwater_unchanged=work.inputs.native_highest==highest,
                        delayed_expected_units=len(expected),retained_closed_keys=len(work.inputs.seen),
                        retained_summaries=len(work.inputs.closed),metadata_bytes=work.inputs.bytes,
                        input_prefix=work.input_context.snapshot())
                    fixture['commands']=[]
                views=[];sequence=0;physical=[];capture_cost=[]''')
CHILD=changed(CHILD,"                    if command=='future':tape.plane.clock=lambda:NOW+100",
'''                    if command=='cancel_after_capture':
                        captured=work.input_context.prefixes.capture
                        def captured_then_stop(*args,**kwargs):
                            result=captured(*args,**kwargs);requested.set();return result
                        with patch.object(work.input_context.prefixes,'capture',side_effect=captured_then_stop):
                            try:tape.events_since(sequence)
                            except Shutdown:pass
                            else:raise AssertionError('late native cancellation missing')
                            finally:requested.clear()
                        assert not original.db.in_transaction
                        views.append(work.snapshot()['native_input_prefix']);continue
                    if command=='future':tape.plane.clock=lambda:NOW+100''')
CHILD=changed(CHILD,"                    if command=='failed_full':",
"                    if command in ('failed_full','failed_second_full'):")
CHILD=changed(CHILD,"                        class FailedCommit:",
"                        commits=[0]\n                        class FailedCommit:")
CHILD=changed(CHILD,"                                if sql=='COMMIT':raise sqlite3.OperationalError('private-native-full-commit-failed')",
'''                                if sql=='COMMIT':
                                    commits[0]+=1
                                    if commits[0]==(2 if command=='failed_second_full' else 1):
                                        raise sqlite3.OperationalError('private-native-full-commit-failed')''')
CHILD=changed(CHILD,'                print(json.dumps(dict(views=views,physical=physical,matched=matched,capture_cost=capture_cost,queued=queued,sequence=sequence,',
'                print(json.dumps(dict(work=work.snapshot(),bulk=bulk,views=views,physical=physical,matched=matched,capture_cost=capture_cost,queued=queued,sequence=sequence,')


class OrderedCurrentNativeTests(unittest.TestCase):
    def setUp(self):
        self.case=native.CurrentPrivateInputTests();self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.enterContext(patch.object(native,'CHILD',CHILD))

    def test_failed_full_exact_native_retry_keeps_original_issuance_and_counts_once(self):
        self.case.prepare(2);self.case.child('source')
        _,value=self.case.child('pump',commands=['failed_full','consume'])
        self.assertEqual(value['views'][0]['retained_prefix']['inherited_retained']['records'],0)
        self.assertEqual(value['views'][-1]['state'],'OBSERVED')
        self.assertEqual(value['retained'],2)
        self.assertEqual(value['work']['discovery']['state'],'MEASURING')
        self.assertEqual(value['work']['discovery']['native_order']['issued_windows'],1)
        self.assertEqual(value['work']['discovery']['expected_units'],2)

    def test_partial_original_full_failure_replays_native_rows_without_double_counting(self):
        self.case.prepare(65);self.case.child('source')
        _,value=self.case.child('pump',commands=['failed_second_full','consume'])
        self.assertEqual(value['views'][0]['retained_prefix']['inherited_retained']['records'],0)
        self.assertTrue(value['views'][0]['retained_prefix']['capture_pending'])
        self.assertEqual(value['views'][-1]['state'],'OBSERVED')
        self.assertEqual(value['retained'],65)
        self.assertEqual(value['work']['discovery']['native_order']['issued_windows'],1)
        self.assertEqual(value['work']['discovery']['expected_units'],65)

    def test_cancellation_after_final_capture_fold_does_not_publish_or_orphan_retry(self):
        self.case.prepare(2);self.case.child('source')
        _,value=self.case.child('pump',commands=['cancel_after_capture','consume'])
        first=value['views'][0]
        self.assertFalse(first['retained_prefix']['capture_pending'])
        self.assertEqual(first['retained_prefix']['inherited_retained']['records'],0)
        self.assertEqual(value['views'][-1]['state'],'OBSERVED')
        self.assertEqual(value['retained'],2)
        self.assertEqual(value['work']['discovery']['native_order']['issued_windows'],1)

    def test_8193_original_native_windows_keep_late_pending_debt_and_bounded_summary(self):
        # Same protocol namespace includes inherited and actual new-source
        # publication: 8190 fixed-cut rows plus three original registry rows.
        with patch.object(native,'native_rows',create_rows):self.case.prepare(8190)
        self.case.child('source',fresh=3,creates=True)
        _,value=self.case.child('pump',windows=8193,fixed_lease=True)
        bulk=value['bulk'];before,after=bulk['before'],bulk['after']
        self.assertEqual(before['completed_cohorts'],8192)
        self.assertEqual(before['active_cohorts'],1);self.assertEqual(before['pending_units'],1)
        self.assertGreaterEqual(before['summary_evictions'],2*16)
        self.assertEqual(after['state'],'MEASURING');self.assertEqual(after['completed_cohorts'],8193)
        self.assertEqual(after['active_cohorts'],0);self.assertEqual(after['pending_units'],0)
        self.assertEqual(after['native_order']['issued_windows'],8193)
        self.assertEqual(bulk['evaluation']['completed_cohorts'],8193)
        self.assertEqual(bulk['evaluation']['state'],'MEASURING')
        self.assertTrue(bulk['highwater_unchanged']);self.assertEqual(bulk['delayed_expected_units'],1)
        self.assertEqual(bulk['retained_closed_keys'],0);self.assertEqual(bulk['retained_summaries'],16)
        self.assertEqual(bulk['metadata_bytes'],0)
        self.assertEqual(bulk['input_prefix']['state'],'OBSERVED')
        self.assertEqual(bulk['input_prefix']['retained_prefix']['inherited_retained']['records'],8190)
        self.assertEqual(bulk['input_prefix']['retained_prefix']['source_retained']['records'],3)
        self.assertEqual(value['retained'],8193)
        self.assertEqual(bulk['phases']['plain']['cursor'],bulk['phases']['observed']['cursor'])
        self.assertEqual(bulk['phases']['plain']['frontier_queries'],0)
        self.assertEqual(bulk['phases']['plain']['key_queries'],0)
        self.assertEqual(bulk['phases']['observed']['frontier_queries'],8193)
        self.assertFalse(value['source_transaction'])
        print('ordered-native-8193-matched-cost '+json.dumps(bulk['phases'],sort_keys=True))


if __name__=='__main__':unittest.main()
