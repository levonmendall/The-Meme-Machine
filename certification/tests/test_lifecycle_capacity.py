"""A smaller retirement queue cannot hide hot/archive or another scope's debt."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest
from certification.lifecycle_capacity import assessment,REVISION,SCOPES,LifecycleObserver
from meme_machine.solana_evidence_plane import EvidenceWriter
from tests.test_run381_retention_progress import record
from certification.tests.test_cleanup_recovery import samples as original_samples


def samples():
    rows=original_samples()
    for row in rows:
        row['monotonic']=row['source_seconds'];row['observer_ms']=1
        row['lifecycle_revision']=REVISION
        row['lifecycle_observation']=dict(source_frames=row['source_frames'],
            service={},oldest_hot_slot_age={},archive_eligible_hot={})
        base=row['scopes']['program:meteora']['archived_pending']
        for scope in SCOPES:
            row['scopes'][scope]=dict(hot=180000+base,archived_pending=base,oldest_age=190)
            row['lifecycle_observation']['archive_eligible_hot'][scope]=base
            row['lifecycle_observation']['oldest_hot_slot_age'][scope]=185
            frames=row['source_frames']
            row['lifecycle_observation']['service'][scope]=dict(
                ingested=frames*1000,archived=frames*700,retired=frames*600,continuity=frames)
    return rows


class LifecycleCapacityTests(unittest.TestCase):
    def test_archive_debt_excludes_fresh_mandatory_hot_window(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db';writer=EvidenceWriter(path)
            now=int(time.time())
            try:
                writer.ingest([
                    replace(record(),scope='program:meteora',identity='eligible-old',
                        signature='eligible-old',slot=10,market_time=now-200,observed_at=now),
                    replace(record(),scope='program:meteora',identity='fresh-window',
                        signature='fresh-window',slot=11,market_time=now-100,observed_at=now),
                ])
                writer._count('stream_accepted_messages',1)
                observer=object.__new__(LifecycleObserver);observer.path=path
                row=observer._capture()
                self.assertEqual(row['scopes']['program:meteora']['hot'],2)
                self.assertEqual(
                    row['lifecycle_observation']['archive_eligible_hot']['program:meteora'],1)
            finally:writer.close()

    def test_all_stages_scopes_and_original_fixed_cohort_must_recover(self):
        result=assessment(samples())
        self.assertTrue(result['passed'],result['failures'])
        self.assertEqual(set(result['joint_lifecycle']),set(SCOPES))
        self.assertTrue(result['observer_overhead']['passed'])

    def test_total_hot_window_growth_is_not_misclassified_as_archive_debt(self):
        rows=samples()
        for row in rows:
            if row['source_seconds']>245:
                for scope in SCOPES:
                    row['scopes'][scope]['hot']+=int((row['source_seconds']-245)*500)
        result=assessment(rows)
        self.assertTrue(result['passed'],result['failures'])

    def test_archive_eligible_hot_growth_fails_even_when_retirement_queues_clear(self):
        for scope in SCOPES:
            rows=samples()
            for row in rows:
                if row['source_seconds']>300:
                    row['lifecycle_observation']['archive_eligible_hot'][scope]+=int(
                        (row['source_seconds']-300)*500)
            result=assessment(rows)
            self.assertFalse(result['passed'])
            self.assertTrue(any(f'{scope}:archive_eligible_hot:' in e for e in result['failures']))

    def test_other_scope_retirement_starvation_is_not_hidden_by_meteora(self):
        rows=samples()
        for row in rows:
            if row['source_seconds']>245:row['scopes']['program:pump']['archived_pending']+=50000
        self.assertFalse(assessment(rows)['passed'])

    def test_retention_boundary_missing_hot_metrics_or_counter_regression_fail(self):
        for mutate in (
            lambda r:r['lifecycle_observation']['archive_eligible_hot'].pop('program:meteora'),
            lambda r:r['scopes']['program:meteora'].update(oldest_age=240),
            lambda r:r['lifecycle_observation']['oldest_hot_slot_age'].update({'program:meteora':240}),
            lambda r:r['lifecycle_observation']['service']['program:meteora'].update(retired=0),
        ):
            rows=samples();mutate(rows[100]);self.assertFalse(assessment(rows)['passed'])

    def test_expensive_observation_missing_tail_and_old_unversioned_evidence_fail(self):
        rows=samples()
        for row in rows:row['observer_ms']=200
        self.assertFalse(assessment(rows)['passed'])
        self.assertFalse(assessment(samples()[:80])['passed'])
        self.assertFalse(assessment(original_samples())['passed'])


if __name__=='__main__':unittest.main()
