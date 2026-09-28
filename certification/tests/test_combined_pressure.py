import copy
import json
from pathlib import Path
import tempfile
import unittest
from certification.combined_pressure import verified


def valid_report(sha='sha'):
    samples=[]
    for seconds in (216,378):
        samples.append(dict(source_seconds=seconds,archived_records=10000,compacted_records=9000,
            observed_pause_seconds=8.01,multiframe_batches=3,source_frames_while_reader=4,
            reader_source_advance=4,reader_compaction_advance=256,
            reader_snapshot_preserved=True,completed_tail_delayed=True,
            observation_revision='durable-window-v3',cleanup_window_status='serviced',
            eligible_at_reader_start=True,eligible_at_reader_end=False))
    return dict(passed=True,integration_sha=sha,provider_calls=0,frames=2223,source_seconds=600.21,
        candidate_checks=60,archive_records_verified=200000,
        counters={'stream_accepted_messages':2223,'compacted_records':200000},
        ipc={'stream.received_messages':2224,'stream.commit_messages':2224,
             'stream.outstanding_frames_peak':20,'stream.dispatch_bytes_peak':80*1024*1024,
             'stream.commit_batch_messages_peak':4,'stream.commit_batch_bytes_peak':16*1024*1024,
             'stream.maintenance_backpressure_batching':5,'stream.maintenance_limited_commit_batches':100,
             'checkpoint.tail_deferred':2,'checkpoint.boundary_reclaimed':2},
        lag_peak=8,hot_peak=1000000000,integrity=['ok'],oldest_hot_age_peak=188,oldest_retained_age_peak=189,
        measured_contention=dict(profile='run381-fullcert-36293751021',owner_seconds_per_frame=.165,
            archive_seconds_per_thousand=.36,additional_commit_latency_seconds=.006,delayed_commits=100),
        combined_load=dict(observation_revision='durable-window-v3',profile='mature-burst-reader-tail-urgent-v2',held_reader_cycles=2,
            tail_delay_cycles=2,urgent_acks=100,urgent_errors=[],burst_evidence=samples))


class CombinedPressureTests(unittest.TestCase):
    def test_unexercised_interactions_cannot_pass(self):
        self.assertTrue(verified(valid_report(),'sha'))
        for field in ('stream.maintenance_backpressure_batching','stream.maintenance_limited_commit_batches',
                      'checkpoint.tail_deferred','checkpoint.boundary_reclaimed','stream.outstanding_frames_peak'):
            row=valid_report();row['ipc'][field]=0
            self.assertFalse(verified(row,'sha'),field)
        for field in ('held_reader_cycles','tail_delay_cycles','urgent_acks'):
            row=valid_report();row['combined_load'][field]=0
            self.assertFalse(verified(row,'sha'),field)
        for field in ('compacted_records','multiframe_batches','source_frames_while_reader',
                      'reader_source_advance','reader_compaction_advance','observed_pause_seconds',
                      'reader_snapshot_preserved','completed_tail_delayed'):
            row=valid_report();row['combined_load']['burst_evidence'][0][field]=0
            self.assertFalse(verified(row,'sha'),field)
        self.assertFalse(verified(valid_report(),'other'));self.assertFalse(verified({},'sha'))

    def test_final_certificate_requires_combined_evidence(self):
        from certification.tests.test_final_acceptance import FinalAcceptanceTests
        from certification.final_acceptance import run
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);FinalAcceptanceTests().build(root)
            path=root/'combined-pressure/result.json'
            row=json.loads(path.read_text());row['ipc']['stream.maintenance_backpressure_batching']=0
            path.write_text(json.dumps(row))
            self.assertEqual(run(root,root/'final.json','sha',root/'registry.json'),1)
            self.assertFalse(json.loads((root/'final.json').read_text())['gates']['combined_mature_solana_pressure'])
            path.unlink()
            self.assertEqual(run(root,root/'final.json','sha',root/'registry.json'),1)


if __name__=='__main__':unittest.main()
