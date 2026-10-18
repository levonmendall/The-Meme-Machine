"""Offline acquisition contracts and actual private immutable pre-write reads.

The reader cases supply an authenticated-launch premise; they do not fabricate
root ownership or claim an actual systemd launch on the engineering host.
"""
from contextlib import ExitStack, closing
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational import normal_boot as boot
from meme_machine.operational import normal_boot_record as wire


def certificate():
    value={key:'a'*64 for key in wire.CERTIFICATE_KEYS}
    value.update(schema='stopped-flat-boot-eligibility-v1',state='ELIGIBLE_FUNDING_CLOSED_ONLY',
        request_action='start',request_id='offline-contract',application_commit='1'*40,
        application_tree='2'*40,administration_commit='3'*40,administration_tree='4'*40,
        worker_hashes={key:'a'*64 for key in wire.WORKERS},epoch_id='offline-epoch',
        combined_sequence=42,four_regimes=list(wire.REGIMES),
        obligations={key:0 for key in wire.OBLIGATIONS},source_inputs={key:None for key in wire.SOURCE_INPUTS},
        unknown_historical_handlers=2,native_books_verified=7,native_databases_inspected=9,
        held_existing_fences=5,boot_id='11111111-2222-3333-4444-555555555555',
        issued_monotonic=time.monotonic(),authoritative_writes=0,provider_requests=0)
    value['not_after_monotonic']=value['issued_monotonic']+60
    value['source_inputs']['source_drain']={'bytes':123,'sha256':'a'*64}
    for key in ('funding_authority','safe_for_normal','current_native_protection_verified',
            'historical_handler_disposition_verified','historical_drain_reclassified','canonical_cohort_complete'):
        value[key]=False
    return rehash(value)


def rehash(value):
    value['certificate_sha256']=wire.digest({k:v for k,v in value.items() if k!='certificate_sha256'})
    return value


def envelope(value=None):
    value=certificate() if value is None else value
    record={key:deepcopy(value[key]) for key in ('request_id','boot_id','issued_monotonic',
        'not_after_monotonic','application_commit','application_tree','administration_commit','worker_hashes')}
    record.update(schema='normal-flat-launch-v1',state='SEALED',instance='b'*32,stop_generation='INITIAL',
        boot_eligibility=value,supervisor={'pid':os.getpid(),'start_ticks':'123','invocation_id':'c'*32},
        funding_authority=False,safe_for_normal=False,historical_handler_disposition_verified=False)
    locator={key:deepcopy(record[key]) for key in ('state','request_id','instance','boot_id',
        'stop_generation','issued_monotonic','not_after_monotonic')}
    locator.update(schema='normal-flat-launch-locator-v1',record_sha256=hashlib.sha256(wire.canonical(record)).hexdigest())
    return locator,record


def physical_hash(root):
    rows=[]
    for directory,dirs,files in os.walk(root):
        for path in (Path(directory),*(Path(directory)/name for name in files)):
            rows.append([str(path.relative_to(root)),list(wire.file_identity(path.lstat()))])
    return hashlib.sha256(json.dumps(sorted(rows),separators=(',',':')).encode()).hexdigest()


