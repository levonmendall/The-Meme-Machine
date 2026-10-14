"""Recording tests only: disposable real errors do not attribute the host fault."""
from concurrent.futures import ProcessPoolExecutor,ThreadPoolExecutor
from contextlib import closing,nullcontext
import json
import multiprocessing
import os
from pathlib import Path
import pickle
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from meme_machine.runtime import sqlite_failure
from meme_machine.runtime.sqlite_failure import connect,payload
from meme_machine.runtime.evidence_worker import failure_diagnostic


class RecorderWorkerConfigurationTests(unittest.TestCase):
    def test_diagnostic_opt_in_reaches_actual_source_environment_only(self):
        from meme_machine.operational.supervisor import Supervisor
        service=object.__new__(Supervisor)
        service.root=Path('/tmp/offline-recorder-configuration')
        service.epoch='paper-offline-recorder'
        service.offline=False
        settings={'MM_SQLITE_DIAGNOSTIC_REQUIRED':'1',
                  'MM_SQLITE_TERMINAL_RECORD_PATH':'/tmp/owned-terminal/source.txt'}
        with patch.dict(os.environ,settings,clear=True):
            source=service.environment('solana')
            for key,value in settings.items():self.assertEqual(source[key],value)
            for lane in ('pump','pons'):
                child=service.environment(lane)
                for key in settings:self.assertNotIn(key,child)
            service.offline=True
            for key in settings:self.assertNotIn(key,service.environment('solana'))
        service.offline=False
        with patch.dict(os.environ,{},clear=True):
            for key in settings:self.assertNotIn(key,service.environment('solana'))


def readonly_failure(path):
    with closing(connect(Path(path).as_uri()+'?mode=ro',uri=True,timeout=0,
            diagnostic_role='candidate_history_test')) as db:
        db.execute('INSERT INTO retained VALUES(?)',('secret-binding',))


def child_terminal_failure(path,terminal):
    from meme_machine.runtime import evidence_worker
    # Simulate a saturated ordinary output channel. The reserved record must
    # survive the child's actual uncaught SystemExit independently of stderr.
    sys.stderr=open(os.devnull,'w')
    os.environ['MM_SQLITE_TERMINAL_RECORD_PATH']=terminal
    with closing(connect(path,diagnostic_role='terminal_child_test',isolation_level=None)) as db:
        for _ in range(256):db.execute('BEGIN');db.execute('COMMIT')
    async def fails():readonly_failure(path)
    evidence_worker.main_async=fails
    evidence_worker.main()


class SQLiteFailureAttributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'retained.sqlite'
        with sqlite3.connect(self.path) as db:db.execute('CREATE TABLE retained(value)')

    def tearDown(self):self.tmp.cleanup()

    def assertEssential(self,error,phase):
        value=payload(error)
        self.assertTrue(value['recorder_valid'])
        self.assertEqual(value['operation'],phase)
        self.assertEqual(value['database'],str(self.path))
        self.assertIsInstance(value['connection_identity'],str)
        self.assertEqual(value['pid'],os.getpid())
        self.assertEqual(value['native_thread_id'],threading.get_native_id())
        self.assertEqual(value['database_inode'],self.path.stat().st_ino)
        self.assertEqual(value['database_device'],self.path.stat().st_dev)
        self.assertGreaterEqual(value['operation_seconds'],0)
        self.assertEqual(value['timeout_seconds'],0)
        self.assertEqual(value['busy_timeout_milliseconds'],0)
        return value

    def test_real_busy_begin_preserves_actual_connection_and_no_parameters(self):
        with closing(sqlite3.connect(self.path,isolation_level=None)) as blocker, \
                closing(connect(self.path,diagnostic_role='canonical_owner_test',timeout=0,isolation_level=None)) as db:
            blocker.execute('BEGIN IMMEDIATE')
            with self.assertRaises(sqlite3.OperationalError) as caught:db.execute('BEGIN IMMEDIATE')
            facts=self.assertEssential(caught.exception,'BEGIN')
            self.assertEqual(facts['sqlite_errorcode'],sqlite3.SQLITE_BUSY)
            self.assertEqual(facts['sqlite_errorname'],'SQLITE_BUSY')
            self.assertFalse(facts['in_transaction'])
            self.assertEqual(facts['connection_role'],'canonical_owner_test')
            self.assertNotIn('database is locked',failure_diagnostic(caught.exception))

    def test_real_busy_commit_keeps_original_transaction_before_rollback(self):
        with closing(sqlite3.connect(self.path,isolation_level=None)) as reader, \
                closing(connect(self.path,diagnostic_role='canonical_owner_test',timeout=0,isolation_level=None)) as writer:
            reader.execute('BEGIN');reader.execute('SELECT * FROM retained').fetchall()
            writer.execute('BEGIN IMMEDIATE')
            writer.execute('INSERT INTO retained VALUES(?)',('secret-binding',))
            with self.assertRaises(sqlite3.OperationalError) as caught:writer.execute('COMMIT')
            original=self.assertEssential(caught.exception,'COMMIT')
            self.assertTrue(original['in_transaction'])
            self.assertIsInstance(original['transaction_started_monotonic'],float)
            saved=json.dumps(original,sort_keys=True)
            writer.execute('ROLLBACK')
            self.assertEqual(json.dumps(payload(caught.exception),sort_keys=True),saved)
            self.assertNotIn('secret-binding',failure_diagnostic(caught.exception))

    def test_real_readonly_includes_mode_and_redacts_sql_error_and_bindings(self):
        with self.assertRaises(sqlite3.OperationalError) as caught:readonly_failure(str(self.path))
        facts=self.assertEssential(caught.exception,'INSERT')
        self.assertEqual(facts['opening_mode'],'ro')
        self.assertEqual(facts['sqlite_errorcode'],sqlite3.SQLITE_READONLY)
        self.assertNotIn('secret-binding',failure_diagnostic(caught.exception))
        self.assertNotIn('INSERT INTO',failure_diagnostic(caught.exception))

    def test_real_capture_read_busy_retains_capture_scope(self):
        from meme_machine.solana_history_delivery import capture
        with closing(sqlite3.connect(self.path,isolation_level=None)) as blocker, \
                closing(connect(self.path,diagnostic_role='canonical_read_test',timeout=0,isolation_level=None)) as db:
            blocker.execute('CREATE TABLE candidate_history_outbox(id)')
            blocker.execute('BEGIN EXCLUSIVE')
            life=SimpleNamespace(db=db,writer=SimpleNamespace(path=self.path))
            with self.assertRaises(sqlite3.OperationalError) as caught:capture(life)
            facts=self.assertEssential(caught.exception,'SELECT')
            self.assertEqual(facts['scope'],'candidate_delivery.capture')
            self.assertEqual(facts['origin']['module'],'meme_machine.solana_history_delivery')
            self.assertEqual(facts['origin']['function'],'capture')

    def test_connection_failure_records_before_optional_file_probe(self):
        missing=Path(self.tmp.name)/'missing.sqlite'
        with self.assertRaises(sqlite3.OperationalError) as caught:
            connect(missing.as_uri()+'?mode=rw',uri=True,timeout=0,diagnostic_role='canonical_checkpoint_test')
        facts=payload(caught.exception)
        self.assertEqual(facts['operation'],'canonical_checkpoint_test.open')
        self.assertEqual(facts['database'],str(missing))
        self.assertIsNone(facts['connection_identity'])
        self.assertEqual(facts['opening_mode'],'rw')
        self.assertEqual(facts['sqlite_errorcode'],sqlite3.SQLITE_CANTOPEN)

    def test_optional_open_file_identity_failure_does_not_replace_sqlite_error(self):
        with patch.object(sqlite_failure.Path,'stat',side_effect=PermissionError('private-probe-error')):
            with self.assertRaises(sqlite3.OperationalError) as caught:readonly_failure(str(self.path))
        self.assertEqual(payload(caught.exception)['sqlite_errorcode'],sqlite3.SQLITE_READONLY)
        self.assertNotIn('private-probe-error',failure_diagnostic(caught.exception))

    def test_recorder_failure_preserves_original_and_marks_attribution_invalid(self):
        with patch.object(sqlite_failure,'_facts',side_effect=OSError('private-recorder-error')):
            with self.assertRaises(sqlite3.OperationalError) as caught:readonly_failure(str(self.path))
        self.assertFalse(payload(caught.exception)['recorder_valid'])
        self.assertEqual(caught.exception.sqlite_errorcode,sqlite3.SQLITE_READONLY)
        self.assertNotIn('private-recorder-error',failure_diagnostic(caught.exception))

    def test_first_failure_survives_reannotation_and_cleanup_failure(self):
        with self.assertRaises(sqlite3.OperationalError) as caught:readonly_failure(str(self.path))
        error=caught.exception;saved=payload(error)
        sqlite_failure.annotate(error,{'database':'different','opening_mode':'rw'},'ROLLBACK',0)
        self.assertIs(payload(error),saved)
        with self.assertRaises(sqlite3.OperationalError) as terminal:
            try:raise error
            finally:
                with sqlite_failure.preserving_cleanup():raise OSError('private-cleanup-error')
        self.assertIs(terminal.exception,error)
        with self.assertRaises(OSError):
            with sqlite_failure.preserving_cleanup():raise OSError('new-cleanup-error')

    def test_thread_failure_records_executor_and_worker_reports_original(self):
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.assertRaises(sqlite3.OperationalError) as caught:executor.submit(readonly_failure,str(self.path)).result(timeout=5)
        facts=payload(caught.exception)
        self.assertNotEqual(facts['native_thread_id'],threading.get_native_id())
        report=failure_diagnostic(caught.exception)
        terminal=json.loads(report.split(':sqlite_failure=',1)[1])
        self.assertEqual(terminal['native_thread_id'],facts['native_thread_id'])
        self.assertEqual(terminal['reporter_native_thread_id'],threading.get_native_id())

    def test_child_error_survives_process_boundary_and_actual_main_reporting(self):
        with ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn')) as executor:
            with self.assertRaises(sqlite3.OperationalError) as caught:executor.submit(readonly_failure,str(self.path)).result(timeout=10)
        error=caught.exception
        self.assertNotEqual(payload(error)['pid'],os.getpid())
        self.assertEqual(payload(pickle.loads(pickle.dumps(error)))['pid'],payload(error)['pid'])
        from meme_machine.runtime import evidence_worker
        async def fails():raise error
        with patch.object(evidence_worker,'main_async',fails):
            with self.assertRaises(SystemExit) as terminal:evidence_worker.main()
        report=str(terminal.exception)
        self.assertIn('SQLITE_READONLY:8',report)
        self.assertIn('sqlite_failure=',report)
        self.assertNotIn('secret-binding',report)
        self.assertLess(len(report.encode()),sqlite_failure.MAX_TERMINAL_BYTES)

    def test_bounded_ring_does_not_exhaust_terminal_error_channel(self):
        with closing(connect(self.path,diagnostic_role='canonical_owner_test',timeout=0,isolation_level=None)) as db:
            for _ in range(512):db.execute('BEGIN');db.execute('COMMIT')
        self.assertLessEqual(len(sqlite_failure._ring),128)
        self.assertLess(len(json.dumps(list(sqlite_failure._ring)).encode()),sqlite_failure.MAX_RING_BYTES)
        with self.assertRaises(sqlite3.OperationalError) as caught:readonly_failure(str(self.path))
        self.assertTrue(payload(caught.exception)['recorder_valid'])
        self.assertLess(len(failure_diagnostic(caught.exception).encode()),sqlite_failure.MAX_TERMINAL_BYTES)

    def test_existing_connection_context_and_explicit_close_semantics(self):
        db=connect(self.path,diagnostic_role='candidate_history_test')
        with db as same:
            self.assertIs(same,db)
            db.execute('INSERT INTO retained VALUES(?)',('value',))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM retained').fetchone()[0],1)
        db.close()
        with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')

    def test_explicit_cursor_read_failure_records_connection(self):
        with closing(sqlite3.connect(self.path,isolation_level=None)) as blocker, \
                closing(connect(self.path,diagnostic_role='canonical_read_test',timeout=0,isolation_level=None)) as db:
            blocker.execute('BEGIN EXCLUSIVE')
            cursor=db.cursor()
            with self.assertRaises(sqlite3.OperationalError) as caught:cursor.execute('SELECT * FROM retained')
            facts=self.assertEssential(caught.exception,'SELECT')
            self.assertEqual(facts['connection_identity'],db._failure_metadata['connection_identity'])

    def test_context_manager_commit_busy_is_attributed(self):
        with closing(sqlite3.connect(self.path,isolation_level=None)) as reader, \
                closing(connect(self.path,diagnostic_role='canonical_owner_test',timeout=0)) as writer:
            reader.execute('BEGIN');reader.execute('SELECT * FROM retained').fetchall()
            with self.assertRaises(sqlite3.OperationalError) as caught:
                with writer:writer.execute('INSERT INTO retained VALUES(?)',('value',))
            self.assertEssential(caught.exception,'context_exit')
            self.assertEqual(caught.exception.sqlite_errorcode,sqlite3.SQLITE_BUSY)

    def test_bounded_terminal_across_four_attributed_causes(self):
        failures=[]
        for _ in range(4):
            try:readonly_failure(str(self.path))
            except sqlite3.OperationalError as error:failures.append(error)
        for newer,older in zip(failures,failures[1:]):newer.__cause__=older
        report=failure_diagnostic(failures[0])
        self.assertEqual(report.count('sqlite_failure='),4)
        self.assertLessEqual(len(report.encode()),sqlite_failure.MAX_TERMINAL_BYTES)

    def test_oversized_terminal_retains_original_native_codes(self):
        failures=[]
        for _ in range(4):
            try:readonly_failure(str(self.path))
            except sqlite3.OperationalError as error:failures.append(error)
        for newer,older in zip(failures,failures[1:]):newer.__cause__=older
        huge=dict(database='😀'*20000,recorder_valid=True)
        with patch.object(sqlite_failure,'payload',return_value=huge):
            report=failure_diagnostic(failures[0])
        self.assertLessEqual(len(report.encode()),sqlite_failure.MAX_TERMINAL_BYTES)
        self.assertEqual(report.count('SQLITE_READONLY:8'),4)
        self.assertIn('recorder_valid=false',report)

    def test_multibyte_path_bound_does_not_replace_connect_failure(self):
        original='😀'*2000
        with patch.object(sqlite_failure,'_path',return_value=original),patch.object(sqlite_failure,'_coverage_valid',True):
            missing=Path(self.tmp.name)/'missing.sqlite'
            with self.assertRaises(sqlite3.OperationalError) as caught:
                connect(missing.as_uri()+'?mode=rw',uri=True,timeout=0,diagnostic_role='canonical_checkpoint_test')
            facts=payload(caught.exception)
            self.assertEqual(facts['sqlite_errorcode'],sqlite3.SQLITE_CANTOPEN)
            self.assertTrue(facts['database_identity_truncated'])
            self.assertFalse(facts['recorder_valid'])
            self.assertLessEqual(len(facts['database'].encode()),1024)
            self.assertEqual(len(facts['configured_database_identity_sha256']),64)

    def test_checkpoint_busy_return_is_distinct_from_thrown_error(self):
        with closing(connect(self.path,diagnostic_role='canonical_checkpoint_test',timeout=0,isolation_level=None)) as writer, \
                closing(sqlite3.connect(self.path,isolation_level=None)) as reader:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('INSERT INTO retained VALUES(1)')
            reader.execute('BEGIN');reader.execute('SELECT * FROM retained').fetchall()
            writer.execute('INSERT INTO retained VALUES(2)')
            result=writer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            self.assertEqual(result[0],1)
            self.assertIs(sqlite_failure.checkpoint_result(writer,result),result)
            last=sqlite_failure._ring[-1]
            self.assertEqual(last['operation'],'checkpoint_return')
            self.assertEqual(last['busy'],1)
            self.assertNotIn('sqlite_errorcode',last)

    def test_required_coverage_status_is_bounded_and_normal_health_is_unchanged(self):
        from meme_machine.solana_evidence_service import ServiceState
        # Invoke the real publication method with offline writer/fence doubles.
        state=SimpleNamespace(writer=SimpleNamespace(transaction=nullcontext,transaction_metrics={}),
            storage_metrics={},maintenance_health=Mock(),fence=SimpleNamespace(health=Mock()))
        status=sqlite_failure.coverage_status()
        self.assertLessEqual(status['ring_upper_bound_bytes'],sqlite_failure.MAX_RING_BYTES)
        with patch.dict(os.environ,{'MM_SQLITE_DIAGNOSTIC_REQUIRED':'0'}):
            ServiceState.publish_health(state,{}, {}, {})
        self.assertNotIn('sqlite_failure_recorder',[call.args[0] for call in state.fence.health.call_args_list])
        state.fence.health.reset_mock()
        with patch.dict(os.environ,{'MM_SQLITE_DIAGNOSTIC_REQUIRED':'1'}),patch.object(sqlite_failure,'_coverage_valid',False):
            ServiceState.publish_health(state,{}, {}, {})
        records={call.args[0]:call.args[1] for call in state.fence.health.call_args_list}
        self.assertFalse(records['sqlite_failure_recorder']['recorder_valid'])

    def test_child_terminal_record_is_reserved_durable_bounded_and_non_overwriting(self):
        terminal=Path(self.tmp.name)/'terminal.log'
        child=multiprocessing.get_context('spawn').Process(target=child_terminal_failure,args=(str(self.path),str(terminal)))
        child.start();child.join(timeout=10)
        try:
            self.assertFalse(child.is_alive())
            self.assertEqual(child.exitcode,1)
            report=terminal.read_text()
            self.assertIn('SQLITE_READONLY:8',report)
            self.assertIn('sqlite_failure=',report)
            self.assertNotIn('secret-binding',report)
            self.assertLessEqual(terminal.stat().st_size,sqlite_failure.MAX_TERMINAL_BYTES)
            self.assertEqual(terminal.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):sqlite_failure.write_terminal_record(terminal,'replacement')
            self.assertEqual(terminal.read_text(),report)
            self.assertFalse(list(Path(self.tmp.name).glob('.sqlite-terminal-*.tmp')))
        finally:
            if child.is_alive():child.terminate();child.join(timeout=5)

    def test_terminal_write_failure_cannot_mask_original_worker_error(self):
        from meme_machine.runtime import evidence_worker
        async def fails():readonly_failure(str(self.path))
        terminal=Path(self.tmp.name)/'terminal.log'
        with patch.dict(os.environ,{'MM_SQLITE_TERMINAL_RECORD_PATH':str(terminal)}), \
                patch.object(sqlite_failure,'write_terminal_record',side_effect=OSError('private-terminal-error')), \
                patch.object(evidence_worker,'main_async',fails):
            with self.assertRaises(SystemExit) as caught:evidence_worker.main()
        report=str(caught.exception)
        self.assertIn('SQLITE_READONLY:8',report)
        self.assertIn('terminal_record_write_failed:recorder_valid=false',report)
        self.assertNotIn('private-terminal-error',report)

    def test_default_worker_reporting_does_not_write_a_terminal_file(self):
        from meme_machine.runtime import evidence_worker
        async def fails():readonly_failure(str(self.path))
        with patch.dict(os.environ,{'MM_SQLITE_TERMINAL_RECORD_PATH':''}), \
                patch.object(sqlite_failure,'write_terminal_record') as recorder, \
                patch.object(evidence_worker,'main_async',fails):
            with self.assertRaises(SystemExit):evidence_worker.main()
        recorder.assert_not_called()

    def test_owned_context_survives_existing_redacting_wrapper(self):
        from meme_machine.runtime.evidence_worker import DeliveredRPCError
        with self.assertRaises(sqlite3.OperationalError) as caught:readonly_failure(str(self.path))
        wrapped=sqlite_failure.carry(caught.exception,DeliveredRPCError('repair_response_unavailable',{}))
        self.assertEqual(payload(wrapped)['sqlite_errorcode'],sqlite3.SQLITE_READONLY)
        self.assertIn('sqlite_failure=',failure_diagnostic(wrapped))
        self.assertNotIn('secret-binding',failure_diagnostic(wrapped))

    def test_candidate_transaction_cleanup_cannot_replace_first_error(self):
        from meme_machine.runtime.candidate_history import CandidateHistory
        history=CandidateHistory.__new__(CandidateHistory)
        original=sqlite3.OperationalError('private-original')
        original.sqlite_errorcode=sqlite3.SQLITE_READONLY;original.sqlite_errorname='SQLITE_READONLY'
        db=Mock();db.in_transaction=False
        def execute(sql):
            if sql=='BEGIN IMMEDIATE':db.in_transaction=True
            if sql=='ROLLBACK':raise OSError('private-cleanup')
        db.execute.side_effect=execute;history.db=db
        with self.assertRaises(sqlite3.OperationalError) as caught:
            with history.transaction():raise original
        self.assertIs(caught.exception,original)
