import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import os
import time
import unittest
from unittest.mock import patch

from meme_machine.operational import observation
from meme_machine.portfolio_accounting import PortfolioAccounting, inception_receipt
from meme_machine.operational.supervisor import identities


class ReadOnlyObservation(unittest.TestCase):
    def test_only_the_observers_own_sqlite_read_deadline_allows_projection(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'data.sqlite'
            with sqlite3.connect(p) as db:db.execute('CREATE TABLE data(value)')
            row=observation.database(p,lambda db:db.execute('WITH RECURSIVE n(v) AS (SELECT 1 UNION ALL SELECT v+1 FROM n WHERE v<100000) SELECT SUM(v) FROM n').fetchone(),seconds=-1)
            self.assertEqual(row['sqlite_code'],sqlite3.SQLITE_INTERRUPT)
            self.assertTrue(row['observation_deadline_exhausted'])
            self.assertTrue(observation.projection_allowed(row))
            self.assertFalse(observation.projection_allowed(dict(sqlite_code=sqlite3.SQLITE_INTERRUPT)))

    def test_provider_projection_is_fresh_bounded_redacted_and_never_masks_integrity(self):
        from meme_machine.runtime.usd_valuation import utc
        now=1791234000.0;health=dict(at=utc(now),providers={'robinhood':dict(state='CURRENT',queue_depth=3,
            oldest_wait_seconds=1,endpoint='private-secret',usage=[
                dict(lane='pons',metric='responses_429',value=4),
                dict(lane='pons',metric='private-secret',value=123)])})
        missing=dict(state='UNAVAILABLE',sqlite_code=sqlite3.SQLITE_CANTOPEN)
        with patch.object(observation,'database',return_value=missing):
            row=observation.observed_provider('/unused',health,'robinhood',now)
            self.assertEqual(row['queue_depth'],3)
            self.assertEqual(row['usage'],[dict(lane='pons',metric='responses_429',value=4)])
            self.assertNotIn('private-secret',json.dumps(row))
            self.assertEqual(observation.observed_provider('/unused',health,'robinhood',now+16),missing)
        corrupt=dict(state='FAIL_CLOSED',sqlite_code=sqlite3.SQLITE_CORRUPT)
        with patch.object(observation,'database',return_value=corrupt):
            self.assertEqual(observation.observed_provider('/unused',health,'robinhood',now),corrupt)

    def test_learning_usage_projection_is_bounded_query_only_and_ignores_symlinks(self):
        from meme_machine.runtime import learning
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'facts.sqlite3'
            with sqlite3.connect(p) as db:
                db.execute('BEGIN')
                learning.save(db,'winner','asset','pump-current',1,{'winner_multiple':50})
            before=p.read_bytes()
            row=observation.owner_learning_observation(root)
            self.assertTrue(row['learning_measurement_complete'])
            self.assertEqual(row['learning_rows'],1)
            self.assertGreater(row['learning_store_bytes'],0)
            self.assertEqual(p.read_bytes(),before)
            (root/'link.sqlite').symlink_to(p)
            row=observation.owner_learning_observation(root)
            self.assertFalse(row['learning_measurement_complete'])
            self.assertEqual(row['learning_rows'],1)
            (root/'link.sqlite').unlink()
            with patch.object(observation.time,'monotonic',side_effect=[0,1]):
                self.assertFalse(observation.owner_learning_observation(root)['learning_measurement_complete'])

    def test_portfolio_projection_rejects_expired_mark_validity_despite_fresh_health(self):
        from meme_machine.operational.supervisor import Supervisor
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);supervisor=Supervisor(root,offline=True)
            supervisor.initialize();self.addCleanup(supervisor.lock.close)
            supervisor.publish();supervisor.publish()
            health=json.loads((root/'health.json').read_text())
            health['portfolio_observation']['valid_until']='2020-01-01T00:00:00Z'
            missing=dict(state='UNAVAILABLE',sqlite_code=sqlite3.SQLITE_INTERRUPT,observation_deadline_exhausted=True)
            with patch.object(observation,'database',return_value=missing):
                self.assertEqual(observation.observed_portfolio(root,health,time.time()),missing)

    def test_wal_support_file_absence_uses_only_fresh_canonical_owner_projection(self):
        from meme_machine.operational.supervisor import Supervisor
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);supervisor=Supervisor(root,offline=True)
            supervisor.initialize()
            self.addCleanup(supervisor.lock.close)
            supervisor.publish();supervisor.publish()
            health=json.loads((root/'health.json').read_text());now=time.time()
            health['portfolio_observation']['provider']='https://provider.invalid/private-secret'
            before=(root/'portfolio.sqlite').read_bytes()
            missing=dict(state='UNAVAILABLE',sqlite_code=sqlite3.SQLITE_CANTOPEN)
            with patch.object(observation,'database',return_value=missing):
                row=observation.observed_portfolio(root,health,now)
                self.assertEqual(row['epoch_id'],supervisor.epoch)
                self.assertEqual(row['reconciliation'],'PASS')
                self.assertEqual(row['marked_equity'],'500.00')
                self.assertEqual(row['reservations'],0)
                self.assertEqual(row['pending_deliveries'],0)
                self.assertNotIn('private-secret',json.dumps(row))
                self.assertEqual(observation.observed_portfolio(root,health,now+31),missing)
                health['portfolio_observation']['epoch_id']='other-epoch'
                self.assertEqual(observation.observed_portfolio(root,health,now),missing)
            self.assertEqual((root/'portfolio.sqlite').read_bytes(),before)

    def test_canonical_projection_cannot_hide_integrity_or_reconciliation_failure(self):
        missing=dict(state='FAIL_CLOSED',sqlite_code=sqlite3.SQLITE_CORRUPT,integrity_failure=True)
        with patch.object(observation,'database',return_value=missing):
            self.assertEqual(observation.observed_portfolio('/missing',{},0),missing)
        missing=dict(state='FAIL_CLOSED',reconciliation_failure=True)
        with patch.object(observation,'database',return_value=missing):
            self.assertEqual(observation.observed_portfolio('/missing',{},0),missing)

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
