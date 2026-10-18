"""Private detached run lifetime under real retained actor locks; no providers."""
import fcntl
import os
import pickle
import threading
import time
import unittest

from meme_machine.operational import normal_boot as boot
from meme_machine.operational import normal_boot_record as wire
from meme_machine.operational import normal_source_recovery as target_module
from meme_machine.operational import qualified_source_program_recovery as qualified
from tests import test_normal_source_recovery as original


class QualifiedProgramRunTests(unittest.TestCase):
    def setUp(self):
        self.source=original.QualifiedRecoveryTargetTests();self.source.setUp()
        self.addCleanup(self.source.doCleanups);self.source.failed_source()
        self.context,self.databases=self.source.context()
        target=target_module.derive_qualified_recovery_target(self.context)
        self.pins={self.source.root/name:wire.file_identity((self.source.root/name).lstat()) for name in boot.LOCKS}
        self.valid=True;self.cancelled=False
        request={key:self.source.fixture.record[key] for key in
            ('request_id','application_commit','application_tree','administration_commit')}
        request.update({key:self.context.ledger()[key] for key in ('epoch_id','inception_sha256')})
        self.run=qualified.detach_qualified_program_run(target,validate_fences=self.guard,
            rejoin=self.rejoin,deadline=time.monotonic()+120,request=request,cancelled=lambda:self.cancelled)
        self.addCleanup(self.run.close)
        self.context.close()
        for db in self.databases.values():db.close()

    def guard(self):
        if not self.valid:raise ValueError('actual_guard_lost')
        for path,identity in self.pins.items():
            self.assertEqual(wire.file_identity(path.lstat()),identity)
            with path.open('rb') as handle:
                with self.assertRaises(BlockingIOError):fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def rejoin(self):
        context,databases=self.source.context(real_locks=False)
        try:return target_module.derive_qualified_recovery_target(context).value()
        finally:
            context.close()
            for db in databases.values():db.close()

    def test_short_sql_scope_closes_but_actual_guarded_rejoin_and_fixed_selection_remain(self):
        self.assertTrue(self.context._closed);self.run.check()
        self.assertEqual(qualified.selection(self.run),('program:pumpswap',100,123))
        self.assertEqual(self.run.rejoins,1)
        with self.assertRaises(TypeError):pickle.dumps(self.run)
        with self.assertRaises(wire.NormalBootUnavailable):self.run.deadline=time.monotonic()+999
        with self.assertRaises(wire.NormalBootUnavailable):self.run._deadline=time.monotonic()+999
        self.assertEqual(self.run.request['epoch_id'],self.source.fixture.record['boot_eligibility']['epoch_id'])
        detached=self.run.request;detached['epoch_id']='changed'
        self.assertNotEqual(self.run.request['epoch_id'],'changed')

    def test_lost_actual_guard_cancel_or_foreign_owner_never_admits_work(self):
        errors=[]
        def foreign():
            try:self.run.check()
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=foreign);worker.start();worker.join(2)
        self.assertEqual(len(errors),1);self.assertIn('run_owner',str(errors[0]))
        self.valid=False
        with self.assertRaisesRegex(ValueError,'actual_guard_lost'):self.run.check()
        self.valid=True;self.cancelled=True
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'run_cancelled'):self.run.check()

    def test_original_provider_closing_reserve_cannot_be_renewed(self):
        from unittest.mock import patch
        boundary=self.run.deadline-qualified.PROVIDER_CLOSING_SECONDS
        with patch.object(qualified.time,'monotonic',return_value=boundary):
            with self.assertRaisesRegex(wire.NormalBootUnavailable,'provider_closing_reserve'):
                self.run.before_provider()
        with patch.object(qualified.time,'monotonic',return_value=self.run.deadline):
            with self.assertRaisesRegex(wire.NormalBootUnavailable,'run_deadline'):self.run.guard()
        self.run.close()
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'run_owner'):self.run.guard()
