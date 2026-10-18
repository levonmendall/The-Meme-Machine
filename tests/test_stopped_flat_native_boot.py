"""Real native terminal/replay inputs; no providers or production state."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.runtime.native_flat_boot import FlatNativeBootInputs, validate_stopped_flat_boot_inputs
from meme_machine.runtime.native_restore_context import NativeDependencyUnavailable
from tests import test_stopped_native_restore_context as original


class StoppedFlatNativeBootTests(unittest.TestCase):
    setUp = original.StoppedNativeReadContextTests.setUp
    context = original.StoppedNativeReadContextTests.context
    native_books = original.StoppedNativeReadContextTests.native_books
    native_terminals = original.StoppedNativeReadContextTests.native_terminals

    def original_context(self, *, terminals=True):
        from meme_machine.runtime.native_restore_closure import PLANE
        from meme_machine.runtime.robinhood.plane import Plane
        paths = self.native_books()
        if terminals:self.native_terminals(paths)
        # Earn a genuine stopped owner identity from a real disposable child.
        code = ('import sys;from meme_machine.runtime.robinhood.plane import process_identity;'
                'print(process_identity(),flush=True);sys.stdin.buffer.read(1)')
        child = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        identity = child.stdout.readline().strip()
        self.assertEqual(len(identity.split(':')), 3)
        child.stdin.close();child.wait(timeout=5)
        child.stdout.close();child.stderr.close()
        self.assertEqual(child.returncode, 0)
        plane = Plane(self.root/PLANE)
        saved = plane.checkpoint_read('pons_cohort')
        saved['owner'] = identity
        plane.checkpoint('pons_cohort', saved);plane.close()
        context, snapshots = self.context(extra=paths)
        boot, pid, start = identity.split(':')
        def dead_owner(value):
            if value != identity:return False
            # The retained identity is known; unknown permission/parse errors
            # cannot become evidence that another owner's PID is dead.
            if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot:return False
            try:raw = Path('/proc/'+pid+'/stat').read_text()
            except FileNotFoundError:return True
            except OSError:return False
            return raw.rsplit(')',1)[1].split()[19] != start
        context._validate_owner = dead_owner
        return context, snapshots

    def test_real_migrated_epoch_and_all_four_native_terminals_earn_only_flat_inputs(self):
        context, snapshots = self.original_context()
        before = self.writer.ledger()
        changes = [db.total_changes for db in snapshots.values()]
        with patch('sqlite3.connect', side_effect=AssertionError('fallback open')):
            value = validate_stopped_flat_boot_inputs(context).value()
        self.assertEqual(value['epoch_id'],before['epoch_id'])
        self.assertEqual(before['initial_capital'],'1000.00')
        self.assertTrue(value['native_flat_inputs_verified'])
        self.assertEqual(len(value['four_regimes']),4)
        for name in ('boot_authority','funding_authority','safe_for_normal',
                'current_native_protection_verified','historical_handler_disposition_verified',
                'historical_drain_reclassified','complete_discovery_closure'):
            self.assertIs(value[name],False,name)
        self.assertEqual(changes,[db.total_changes for db in snapshots.values()])
        self.assertEqual(self.writer.ledger(),before)

    def test_inspection_dictionary_or_manual_record_cannot_issue_native_inputs(self):
        with self.assertRaisesRegex(NativeDependencyUnavailable,'read_context_required'):
            validate_stopped_flat_boot_inputs(dict(native_flat_inputs_verified=True))
        with self.assertRaisesRegex(NativeDependencyUnavailable,'issuer'):
            FlatNativeBootInputs(None,'a'*64,{})

    def test_missing_configured_native_book_refuses_not_smaller_population(self):
        from meme_machine.runtime.native_restore_closure import PAPERS
        context, _ = self.original_context(terminals=False)
        del context._databases[self.root/PAPERS['pump_survivor']]
        with self.assertRaisesRegex(NativeDependencyUnavailable,'configured_dependency_missing'):
            validate_stopped_flat_boot_inputs(context)

    def test_missing_terminal_receipt_preserves_original_refusal(self):
        from meme_machine.runtime.native_restore_closure import PLANE
        from meme_machine.runtime.journal import canonical
        context, snapshots = self.original_context()
        for db in snapshots.values():db.rollback()
        import sqlite3
        with sqlite3.connect(self.root/PLANE) as db:
            saved = json.loads(db.execute("SELECT body FROM runtime WHERE key='pons_cohort'").fetchone()[0])
            saved['result']['lifecycles'] = []
            db.execute("UPDATE runtime SET body=? WHERE key='pons_cohort'",(canonical(saved),))
        for db in snapshots.values():db.execute('BEGIN')
        with self.assertRaisesRegex(NativeDependencyUnavailable,'controller_continuation_required'):
            validate_stopped_flat_boot_inputs(context)

    def test_cancelled_cold_replay_and_deadline_restore_original_context_hook(self):
        context, _ = self.original_context(terminals=False)
        before = context._check_owner_deadline
        with self.assertRaisesRegex(NativeDependencyUnavailable,'cancelled'):
            validate_stopped_flat_boot_inputs(context,cancelled=lambda:True)
        self.assertEqual(context._check_owner_deadline,before)
        context.deadline = time.monotonic()-1
        with self.assertRaisesRegex(TimeoutError,'native_restore_deadline'):
            validate_stopped_flat_boot_inputs(context)

    def test_fenced_generation_loss_and_foreign_thread_refuse_detached_result(self):
        context, _ = self.original_context(terminals=False)
        proof = validate_stopped_flat_boot_inputs(context)
        errors = []
        worker = threading.Thread(target=lambda:self._foreign(proof,errors))
        worker.start();worker.join(2)
        self.assertEqual(len(errors),1)
        self.assertIn('owner',str(errors[0]))
        self.boundary_valid = False
        with self.assertRaisesRegex(NativeDependencyUnavailable,'snapshot_changed'):
            proof.value()

    def test_real_original_path_inode_replacement_invalidates_issued_inputs(self):
        context, _ = self.original_context(terminals=False)
        path = self.root/'shared-capital.sqlite'
        info = path.stat()
        original_boundary = context._validate_snapshot
        context._validate_snapshot = lambda: original_boundary() and (
            path.stat().st_dev,path.stat().st_ino) == (info.st_dev,info.st_ino)
        proof = validate_stopped_flat_boot_inputs(context)
        raw = path.read_bytes();path.rename(path.with_suffix('.old'))
        path.write_bytes(raw)
        with self.assertRaisesRegex(NativeDependencyUnavailable,'snapshot_changed'):
            proof.value()

    def test_actual_connection_generation_replacement_and_post_issue_cancel_refuse(self):
        import sqlite3
        context, _ = self.original_context(terminals=False)
        stopped = threading.Event()
        proof = validate_stopped_flat_boot_inputs(context,cancelled=stopped.is_set)
        stopped.set()
        with self.assertRaisesRegex(NativeDependencyUnavailable,'cancelled'):proof.value()
        stopped.clear()
        path = self.root/'shared-capital.sqlite'
        replacement = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,isolation_level=None)
        self.addCleanup(replacement.close)
        replacement.execute('PRAGMA query_only=ON');replacement.execute('BEGIN')
        context._databases[path] = replacement
        with self.assertRaisesRegex(NativeDependencyUnavailable,'generation_changed'):proof.value()

    def test_cancellation_during_original_full_replay_is_not_deferred_until_afterward(self):
        from meme_machine.shared_capital.runtime import RuntimeCapital
        self.writer.command('flat-boot-more-real-events','runtime_publish',{},self.now)
        context, _ = self.original_context(terminals=False)
        stopped = threading.Event();applied = []
        original_apply = RuntimeCapital._apply
        def apply(reader,state,event):
            applied.append(event['operation_id'])
            result = original_apply(reader,state,event)
            stopped.set()
            return result
        with patch.object(RuntimeCapital,'_apply',apply):
            with self.assertRaisesRegex(NativeDependencyUnavailable,'cancelled'):
                validate_stopped_flat_boot_inputs(context,cancelled=stopped.is_set)
        self.assertEqual(len(applied),1)

    @staticmethod
    def _foreign(proof,errors):
        try:proof.value()
        except Exception as error:errors.append(error)
