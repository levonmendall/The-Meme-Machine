import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import os
import unittest

from meme_machine.operational import observation
from meme_machine.portfolio_accounting import PortfolioAccounting, inception_receipt
from meme_machine.operational.supervisor import identities


class ReadOnlyObservation(unittest.TestCase):
    def test_read_only_replay_preserves_writer_lock_and_economic_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'portfolio.sqlite'
            account=PortfolioAccounting(p)
            values=identities()
            account.establish_inception(inception_receipt('offline-fixture-observation','2026-01-01T00:00:00Z','fixture'),portfolio_identities=values['pump'],lane_identities=values)
            account.configure_family_sleeves()
            before=account.snapshot()
            first=observation.database(p,observation.portfolio)
            self.assertEqual(first['epoch_id'],'offline-fixture-observation')
            self.assertEqual(first['reconciliation'],'PASS')
            self.assertEqual(account.snapshot(),before)
            with self.assertRaisesRegex(RuntimeError,'writer_already_running'):
                PortfolioAccounting(p)
            account.close()
            checksum=hashlib.sha256(p.read_bytes()).hexdigest()
            self.assertEqual(observation.database(p,observation.portfolio)['reconciliation'],'PASS')
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),checksum)

    def test_sqlite_read_only_mode_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'data.sqlite'
            with sqlite3.connect(p) as db:db.execute('CREATE TABLE data(value)')
            before=hashlib.sha256(p.read_bytes()).hexdigest()
            result=observation.database(p,lambda db:dict(changes=db.execute('INSERT INTO data VALUES(1)').rowcount))
            self.assertEqual(result['state'],'UNAVAILABLE')
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),before)

    def test_arbitrary_provider_strings_are_not_published(self):
        value={'endpoint':'https://rpc.invalid/provider-secret','phase':'MANAGING','counters':{'failures':3,'credential':'private'},'storage':{'state':'CURRENT','free_bytes':123}}
        result=observation.numeric(value)
        self.assertEqual(result['phase'],'MANAGING')
        self.assertEqual(result['counters'],{'failures':3})
        self.assertNotIn('provider-secret',json.dumps(result))
        self.assertNotIn('credential',json.dumps(result))

    def test_observation_error_cannot_initialize_missing_database(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'missing.sqlite'
            self.assertEqual(observation.database(p,observation.portfolio)['state'],'UNAVAILABLE')
            self.assertFalse(p.exists())

    def test_corrupt_database_is_actionable_without_a_write(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'data.sqlite';p.write_bytes(b'corrupt durable fixture')
            before=p.read_bytes()
            row=observation.database(p,lambda db:dict(count=db.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()[0]))
            self.assertEqual(row['state'],'FAIL_CLOSED')
            self.assertTrue(row['integrity_failure'])
            self.assertEqual(p.read_bytes(),before)

    def test_native_sqlite3_corruption_is_included_in_rotating_integrity_checks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'state';root.mkdir()
            folder=Path(td)/'observations';folder.mkdir()
            p=root/'native.accounting.sqlite3';p.write_bytes(b'corrupt native journal')
            before=p.read_bytes()
            value={'storage':{p.name:p.stat().st_size}}
            observation.check_next_database(root,folder,value)
            self.assertTrue(value['database_integrity'][p.name]['integrity_failure'])
            self.assertEqual(p.read_bytes(),before)

    def test_survivor_progress_is_distinct_from_current_lane_progress_and_redacted(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'pump/pump-acceleration-natural-prospective.json'
            p.parent.mkdir()
            p.write_text(json.dumps(dict(counts={'current_qualifiers':5},
                survivor=dict(active=True,last_boundary='https://rpc.invalid/provider-secret',
                    candidate_count=7,machinery=dict(completed_steps=11,last_step_completed_at=123)))))
            os.utime(p,(150,150));before=p.read_bytes();regimes={}
            observation.directional_reports(root,regimes,now=160)
            current=regimes['Pump Current'];survivor=regimes['Pump Survivor']
            self.assertEqual(current['machinery']['counts']['current_qualifiers'],5)
            self.assertEqual(survivor['machinery']['machinery']['completed_steps'],11)
            self.assertTrue(survivor['boundary_present'])
            self.assertNotIn('provider-secret',json.dumps(regimes))
            self.assertEqual(regimes['Pons Survivor']['observation_state'],'UNAVAILABLE')
            self.assertEqual(p.read_bytes(),before)
            observation.directional_reports(root,regimes,now=220)
            self.assertEqual(regimes['Pump Survivor']['report_state'],'STALE')

    def test_invalid_or_oversized_projection_does_not_break_other_observations(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'pump/pump-acceleration-natural-prospective.json'
            p.parent.mkdir();p.write_text('[]');regimes={}
            observation.directional_reports(root,regimes)
            self.assertEqual(regimes['Pump Current']['report_state'],'UNAVAILABLE')
            p.write_bytes(b' '*(16*1024**2+1))
            observation.directional_reports(root,regimes)
            self.assertEqual(regimes['Pump Survivor']['observation_state'],'UNAVAILABLE')

    def test_current_projection_does_not_duplicate_shared_stream_telemetry(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'pump/pump-acceleration-natural-prospective.json'
            p.parent.mkdir()
            stream={f'counter{i}':i for i in range(128)}
            p.write_text(json.dumps(dict(counts={'current_qualifiers':5},
                stream=dict(evidence_runtime=stream),evidence_queue={'pending':7})))
            regimes={};observation.directional_reports(root,regimes)
            current=regimes['Pump Current']['machinery']
            self.assertNotIn('stream',current)
            self.assertEqual(current['counts']['current_qualifiers'],5)
            self.assertEqual(current['evidence_queue']['pending'],7)


if __name__=='__main__':unittest.main()
