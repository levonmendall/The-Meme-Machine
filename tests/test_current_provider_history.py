"""Genuine current usage is mutable; the original restore stock is not reseeded."""
from contextlib import closing,contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational.bounded_provider import Budget
from meme_machine.operational.current_provider_history import current_provider_book
from meme_machine.shared_capital.model import CapitalError


class CurrentProviderHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name)/'shared/provider-usage.continuous.sqlite'
        source=Path(__file__).resolve().parents[1]
        self.profile=json.loads((source/'operational/pump-first-release/deployment/'
            'paper-continuous.four-regime.json').read_text())
        self.budget=Budget.create(self.path,continuous=self.profile)
        self.owner='f'*32;self.budget.publish_readiness(False,self.owner)
        self.state=dict(runtime_admission=dict(mode='OBSERVATION',run_id=self.owner,
            provider_db=str(self.path),continuous_provider_db=str(self.path)))

    @contextmanager
    def snapshot(self):
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,isolation_level=None)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN');yield db

    def inspect(self,db=None,**changes):
        arguments=dict(profile=self.profile,configured_path=str(self.path),expected_path=self.path)
        arguments.update(changes)
        with (patch.object(Budget,'__init__',side_effect=AssertionError('writer constructor')),
                patch.object(Budget,'create',side_effect=AssertionError('replacement book')),
                patch.object(Budget,'reap_orphans',side_effect=AssertionError('reaping'))):
            if db is not None:return current_provider_book(db,self.state,**arguments)
            with self.snapshot() as reader:return current_provider_book(reader,self.state,**arguments)

    def test_original_same_path_usage_can_grow_without_reusing_restore_stock(self):
        before=self.inspect();self.budget.change(dict(rpc_cu=7,http_attempts=1))
        self.budget.publish_readiness(False,self.owner,reason='offline retained control')
        with self.snapshot() as db:
            changes=db.total_changes;after=self.inspect(db)
            self.assertEqual(db.total_changes,changes)
        self.assertTrue(after['current_book_verified'])
        self.assertNotEqual(after['ledger_snapshot_sha256'],before['ledger_snapshot_sha256'])
        self.assertEqual(after['counters']['rpc_cu'],7)
        self.assertTrue(after['readiness_owner_matches_previous_run'])
        self.assertFalse(after['historical_provider_lineage_verified'])
        self.assertEqual((after['authoritative_writes'],after['provider_requests']),(0,0))

    def test_changed_path_or_ownerless_admission_refuses_without_dereferencing_old_path(self):
        for key in ('provider_db','continuous_provider_db','run_id'):
            with self.subTest(key=key):
                original=self.state['runtime_admission'][key]
                self.state['runtime_admission'][key]='/PRIVATE_DIFFERENT_PATH' if key!='run_id' else ''
                try:
                    with self.assertRaisesRegex(ValueError,'current_provider_book_'):
                        self.inspect()
                finally:self.state['runtime_admission'][key]=original
        with self.assertRaisesRegex(ValueError,'configured_path'):
            self.inspect(configured_path='/PRIVATE_DIFFERENT_PATH')

    def test_original_profile_clock_counter_and_schema_failures_refuse(self):
        for key,value in (('resource_configuration','{}'),('continuous_envelope','{}'),
                ('started','nan'),('started_wall','-1'),('boot',''),('rpc_cu','-1'),
                ('new_risk_ready','unknown')):
            with self.subTest(key=key),closing(sqlite3.connect(self.path)) as db:
                original=db.execute('SELECT value FROM run WHERE key=?',(key,)).fetchone()[0]
                db.execute('UPDATE run SET value=? WHERE key=?',(value,key));db.commit()
                try:
                    with self.assertRaises((ValueError,KeyError,CapitalError)):self.inspect()
                finally:db.execute('UPDATE run SET value=? WHERE key=?',(original,key));db.commit()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('ALTER TABLE usage_hours ADD COLUMN unexpected INTEGER');db.commit()
        with self.assertRaisesRegex(ValueError,'usage_schema'):self.inspect()

    def test_bootstrap_pacing_key_does_not_add_a_continuous_guard(self):
        for stored,expected in (('{}',False),('not-json',None)):
            with self.subTest(stored=stored),closing(sqlite3.connect(self.path)) as db:
                db.execute("UPDATE run SET value=? WHERE key='physical_http_start_intervals'",(stored,));db.commit()
                value=self.inspect()
                self.assertTrue(value['current_book_verified'])
                self.assertIs(value['stored_bootstrap_pacing_matches_profile'],expected)

    def test_open_consumed_receipt_is_reported_even_with_zero_reservations(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('INSERT INTO http_receipts VALUES(?,?,?,?)',('retained',0,0,'original owner'))
            db.commit()
        value=self.inspect()
        self.assertTrue(value['current_book_verified'])
        self.assertEqual(value['counters']['http_reserved'],0)
        self.assertEqual(value['transports']['http_receipts']['open_rows'],1)
        self.assertTrue(value['ledger_funding_closed'])

    def test_unknown_readiness_owner_and_failure_remain_observations(self):
        self.budget.publish_readiness(False,'other-owner')
        self.budget.change(reason='original durable fault',check=False)
        value=self.inspect()
        self.assertFalse(value['readiness_owner_matches_previous_run'])
        self.assertTrue(value['ledger_failure_recorded'])
        self.assertFalse(value['historical_provider_lineage_verified'])

    def test_active_snapshot_required_and_restart_observes_latest_original_counters(self):
        with closing(sqlite3.connect(self.path)) as db:
            with self.assertRaisesRegex(ValueError,'readonly_snapshot_required'):self.inspect(db)
            db.execute('PRAGMA query_only=ON')
            with self.assertRaisesRegex(ValueError,'readonly_snapshot_required'):self.inspect(db)
        with self.snapshot() as first:
            before=self.inspect(first)
            self.budget.change(dict(native_bytes=17))
            self.assertEqual(self.inspect(first),before)
        after=self.inspect()
        self.assertEqual(after['counters']['native_bytes'],17)
        self.assertNotEqual(before['ledger_snapshot_sha256'],after['ledger_snapshot_sha256'])
