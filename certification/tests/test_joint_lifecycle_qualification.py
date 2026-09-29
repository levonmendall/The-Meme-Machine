"""A drained retirement queue cannot mask hot debt, starvation, or bad metrics."""
from copy import deepcopy
from pathlib import Path
from dataclasses import replace
import tempfile
import time
import unittest
from certification import joint_lifecycle_qualification as joint
from certification.tests.test_cleanup_recovery import samples as old_samples
from meme_machine.solana_evidence_plane import EvidenceWriter
from tests.test_run381_retention_progress import record


def samples():
    rows=old_samples()
    for r in rows:
        debt=r['scopes']['program:meteora']['archived_pending']
        r.update(monotonic=r['source_seconds'],observer_ms=3,
                 observation_revision='joint-lifecycle-snapshot-v1')
        r['scopes']={scope:dict(archived_pending=debt,hot=90000+debt,
                               age_eligible_hot=debt,oldest_hot_age=190)
                     for scope in joint.SCOPES}
    return rows


def report():
    r=dict(storage_maintenance={},retained_by_scope=[],ipc={},
           oldest_hot_age_peak=195,oldest_retained_age_peak=198)
    for scope in joint.SCOPES:
        label=scope.split(':',1)[1]
        r['retained_by_scope'].append(dict(scope=scope,hot=90,archived_pending=10))
        for stage,value in (('source',1100),('archive',1010)):
            r['storage_maintenance']['lifecycle.'+stage+'.'+label+'.records']=value
        r['storage_maintenance']['lifecycle.retention.'+label+'.retired_records']=1000
    for stage in ('source_commit','archive_commit_plan','retention'):
        prefix='owner.stage.'+stage
        r['ipc'][prefix+'.calls']=10
        for kind in ('queue','execution'):r['ipc'][prefix+'.'+kind+'_total_microseconds']=10
    return r


class JointLifecycleTests(unittest.TestCase):
    def assess(self,rows):
        with joint.qualification():return joint.recovery_assessment(rows)

    def test_all_scopes_both_debts_recover_with_advancing_source(self):
        result=self.assess(samples())
        self.assertTrue(result['passed'],result['failures'])
        self.assertEqual(set(result['joint_lifecycle']['scopes']),set(joint.SCOPES))

    def test_small_retirement_queue_cannot_hide_hot_side_failure(self):
        rows=samples()
        for r in rows:
            if r['source_seconds']>245:
                r['scopes']['program:meteora']['hot']+=int((r['source_seconds']-245)*50)
                r['scopes']['program:meteora']['age_eligible_hot']+=int((r['source_seconds']-245)*50)
        self.assertTrue(joint.original_assessment(rows)['passed'])
        result=self.assess(rows)
        self.assertFalse(result['passed'])
        self.assertTrue(any('program:meteora:hot' in f for f in result['failures']))

    def test_another_scope_cannot_be_starved_behind_meteora(self):
        rows=samples()
        for r in rows:
            if r['source_seconds']>245:r['scopes']['program:pump']['archived_pending']+=9000
        self.assertTrue(joint.original_assessment(rows)['passed'])
        self.assertFalse(self.assess(rows)['passed'])

    def test_hot_tail_growth_after_recovery_still_fails(self):
        rows=samples()
        for r in rows:
            if r['source_seconds']>960:r['scopes']['program:pumpswap']['hot']+=int((r['source_seconds']-960)*25)
        self.assertFalse(self.assess(rows)['passed'])

    def test_missing_field_overhead_or_boundary_age_fails(self):
        for change in ('missing','overhead','age'):
            rows=samples()
            if change=='missing':rows[20]['scopes']['program:pump'].pop('hot')
            elif change=='overhead':
                for r in rows:r['observer_ms']=100
            else:rows[20]['scopes']['program:pump']['oldest_hot_age']=240
            self.assertFalse(self.assess(rows)['passed'],change)

    def test_source_stop_pins_and_short_observation_still_fail(self):
        self.assertFalse(self.assess(samples()[:50])['passed'])
        rows=samples()
        for r in rows:
            if r['source_seconds']>390:r['source_frames']=int(390/.27)
        self.assertFalse(self.assess(rows)['passed'])
        rows=samples();rows[10]['active_pins']=1
        self.assertFalse(self.assess(rows)['passed'])

    def test_committed_scope_flow_reconciles_or_fails(self):
        self.assertTrue(joint.useful_work_verified(report()))
        for stage in ('source','archive','retention'):
            r=report();name='retired_records' if stage=='retention' else 'records'
            r['storage_maintenance']['lifecycle.'+stage+'.meteora.'+name]+=1
            self.assertFalse(joint.useful_work_verified(r))
        r=report();r['ipc'].pop('owner.stage.source_commit.queue_total_microseconds')
        self.assertFalse(joint.useful_work_verified(r))

    def test_invalid_timing_duplicate_scope_and_old_revision_fail(self):
        r=report();r['ipc']['owner.stage.source_commit.calls']=True
        self.assertFalse(joint.useful_work_verified(r))
        r=report();r['ipc']['owner.stage.retention.queue_total_microseconds']=-1
        self.assertFalse(joint.useful_work_verified(r))
        r=report();r['retained_by_scope'].append(r['retained_by_scope'][0])
        self.assertFalse(joint.useful_work_verified(r))
        rows=samples();rows[10]['observation_revision']='unreviewed-version'
        self.assertFalse(self.assess(rows)['passed'])

    def test_age_limit_is_strict_not_less_equal_or_nan(self):
        self.assertTrue(joint.strict_age_verified(report()))
        for value in (240,240.01,float('nan'),float('inf'),None):
            r=report();r['oldest_retained_age_peak']=value
            self.assertFalse(joint.strict_age_verified(r))

    def test_real_readonly_snapshot_captures_hot_debt_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db';writer=EvidenceWriter(path)
            try:
                rows=[replace(record(),identity=scope+':sample',signature=scope+':sample',scope=scope)
                      for scope in joint.SCOPES]
                writer.ingest(rows)
                with writer.transaction():writer._count('stream_accepted_messages',1000)
                before=writer.db.total_changes
                observer=object.__new__(joint.JointBacklogObserver)
                observer.path=path;observer.cohorts={}
                with joint.qualification():row=observer._capture()
                self.assertEqual(writer.db.total_changes,before)
                self.assertEqual(row['source_frames'],1000)
                self.assertEqual(row['observation_revision'],'joint-lifecycle-snapshot-v1')
                for scope in joint.SCOPES:
                    self.assertEqual(row['scopes'][scope]['hot'],1)
                    self.assertEqual(row['scopes'][scope]['age_eligible_hot'],1)
                    self.assertEqual(row['scopes'][scope]['archived_pending'],0)
                self.assertEqual(writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            finally:writer.close()
