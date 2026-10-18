"""Pure ordered admission tests; real capture/FULL windows are separate.

These fixtures give no private capability or source completion authority.
"""
from copy import deepcopy
import os
import threading
import unittest
from unittest.mock import patch

from meme_machine.runtime import native_work_cohort as module
from meme_machine.runtime.economic_cohort import checksum
from meme_machine.runtime.native_work_cohort import NativeWorkCohorts,NATIVE_ORDER,project_native_work
from tests import test_pump_current_input_prefix as prefixes


class OrderedNativeWorkTests(unittest.TestCase):
    def meter(self,*,clock=lambda:0.):
        binding=dict(owner_pid=os.getpid(),owner_tid=threading.get_native_id(),owner_instance='a'*32,
            source_identity_sha256='b'*64,private_owner_sha256='c'*64,epoch_sha256='d'*64,
            policy_sha256='e'*64,regime='pump_current')
        return NativeWorkCohorts(binding,'NATIVE_PREPARATION',native_order=NATIVE_ORDER,clock=clock)

    def window(self,meter,position):
        frontier=checksum(['actual-fixture-native-frontier',position])
        cid=checksum([meter.binding,NATIVE_ORDER,position,frontier])
        descriptor=(meter.binding,NATIVE_ORDER,position,frontier)
        return cid,frontier,descriptor

    def begin(self,meter,position):
        cid,frontier,descriptor=self.window(meter,position)
        meter.begin(cid,frontier,native_window=descriptor)
        rows=((checksum(['native-key',position]),checksum(['native-content',position])),)
        meter.expect(cid,rows);meter.seal_expected(cid,1,checksum(rows),checksum(['native-census',position]))
        return cid,rows

    def close(self,meter,cid,rows):
        meter.observe(cid,((*rows[0],'HISTORY_COMMITTED',checksum(['original-FULL-receipt',cid]),None),))

    def test_pure_admission_exceeds_old_lifetime_without_retaining_closed_ids(self):
        meter=self.meter()
        for position in range(1,8201):
            cid,rows=self.begin(meter,position);self.close(meter,cid,rows)
        raw=meter.snapshot();view=project_native_work(raw)
        self.assertEqual(view['state'],'MEASURING')
        self.assertEqual(view['completed_cohorts'],8200)
        self.assertEqual(view['summary_evictions'],8200-module.MAX_SUMMARIES)
        self.assertEqual(view['native_order']['highest_issued_position'],8200)
        self.assertEqual(view['native_order']['issued_windows'],8200)
        self.assertEqual(view['metadata_bytes'],0);self.assertEqual(view['pending_units'],0)
        self.assertEqual(len(meter.seen),0);self.assertEqual(len(meter.active),0)
        self.assertEqual(len(meter.closed),module.MAX_SUMMARIES)
        self.assertEqual(project_native_work(view),view)

    def test_old_pending_cohort_survives_two_summary_rotations_and_late_outcome(self):
        meter=self.meter();old,rows=self.begin(meter,1)
        meter.observe(old,((*rows[0],'INCOMPLETE',None,None),))
        for position in range(2,2*module.MAX_SUMMARIES+3):
            cid,current=self.begin(meter,position);self.close(meter,cid,current)
        before=meter.snapshot()
        self.assertEqual(before['pending_units'],1);self.assertEqual(before['active_cohorts'],1)
        self.assertEqual(meter.active[old]['expected'],dict(rows))
        self.close(meter,old,rows);after=meter.snapshot()
        self.assertEqual(after['pending_units'],0)
        self.assertEqual(after['completed_cohorts'],before['completed_cohorts']+1)
        self.assertNotEqual(after['cumulative_summary_sha256'],before['cumulative_summary_sha256'])
        self.assertEqual(after['native_order']['highest_issued_position'],2*module.MAX_SUMMARIES+2)
        self.assertEqual(after['closed'][-1]['native_window_position'],1)
        self.assertEqual(project_native_work(after)['state'],'MEASURING')

    def test_exact_active_begin_is_idempotent_and_never_renews_its_clock(self):
        ticks=[1.];meter=self.meter(clock=lambda:ticks[0]);cid,rows=self.begin(meter,10)
        first=meter.active[cid]['first'];ticks[0]=5.
        _,frontier,descriptor=self.window(meter,10)
        meter.begin(cid,frontier,native_window=descriptor)
        self.assertEqual(meter.native_issued,1);self.assertEqual(meter.active[cid]['first'],first)
        self.assertEqual(meter.units,1)
        self.close(meter,cid,rows);self.assertEqual(meter.completed,1)

    def test_stale_different_closed_and_closed_id_with_higher_position_refuse(self):
        for kind in ('same','lower','different','old_id_new_position'):
            meter=self.meter();old,rows=self.begin(meter,10);self.close(meter,old,rows)
            position=9 if kind=='lower' else 11 if kind=='old_id_new_position' else 10
            cid,frontier,descriptor=self.window(meter,position)
            if kind=='different':cid=checksum('another-cohort-at-the-same-cut')
            elif kind=='old_id_new_position':cid=old
            meter.begin(cid,frontier,native_window=descriptor)
            self.assertEqual(meter.snapshot()['state'],'UNKNOWN',kind)
            self.assertEqual(meter.native_issued,1);self.assertEqual(meter.completed,1)

    def test_foreign_binding_domain_frontier_and_source_cannot_admit(self):
        for index,value in ((0,'f'*64),(1,'unrelated-plane-domain'),(3,'f'*64)):
            meter=self.meter();cid,frontier,descriptor=self.window(meter,1)
            changed=list(descriptor);changed[index]=value
            meter.begin(cid,frontier,native_window=tuple(changed))
            self.assertEqual(meter.snapshot()['state'],'UNKNOWN');self.assertEqual(meter.native_issued,0)
        meter=self.meter();cid,frontier,descriptor=self.window(meter,1)
        other=self.meter();other.binding=checksum('another-private-source-generation')
        other.begin(cid,frontier,native_window=descriptor)
        self.assertEqual(other.snapshot()['state'],'UNKNOWN');self.assertEqual(other.native_issued,0)

    def test_foreign_thread_and_clock_failure_leave_pending_unclosed(self):
        meter=self.meter();cid,rows=self.begin(meter,1)
        worker=threading.Thread(target=lambda:self.close(meter,cid,rows));worker.start();worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(meter.completed,0)
        self.assertEqual(meter.snapshot()['pending_units'],1)
        ticks=[1.];meter=self.meter(clock=lambda:ticks[0]);cid,rows=self.begin(meter,1)
        original=module.checksum
        def hash_then_regress(value):
            result=original(value)
            if isinstance(value,list) and len(value)==2 and isinstance(value[1],dict) and 'outcomes_sha256' in value[1]:
                ticks[0]=0.
            return result
        with patch.object(module,'checksum',side_effect=hash_then_regress):self.close(meter,cid,rows)
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN');self.assertEqual(meter.completed,0)
        self.assertEqual(meter.snapshot()['pending_units'],0)
        self.assertEqual(meter.snapshot()['active_cohorts'],1)

    def test_actual_pending_bounds_remain_and_legacy_guard_is_unchanged(self):
        meter=self.meter()
        for position in range(1,module.MAX_ACTIVE+2):self.begin(meter,position)
        view=meter.snapshot();self.assertEqual(view['reason'],'BOUND')
        self.assertEqual(view['active_cohorts'],module.MAX_ACTIVE)
        self.assertEqual(view['pending_units'],module.MAX_ACTIVE)
        legacy=NativeWorkCohorts(dict(owner_pid=123),'NATIVE_PREPARATION',clock=lambda:0.)
        with patch.object(module,'MAX_COHORTS',2):
            for n in range(3):
                cid=checksum(['legacy',n]);legacy.begin(cid,checksum(['frontier',n]))
                legacy.expect(cid,());legacy.seal_expected(cid,0,checksum(()),checksum(['traversal',n]))
        self.assertEqual(legacy.completed,2);self.assertEqual(len(legacy.seen),2)
        self.assertEqual(legacy.snapshot()['reason'],'BOUND')

    def test_late_closed_duplicate_never_adds_credit(self):
        meter=self.meter();cid,rows=self.begin(meter,1);self.close(meter,cid,rows)
        old_chain=meter.chain;self.close(meter,cid,rows)
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
        self.assertEqual(meter.completed,1);self.assertEqual(meter.chain,old_chain)

    def test_projection_refuses_forged_positions_bindings_and_unaccounted_windows(self):
        meter=self.meter();cid,rows=self.begin(meter,1);self.close(meter,cid,rows)
        raw=meter.snapshot();self.assertEqual(project_native_work(raw)['state'],'MEASURING')
        for kind in ('binding','closed_position','issued_count','retained_ids'):
            bad=deepcopy(raw)
            if kind=='binding':bad['native_order']['binding_sha256']='f'*64
            elif kind=='closed_position':bad['closed'][0]['native_window_position']=2
            elif kind=='issued_count':bad['native_order']['issued_windows']=2
            else:bad['native_order']['retained_closed_keys']=1
            self.assertEqual(project_native_work(bad)['state'],'UNKNOWN',kind)

    def test_uncommitted_exact_prefix_retry_can_observe_newer_source_without_new_credit(self):
        inherited=[prefixes.row(1)];fresh=[prefixes.row(2),prefixes.row(3)]
        meter=prefixes.CurrentInputPrefixes('c'*64,prefixes.census(inherited),'a'*64,'b'*32)
        old=prefixes.publication(prefixes.census(inherited),fresh[:1])
        first=meter.capture(0,inherited,old,as_of=100)
        self.assertIsNotNone(first)
        newer=prefixes.publication(prefixes.census(inherited),fresh)
        retry=meter.capture(0,inherited,newer,as_of=100,retry=True)
        self.assertIsNotNone(retry)
        self.assertEqual(first.batch_sha256,retry.batch_sha256)
        self.assertEqual(first.version,retry.version)
        self.assertEqual(meter.snapshot()['inherited_retained']['records'],0)
        meter.committed(retry)
        self.assertEqual(meter.snapshot()['inherited_retained']['records'],1)
        self.assertEqual(meter.snapshot()['source_expected']['records'],2)
        self.assertEqual(meter.snapshot()['source_retained']['records'],0)
        self.assertEqual(meter.snapshot()['state'],'INCOMPLETE')

    def test_uncommitted_retry_cannot_regress_source_or_change_selected_membership(self):
        inherited=[prefixes.row(1)];fresh=[prefixes.row(2),prefixes.row(3)]
        for kind in ('regress','same_count_changed','changed_batch'):
            meter=prefixes.CurrentInputPrefixes('c'*64,prefixes.census(inherited),'a'*64,'b'*32)
            self.assertIsNotNone(meter.capture(0,inherited,
                prefixes.publication(prefixes.census(inherited),fresh),as_of=100))
            metadata=prefixes.publication(prefixes.census(inherited),fresh)
            rows=inherited
            if kind=='regress':metadata=prefixes.publication(prefixes.census(inherited),fresh[:1])
            elif kind=='same_count_changed':metadata['economic']['programs']['program:pump']['prefix_sha256']='f'*64
            else:rows=[(*inherited[0][:3],999,inherited[0][4])]
            self.assertIsNone(meter.capture(0,rows,metadata,as_of=100,retry=True))
            self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
            self.assertEqual(meter.snapshot()['inherited_retained']['records'],0)


if __name__=='__main__':unittest.main()
