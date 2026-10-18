"""Real private source child, failed callbacks/native FULL metadata and RO replay.

Protected root/unit/native-clock acquisition is the original IPC fixture's
explicit simulated premise. Process death, advisory locks, SQLite replay and
source registry/handler/gap/control joins are genuine. No provider is contacted.
"""
from contextlib import ExitStack,closing
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pickle
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.operational import normal_boot as boot
from meme_machine.operational import normal_boot_record as wire
from meme_machine.operational import normal_source_boot as source
from meme_machine.operational import normal_source_recovery as recovery
from tests import test_normal_source_boot as fixtures
from tests.test_normal_boot_context import physical_hash

CHILD=r'''
import asyncio,json,os,sys,time
from types import SimpleNamespace
from unittest.mock import patch
from operational.tests import network_guard
network_guard()
from meme_machine.operational import normal_boot as boot,normal_source_boot as source
fixture=json.loads(sys.stdin.readline());locator,record=fixture['locator'],fixture['record']
fields='MainPID='+str(record['supervisor']['pid'])+'\nInvocationID='+record['supervisor']['invocation_id']+'\nActiveState=active\n'
try:
    with patch.object(source,'_read_record',return_value=(locator,record)), \
         patch.object(source,'_clock_sha256',return_value='e'*64), \
         patch.object(boot,'_source_identity',return_value=(record['application_commit'],record['application_tree'])), \
         patch.object(source.subprocess,'run',return_value=SimpleNamespace(stdout=fields)):
        cap=source.accept_source_launch(int(sys.argv[1]))
    sys.stdin.readline() # actual parent finishes its original bind first
    from pathlib import Path
    from meme_machine.solana_evidence_service import ServiceState
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from meme_machine.solana_selective_source import SelectiveSource,install
    from meme_machine.operational.normal_source_registry import NativeSourceRegistry
    from meme_machine.solana_source_drain import preserve_handlers,preserve_control_recovery
    from meme_machine.solana_selective_runtime import CONTROL
    from meme_machine.solana_candidate_join import CandidateTransactionJoin
    from meme_machine.yellowstone import geyser_pb2 as pb
    state=ServiceState(Path(cap.identity()['root'])/'shared/solana-evidence.sqlite',
        AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline_fixture_only'))
    try:
        history=install(state)
        native=SelectiveSource(SimpleNamespace(credential='offline',identity=state.fence.endpoint_identity),
            None,normal_generation=cap)
        cap.begin(state,native.drain_snapshot());registry=NativeSourceRegistry(state,cap)
        cap._registry=registry;history._normal_source_registry=registry
        scopes=[('1'*32,'2'*32,'rolling','program:pumpswap',123),
            ('3'*32,'4'*32,'control',CONTROL,124),('5'*32,'6'*32,'scout','scout:pump',None)]
        async def interrupted(stream,session,scope,slot):
            async def handler(*args):raise ValueError('offline_failed_callback')
            handler.source_session=session;handler.source_scopes=(scope,)
            frame=pb.SubscribeUpdate(block_meta=pb.SubscribeUpdateBlockMeta(slot=slot))
            try:await native.handle_native(handler,frame,frame.ByteSize(),time.time(),stream,'shared')
            except ValueError:pass
        for stream,session,plane,scope,slot in scopes:
            registry.open(state,stream=stream,session=session,plane=plane,transport='yellowstone',
                scopes=[scope],lower_slot=100,filter_sha256='a'*64)
            if slot is not None:asyncio.run(interrupted(stream,session,scope,slot))
            registry.stopped(state,stream)
            with state.writer.transaction():
                if plane=='control':
                    retained=preserve_handlers(state,native.handlers,native.handlers.pending(session),
                        dict(kind='CONTROL_REPLAY',**preserve_control_recovery(state,100,124)))
                elif plane=='rolling':
                    history.gap(scope,100,None,'candidate_live_disconnect_or_filter_rebuild')
                    gap=state.writer.db.execute('SELECT last_insert_rowid()').fetchone()[0]
                    retained=preserve_handlers(state,native.handlers,native.handlers.pending(session),
                        dict(kind='CANDIDATE_GAPS',gap_ids=[gap]))
                else:retained=[]
                native.handlers.preserved(retained)
                join=CandidateTransactionJoin({},set(),filtered_from_slot=100)
                history._observation(None,'control_session_drain' if plane=='control' else 'source_session_drain',
                    dict(session=session,**join.diagnostic(),replay_from_slot=100,
                        handler_dispositions=retained,complete_history_claim=False))
                registry.closed(state,session,state.writer.db.execute('SELECT last_insert_rowid()').fetchone()[0])
        native.source_drain.update(state='RECOVERY_REQUIRED',terminal=True,closed_sessions=3)
        if os.environ.get('QUALIFIED_TEST_CRASH')!='1':
            body=native.drain_snapshot()
            with state.writer.transaction():
                body['pending_history']=state.writer.db.execute(
                    'SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0]
                body['pending_proofs']=state.writer.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0]
                cap.publish(state,body)
        print(json.dumps(dict(ready=True,generation=cap.generation)),flush=True)
        sys.stdin.readline()
        if os.environ.get('QUALIFIED_TEST_CRASH')=='1':os._exit(17)
    finally:state.close()
except BaseException as error:
    print(type(error).__name__+':'+str(error),file=sys.stderr,flush=True);raise SystemExit(2)
'''


class QualifiedRecoveryTargetTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NativeSourceLaunchTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.case.root;self.source_path=self.root/'shared/solana-evidence.sqlite'
        self.enterContext(patch.dict(os.environ,
            MM_SOLANA_READ_RPC_URL='https://solana-mainnet.g.alchemy.com/v2/offline_fixture_only'))
        self.enterContext(patch.object(source,'_clock_sha256',return_value='e'*64))
        self.enterContext(patch.object(wire,'_protected_bytes',side_effect=self.protected))
        self.record_raw=wire.canonical(self.fixture.record)
        self.raw_hash=self.fixture.record['boot_eligibility']['source_inputs']['source_drain']['sha256']

    def protected(self,path,maximum):
        self.assertEqual(path,wire.OPERATIONS/self.fixture.record['request_id']/'normal-launch.json')
        self.assertLessEqual(len(self.record_raw),maximum)
        return self.record_raw,None

    def failed_source(self,*,crash=False,alive=False):
        channel=source.SourceLaunch(self.fixture.context)
        with patch.object(fixtures,'CHILD',CHILD),patch.dict(os.environ,QUALIFIED_TEST_CRASH='1' if crash else '0'):
            child=self.fixture.launch(channel)
        self.identity=channel.bind(child,deadline=time.monotonic()+5)
        child.stdin.write('begin actual callbacks\n');child.stdin.flush()
        raw=child.stdout.readline()
        if not raw:
            child.wait(timeout=5)
            self.fail('actual_source_child_failed: '+child.stderr.read())
        self.assertTrue(json.loads(raw)['ready'])
        if not alive:
            child.stdin.write('finish\n');child.stdin.flush();child.stdin.close()
            self.assertEqual(child.wait(timeout=5),17 if crash else 0,child.stderr.read())
        return child

    def context(self,*,real_locks=True,authenticate=True):
        stack=self.enterContext(ExitStack())
        held=[]
        if real_locks:
            for relative in boot.LOCKS[1:]:
                fd=os.open(self.root/relative,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
                stack.callback(os.close,fd);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                held.append((self.root/relative,fd,wire.file_identity(os.fstat(fd))))
        context,databases=self.fixture.case.case.context(extra=[self.source_path])
        # Acquire the actual schema/read snapshot before the fixture collector
        # records its physical boundary. A crashed SQLite writer may leave a
        # WAL-index that a first ordinary host reader initializes. This is not
        # a production read-only mount or permission bypass claim.
        for db in databases.values():db.execute('SELECT name FROM sqlite_master LIMIT 1').fetchone()
        self.addCleanup(lambda:context.close() if not context._closed and self.boundary_valid else None)
        physical=physical_hash(self.root);self.boundary_valid=True
        def guard():
            return self.boundary_valid and physical_hash(self.root)==physical and all(
                wire.file_identity(path.lstat())==before==wire.file_identity(os.fstat(fd))
                for path,fd,before in held)
        context._validate_snapshot=guard
        if authenticate:context.authenticate_authority()
        return context,databases

    def test_real_private_failed_source_full_replay_and_underlying_joins_issue_no_completion(self):
        self.failed_source();context,databases=self.context();source_db=databases[self.source_path]
        old=source_db.execute('SELECT value FROM service_health WHERE key=\'source_drain\'').fetchone()[0]
        before=[db.total_changes for db in databases.values()]
        with patch('sqlite3.connect',side_effect=AssertionError('fallback open')):
            target=recovery.derive_qualified_recovery_target(context)
            value=target.value();self.assertIs(recovery.verify_qualified_recovery_target(target),target)
        self.assertEqual(value['registered_sessions'],3);self.assertEqual(len(value['handlers']),2)
        self.assertEqual(value['retained_session_closures'],3)
        self.assertEqual({row['kind'] for row in value['obligations']},
            {'CONTROL_METADATA','SCOUT_NOMINATION_HISTORY_UNPROVED','CANONICAL_INTERVAL_DELIVERY_AND_PROOF',
             'NATIVE_GAP','RETAINED_CONTROL_REPLAY'})
        self.assertEqual(value['original_unknown_historical_handlers'],2)
        self.assertEqual(value['current_control_prerequisite']['upper_slot'],124)
        self.assertEqual(hashlib.sha256(old.encode()).hexdigest(),self.raw_hash)
        self.assertEqual(before,[db.total_changes for db in databases.values()])
        self.assertIsNone(value['authenticated_upper']);self.assertTrue(value['fresh_authenticated_upper_required'])
        for name in ('recovery_complete','funding_authority','safe_for_normal','original_callback_completion',
                'historical_handler_disposition_verified','native_endpoint_completion_verified'):
            self.assertIs(value[name],False)
        value['generation']='changed';self.assertEqual(target.value()['generation'],self.identity['generation'])
        with self.assertRaises(TypeError):pickle.dumps(target)
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'private_issuer'):
            recovery.QualifiedSourceRecoveryTarget(context,{})

    def test_genuine_crash_retains_partial_handler_population_and_unknown_upper(self):
        self.failed_source(crash=True);context,_=self.context()
        value=recovery.derive_qualified_recovery_target(context).value()
        self.assertFalse(value['terminal_census_retained'])
        self.assertEqual(value['handler_population'],'UNKNOWN_CRASH_TAIL')
        self.assertEqual(value['queue_accounting'],'UNKNOWN_CRASH_TAIL')
        self.assertEqual(len(value['handlers']),2)
        self.assertTrue(any(row['retained_upper_slot'] is None for row in value['obligations']))
        self.assertFalse(value['recovery_complete'])

    def test_actual_live_producer_lock_and_prior_kernel_owner_refuse(self):
        child=self.failed_source(alive=True)
        with self.assertRaises(BlockingIOError):self.context()
        context,_=self.context(real_locks=False)
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'owner_unverified'):
            recovery.derive_qualified_recovery_target(context)
        # The refused live-owner scope must close before that actual owner
        # changes its WAL/support files while shutting down.
        context.close()
        child.stdin.write('finish\n');child.stdin.flush();child.stdin.close();child.wait(timeout=5)

    def test_original_replay_epoch_endpoint_native_clock_and_prior_record_mismatches_refuse(self):
        self.failed_source();context,_=self.context(authenticate=False)
        with self.assertRaisesRegex(ValueError,'authority_not_authenticated'):
            recovery.derive_qualified_recovery_target(context)
        context.authenticate_authority()
        # Isolate the new association checks after the genuine original full
        # replay: a crossed read-port return cannot issue a target.
        for name in ('epoch_id','inception_sha256'):
            crossed=context.ledger();crossed[name]='foreign'
            with patch.object(context,'ledger',return_value=crossed):
                with self.assertRaisesRegex(wire.NormalBootUnavailable,'recovery_target_epoch'):
                    recovery.derive_qualified_recovery_target(context)
        with patch.dict(os.environ,MM_SOLANA_READ_RPC_URL='https://solana-mainnet.g.alchemy.com/v2/foreign_fixture'):
            with self.assertRaisesRegex(wire.NormalBootUnavailable,'endpoint'):
                recovery.derive_qualified_recovery_target(context)
        with patch.object(source,'_clock_sha256',return_value='f'*64):
            with self.assertRaisesRegex(wire.NormalBootUnavailable,'clock'):
                recovery.derive_qualified_recovery_target(context)
        self.record_raw=self.record_raw+b' '
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'root_record'):
            recovery.derive_qualified_recovery_target(context)

    def test_complete_registry_membership_closure_and_real_gap_are_not_skippable(self):
        self.failed_source()
        with closing(sqlite3.connect(self.source_path)) as db:
            db.execute("DELETE FROM native_source_sessions WHERE id=?",('5'*32,));db.commit()
        context,_=self.context()
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'population_changed'):
            recovery.derive_qualified_recovery_target(context)

    def test_original_closed_observation_must_still_exist(self):
        self.failed_source()
        with closing(sqlite3.connect(self.source_path)) as db:
            row=db.execute('SELECT body FROM native_source_sessions WHERE id=?',('1'*32,)).fetchone()
            reference=json.loads(row[0])['closure']['observation_id']
            db.execute('UPDATE acquisition_observations SET body=? WHERE id=?',('{}',reference));db.commit()
        context,_=self.context()
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'closure_changed'):
            recovery.derive_qualified_recovery_target(context)

    def test_real_handler_gap_cannot_be_dropped_from_the_target(self):
        self.failed_source()
        with closing(sqlite3.connect(self.source_path)) as db:
            db.execute('DELETE FROM candidate_gaps');db.commit()
        context,_=self.context()
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'gap_changed'):
            recovery.derive_qualified_recovery_target(context)

    def test_bound_target_cannot_outlive_actual_guard_owner_or_deadline(self):
        self.failed_source();context,_=self.context();target=recovery.derive_qualified_recovery_target(context)
        errors=[]
        def foreign():
            try:target.value()
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=foreign);worker.start();worker.join(2)
        self.assertEqual(len(errors),1);self.assertIn('target_owner',str(errors[0]))
        self.boundary_valid=False
        with self.assertRaisesRegex(ValueError,'snapshot_changed'):target.value()
        self.boundary_valid=True;context.deadline=time.monotonic()-1
        with self.assertRaises(TimeoutError):target.value()
        context.deadline=time.monotonic()+5;context.close()
        with self.assertRaisesRegex(ValueError,'context_owner'):target.value()