class NormalBootRecordTests(unittest.TestCase):
    def test_exact_shape_preserves_unknown_two_and_no_authority(self):
        locator,record=envelope()
        value=wire.validate_envelope(locator,record)
        self.assertEqual(value['unknown_historical_handlers'],2)
        self.assertEqual(value['native_databases_inspected'],9)
        self.assertFalse(value['funding_authority'] or value['safe_for_normal'])
        self.assertEqual((value['authoritative_writes'],value['provider_requests']),(0,0))

    def test_signed_shape_never_repairs_bad_population_epoch_policy_or_authority(self):
        for changes in ({'native_databases_inspected':6},{'native_books_verified':5},
                {'funding_authority':True},{'provider_requests':True},
                {'obligations':dict.fromkeys(wire.OBLIGATIONS,False)},
                {'four_regimes':['pump_current']},{'policy_sha256':'bad'},
                {'epoch_id':''},{'not_after_monotonic':float('inf')}):
            with self.subTest(changes=changes):
                value=certificate();value.update(changes)
                if changes.get('not_after_monotonic')!=float('inf'):rehash(value)
                with self.assertRaises(wire.NormalBootUnavailable):wire.validate_certificate(value)
        value=certificate();value['epoch_id']='different-but-unhashed'
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'checksum'):wire.validate_certificate(value)

    def test_record_cross_instance_stop_expiry_and_extra_field_refuse(self):
        for key,value in (('stop_generation','0'),('boot_id','another-boot'),('instance','bad'),
                ('state','REVOKED'),('not_after_monotonic',float('nan'))):
            with self.subTest(key=key):
                locator,record=envelope();locator[key]=value
                with self.assertRaises(wire.NormalBootUnavailable):wire.validate_envelope(locator,record)
        locator,record=envelope();record['supervisor']['start_ticks']='0123'
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'sealed_instance'):
            wire.validate_envelope(locator,record)
        locator,record=envelope();record['readiness']=True
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'record_fields'):
            wire.validate_envelope(locator,record)

    def test_json_duplicate_and_nonfinite_are_not_normalized(self):
        for raw in ('{"state":"SEALED","state":"PENDING"}','{"x":NaN}'):
            with self.subTest(raw=raw),self.assertRaises(wire.NormalBootUnavailable):wire._json(raw)

    def test_private_issuer_and_real_nonroot_file_cannot_grant_launch(self):
        locator,record=envelope()
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'issuer'):
            wire.AuthenticatedNormalLaunch(locator,record)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'normal-launch.json';path.write_bytes(wire.canonical(locator));path.chmod(0o640)
            # The engineering-owned file genuinely lacks root acquisition.
            if os.geteuid()!=0:
                with patch.object(wire.pwd,'getpwnam',return_value=SimpleNamespace(pw_gid=os.getgid())):
                    with self.assertRaises(wire.NormalBootUnavailable):wire._protected_bytes(path,2048)

    def test_pending_wait_sealed_kernel_binding_expiry_and_revocation(self):
        locator,record=envelope()
        pending_locator=deepcopy(locator);pending_locator['state']='PENDING'
        pending_record=deepcopy(record);pending_record.update(state='PENDING',supervisor=None)
        with patch.object(wire,'_read_record',side_effect=[(pending_locator,pending_record),
                (locator,record),(locator,record)]),patch.object(wire,'current_kernel_instance',
                return_value=(record['supervisor'],record['boot_id'])),patch.object(wire.time,'sleep'):
            launch=wire.await_normal_launch(cancelled=lambda:False)
        with patch.object(wire,'_read_record',return_value=(locator,record)), \
                patch.object(wire,'current_kernel_instance',return_value=(record['supervisor'],record['boot_id'])):
            self.assertEqual(launch.require_current(initial=True),record)
            with patch.object(wire.time,'monotonic',return_value=record['not_after_monotonic']):
                with self.assertRaisesRegex(wire.NormalBootUnavailable,'expired'):launch.require_current(initial=True)
                # Expiry limits first consumption, not a later ongoing root identity check.
                self.assertEqual(launch.require_current(),record)
            revoked=deepcopy(locator);revoked['state']='REVOKED'
            with patch.object(wire,'_read_record',return_value=(revoked,record)):
                with self.assertRaisesRegex(wire.NormalBootUnavailable,'replaced'):launch.require_current()


class OwnedPrewriteReadTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.path=self.root/'book.sqlite'
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE native(value)');db.execute('INSERT INTO native VALUES(7)');db.commit()
        for name in boot.LOCKS:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.touch()
        self.lock=(self.root/'supervisor.lock').open('rb');self.addCleanup(self.lock.close)
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.supervisor=SimpleNamespace(root=self.root,lock=self.lock,processes={})
        self.locator,self.record=envelope()
        # Fixed typed acquisition premise. These tests exercise the real owned
        # reader, not root/systemd attestation, which the host cannot produce.
        self.launch=wire.AuthenticatedNormalLaunch(self.locator,self.record,_issuer=wire._ISSUER)
        self.boundary=patch.object(wire.AuthenticatedNormalLaunch,'require_current',
            lambda launch,**kwargs:deepcopy(self.record))
        self.boundary.start();self.addCleanup(self.boundary.stop)

    def seal_physical(self):
        self.record['boot_eligibility']['physical_generation_sha256']=physical_hash(self.root)

    def reader(self,*,cancelled=lambda:False):
        return boot._OwnedPrewriteReads(self.supervisor,self.launch,cancelled=cancelled)

    def test_actual_rw_namespace_zero_wal_shm_is_pinned_readonly_and_unchanged(self):
        wal=Path(str(self.path)+'-wal');shm=Path(str(self.path)+'-shm')
        wal.touch();shm.write_bytes(b'\0'*32768);self.seal_physical()
        before={path:wire.file_identity(path.stat()) for path in (self.path,wal,shm)}
        with self.reader() as reads:
            db=reads.databases[self.path]
            self.assertEqual(db.execute('SELECT value FROM native').fetchall(),[(7,)])
            self.assertTrue(db.in_transaction)
            self.assertEqual(db.execute('PRAGMA query_only').fetchone(),(1,))
            with self.assertRaises(sqlite3.OperationalError):db.execute('INSERT INTO native VALUES(8)')
            self.assertEqual(reads.metadata_sha256(),self.record['boot_eligibility']['physical_generation_sha256'])
            descriptor=reads.files[self.path][0]
            self.assertTrue(fcntl.fcntl(descriptor,fcntl.F_GETFD)&fcntl.FD_CLOEXEC)
        self.assertEqual(before,{path:wire.file_identity(path.stat()) for path in before})
        with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')
        with self.assertRaises(OSError):os.fstat(descriptor)

    def test_nonempty_wal_or_any_rollback_journal_refuses_before_sqlite_open(self):
        for suffix,body in (('-wal',b'one frame'),('-journal',b'')):
            with self.subTest(suffix=suffix):
                path=Path(str(self.path)+suffix);path.write_bytes(body);self.seal_physical()
                with patch.object(boot.sqlite3,'connect',side_effect=AssertionError('fallback open')):
                    with self.assertRaisesRegex(wire.NormalBootUnavailable,'wal|journal'):
                        with self.reader():pass
                path.unlink()

    def test_actual_concurrent_uncooperative_commit_invalidates_whole_result(self):
        self.seal_physical()
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'file_changed|directory_changed'):
            with self.reader() as reads:
                self.assertEqual(reads.databases[self.path].execute('SELECT value FROM native').fetchone(),(7,))
                errors=[]
                def mutate():
                    try:
                        with closing(sqlite3.connect(self.path)) as db:
                            db.execute('UPDATE native SET value=8');db.commit()
                    except Exception as error:errors.append(error)
                worker=threading.Thread(target=mutate);worker.start();worker.join(2)
                self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
                reads.validate()

    def test_actual_replacement_new_support_file_and_hardlink_refuse(self):
        self.seal_physical()
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'changed'):
            with self.reader() as reads:
                self.path.rename(self.path.with_suffix('.old'))
                self.path.write_bytes(b'replacement')
                # The existing SQL handle remains on its held original inode.
                self.assertEqual(reads.databases[self.path].execute('SELECT value FROM native').fetchone(),(7,))
        self.path.unlink();self.path.with_suffix('.old').rename(self.path)
        self.seal_physical()
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'directory_changed'):
            with self.reader():Path(str(self.path)+'-wal').touch()
        Path(str(self.path)+'-wal').unlink()
        os.link(self.path,self.root/'linked');self.seal_physical()
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'file_bound'):
            with self.reader():pass

    def test_existing_writer_lock_before_read_and_all_partial_fds_are_released(self):
        self.seal_physical();other=(self.root/boot.LOCKS[-1]).open('rb');self.addCleanup(other.close)
        fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=set(os.listdir('/proc/self/fd'))
        with self.assertRaises(BlockingIOError):
            with self.reader():pass
        self.assertEqual(before,set(os.listdir('/proc/self/fd')))
        fcntl.flock(other,fcntl.LOCK_UN)
        # No earlier lock leaked out of a failed attempt.
        with self.reader():pass

    def test_symlink_parent_cancel_foreign_owner_and_post_constructor_refuse(self):
        self.seal_physical()
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'cancelled'):
            with self.reader(cancelled=lambda:True):pass
        with self.reader() as reads:
            errors=[]
            def foreign():
                try:reads.validate()
                except Exception as error:errors.append(error)
            worker=threading.Thread(target=foreign);worker.start();worker.join(2)
            self.assertEqual(len(errors),1);self.assertIn('owner',str(errors[0]))
        self.supervisor.shared_capital=object()
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'before_runtime'):self.reader()
        del self.supervisor.shared_capital
        original=self.root/'pons';original.rename(self.root/'other-pons');original.symlink_to(self.root/'other-pons')
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'ancestor'):
            with self.reader():pass

    def test_original_source_census_requires_committed_sessions_keeps_unknown_two(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE service_health(key PRIMARY KEY,value)')
            body=dict(state='RECOVERY_REQUIRED',accepted_handlers=2,settled_handlers=0,pending_handlers=2,
                terminal=True,all_accepted_committed=True,unpreserved_sessions=0,
                queues={name:dict(accepted=0,committed=0,pending=0) for name in ('control','scout','rolling','candidate')})
            db.execute('INSERT INTO service_health VALUES(?,?)',('source_drain',json.dumps(body)))
            values,census=boot._source_inputs(db)
            self.assertEqual(census['pending_handlers'],2);self.assertIsNone(values['source_handler_recovery'])
            body['all_accepted_committed']=False
            db.execute('UPDATE service_health SET value=?',(json.dumps(body),))
            with self.assertRaisesRegex(wire.NormalBootUnavailable,'uncommitted'):boot._source_inputs(db)


class NativePrewriteReplayTests(unittest.TestCase):
    def setUp(self):
        from tests.test_stopped_flat_native_boot import StoppedFlatNativeBootTests
        from meme_machine.operational.bounded_provider import Budget
        from meme_machine.solana_evidence_service import ServiceState
        from meme_machine.solana_provider_config import AlchemyEndpoint
        from meme_machine.runtime.candidate_history import CandidateHistory
        self.case=StoppedFlatNativeBootTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        context,snapshots=self.case.original_context()
        dead=context._validate_owner;context.close()
        native_paths=list(snapshots)
        for db in snapshots.values():db.close()
        self.root=self.case.root
        provider=self.root/'shared/provider-usage.continuous.sqlite'
        source_root=Path(__file__).resolve().parents[1]
        profile_path=source_root/'operational/pump-first-release/deployment/paper-continuous.four-regime.json'
        self.profile=json.loads(profile_path.read_text())
        budget=Budget.create(provider,continuous=self.profile)
        budget.publish_readiness(False,'offline-prewrite-prior')
        self.case.writer.command('offline-prior-admission','runtime_admission',dict(mode='OBSERVATION',
            run_id='offline-prewrite-prior',pid=os.getpid(),process_start='1',provider_db=str(provider),
            continuous_provider_db=str(provider)),self.case.now)
        evidence=ServiceState(self.root/'shared/solana-evidence.sqlite',
            AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline_fixture_only'))
        raw=json.dumps(dict(state='RECOVERY_REQUIRED',accepted_handlers=2,settled_handlers=0,pending_handlers=2,
            terminal=True,all_accepted_committed=True,unpreserved_sessions=0,
            queues={name:dict(accepted=0,committed=0,pending=0) for name in ('control','scout','rolling','candidate')}))
        evidence.writer.db.execute("INSERT OR REPLACE INTO service_health(key,value) VALUES('source_drain',?)",(raw,))
        evidence.writer.db.commit();evidence.close()
        history=CandidateHistory(self.root/'shared/solana-candidate-history.sqlite');history.close()
        context,snapshots=self.case.context(extra=[path for path in native_paths
            if path not in (self.root/'portfolio.sqlite',self.root/'shared-capital.sqlite')])
        context._validate_owner=dead
        from meme_machine.runtime.native_flat_boot import validate_stopped_flat_boot_inputs
        value=validate_stopped_flat_boot_inputs(context).value()
        context.close()
        for db in snapshots.values():db.close()
        self.case.writer.close()
        # Native terminal operations legitimately use the original per-thread
        # shared writer cache. Close only this disposable fixture's cached
        # owner before constructing its genuinely pre-write corpus.
        from meme_machine.shared_capital import runtime
        pool=getattr(runtime._LOCAL,'pool',{})
        cached=pool.pop(str(self.root/'shared-capital.sqlite'),None)
        if cached is not None:cached[1].close()
        for name in boot.LOCKS:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.touch(exist_ok=True)
        self.lock=(self.root/'supervisor.lock').open('rb');self.addCleanup(self.lock.close)
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.supervisor=SimpleNamespace(root=self.root,lock=self.lock,processes={})
        self.locator,self.record=envelope();cert=self.record['boot_eligibility']
        for key in ('epoch_id','inception_sha256','journal_hash','projection_hash','combined_sequence',
                'native_input_sha256','policy_sha256'):cert[key]=value[key]
        cert['continuous_profile_sha256']=wire.digest(self.profile)
        cert['source_inputs']={key:None for key in wire.SOURCE_INPUTS}
        cert['source_inputs']['source_drain']={'bytes':len(raw.encode()),'sha256':hashlib.sha256(raw.encode()).hexdigest()}
        cert['physical_generation_sha256']=physical_hash(self.root)
        rehash(cert)
        self.locator['record_sha256']=hashlib.sha256(wire.canonical(self.record)).hexdigest()
        wire.validate_envelope(self.locator,self.record)
        self.launch=wire.AuthenticatedNormalLaunch(self.locator,self.record,_issuer=wire._ISSUER)
        self.enterContext(patch.object(wire.AuthenticatedNormalLaunch,'require_current',
            lambda launch,**kwargs:deepcopy(self.record)))
        self.enterContext(patch.object(boot,'await_normal_launch',return_value=self.launch))
        self.enterContext(patch.object(boot,'_source_identity',return_value=(cert['application_commit'],cert['application_tree'])))
        self.enterContext(patch.dict(os.environ,{'MM_PROVIDER_USAGE_DB':str(provider),
            'MM_CONTINUOUS_PROVIDER_ENVELOPE':str(profile_path)}))
        self.enterContext(patch.object(boot,'_ACTIVE',None))

    def test_real_all_four_cold_replay_closes_before_private_nonfunding_context(self):
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
        from meme_machine.runtime.robinhood.plane import Plane
        files={path:wire.file_identity(path.stat()) for path in self.root.rglob('*') if path.is_file()}
        with patch.object(PaperBook,'__init__',side_effect=AssertionError('book writer')), \
                patch.object(SleeveReservations,'__init__',side_effect=AssertionError('sleeve writer')), \
                patch.object(CohortCapital,'__init__',side_effect=AssertionError('capital writer')), \
                patch.object(Plane,'__init__',side_effect=AssertionError('Plane writer')):
            context=boot.consume_normal_boot(self.supervisor,cancelled=lambda:False)
        self.assertIs(boot.require_boot_context(context),context)
        identity=context.require_current()
        self.assertEqual(identity['unknown_historical_handlers'],2)
        self.assertEqual(identity['epoch_id'],self.record['boot_eligibility']['epoch_id'])
        self.assertNotIn('funding_authority',identity)
        self.assertEqual(files,{path:wire.file_identity(path.stat()) for path in files})
        self.assertTrue(self.launch._consumed)
        # All temporary reader fences were released before ordinary actors;
        # the original Supervisor alone still owns its original lock.
        for name in boot.LOCKS[1:]:
            with (self.root/name).open('rb') as handle:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        context.close()
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'owner'):boot.require_boot_context(context)

    def test_genuine_replay_refuses_rehashed_epoch_head_source_and_native_hash_substitutions(self):
        for key in ('epoch_id','journal_hash','native_input_sha256'):
            with self.subTest(key=key):
                value=self.record['boot_eligibility'][key]
                self.record['boot_eligibility'][key]='wrong-epoch' if key=='epoch_id' else '0'*64
                rehash(self.record['boot_eligibility']);wire.validate_certificate(self.record['boot_eligibility'])
                try:
                    with self.assertRaisesRegex(wire.NormalBootUnavailable,'native_or_financial_generation'):
                        boot.consume_normal_boot(self.supervisor,cancelled=lambda:False)
                    self.assertIsNone(boot._ACTIVE)
                finally:
                    self.record['boot_eligibility'][key]=value;rehash(self.record['boot_eligibility'])
        self.record['boot_eligibility']['source_inputs']['source_drain']['sha256']='0'*64
        rehash(self.record['boot_eligibility']);wire.validate_certificate(self.record['boot_eligibility'])
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'retained_source_inputs'):
            boot.consume_normal_boot(self.supervisor,cancelled=lambda:False)
        self.assertFalse(self.launch._consumed)

    def test_all_required_roles_and_unknown_extra_economic_store_refuse_before_grant(self):
        required,_=boot._configured_databases(self.root)
        self.assertEqual(len(required),14)
        # The source producer's database count is not a completeness substitute.
        path=self.root/'shared/solana-candidate-history.sqlite';path.rename(path.with_suffix('.gone'))
        self.record['boot_eligibility']['physical_generation_sha256']=physical_hash(self.root)
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'configured_database_missing'):
            boot.consume_normal_boot(self.supervisor,cancelled=lambda:False)
        self.assertIsNone(boot._ACTIVE)
        path.with_suffix('.gone').rename(path)
        with closing(sqlite3.connect(self.root/'unmapped.sqlite')) as db:
            db.execute('CREATE TABLE hidden_positions(body)');db.commit()
        self.record['boot_eligibility']['physical_generation_sha256']=physical_hash(self.root)
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'unmapped_database'):
            boot.consume_normal_boot(self.supervisor,cancelled=lambda:False)
        self.assertIsNone(boot._ACTIVE)

    def test_supervisor_cannot_reach_first_financial_open_before_seal_replay(self):
        from meme_machine.operational.supervisor import Supervisor
        from meme_machine.shared_capital import runtime
        supervisor=Supervisor(self.root)
        self.addCleanup(lambda:supervisor.lock.close() if supervisor.lock is not None else None)
        # Use the real initialize ownership sequence; only host configuration
        # and the deliberately unavailable root seal are injected.
        self.lock.close()
        with patch('meme_machine.operational.supervisor.validate_environment'), \
                patch('meme_machine.operational.admission.require_normal',return_value=self.profile), \
                patch('meme_machine.operational.storage_guard.verify_storage'), \
                patch.object(boot,'consume_normal_boot',side_effect=wire.NormalBootUnavailable('no seal')) as consume, \
                patch.object(runtime,'selected',side_effect=AssertionError('premature selected')), \
                patch.object(runtime,'connection',side_effect=AssertionError('premature financial writer')):
            with self.assertRaisesRegex(wire.NormalBootUnavailable,'no seal'):supervisor.initialize()
        self.assertEqual(consume.call_count,1)
