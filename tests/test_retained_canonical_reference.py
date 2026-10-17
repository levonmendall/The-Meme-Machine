"""Existing canonical references survive one exact restored PAPER cohort move.

All files are disposable. The original source/outbox and FULL consumer generate
references before migration; their absolute legacy paths and hashes are never
rewritten. No provider, financial recovery or runtime readiness is inferred.
"""
from contextlib import closing,contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.runtime import candidate_history as reference_module
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime.journal import canonical,digest
from meme_machine.runtime.stop import Shutdown
from meme_machine.solana_history_archive import prepare as prepare_archive,apply as apply_archive
from meme_machine.solana_history_delivery import capture,deliver,acknowledge,generation
from meme_machine.solana_scoped_retirement import ScopedRetirement
from meme_machine.solana_selective_history import PROGRAMS,economic_records
from tests.test_solana_closure import NOW,state_at
from tests.test_solana_selective_evidence import FIXTURE


PRODUCTION_LEGACY=Path('/mnt/volume_nyc1_1790918115030/meme-machine-paper-shared-1000')
PRODUCTION_AWS=Path('/srv/meme-machine/state/shared-1000')
PRODUCTION_EPOCH='paper-shared-1000-20261011T071207Z'


class RetainedCanonicalReferenceTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.legacy=self.root/'retained-do-1000'
        self.aws=self.root/'restored-aws-1000'
        self.production=(reference_module.RETAINED_REFERENCE_LEGACY_ROOT,
            reference_module.RETAINED_REFERENCE_AWS_ROOT,reference_module.RETAINED_REFERENCE_EPOCH)
        # Assert immutable production pins before patching disposable locations.
        # A fixture must not make a broadened production rule look correct.
        self.assertEqual(self.production,(PRODUCTION_LEGACY,PRODUCTION_AWS,PRODUCTION_EPOCH))
        self.enterContext(patch.object(reference_module,'RETAINED_REFERENCE_LEGACY_ROOT',self.legacy))
        self.enterContext(patch.object(reference_module,'RETAINED_REFERENCE_AWS_ROOT',self.aws))
        self.enterContext(patch.dict(os.environ,dict(MM_MODE='PAPER',MM_STATE_ROOT=str(self.legacy),
            MM_PAPER_EPOCH=PRODUCTION_EPOCH,MM_SOLANA_HISTORY_SEPARATED='1'),clear=True))
        self.canonical=self.aws/'shared/solana-evidence.sqlite'
        self.consumer=self.aws/'shared/solana-candidate-history.sqlite'

    @staticmethod
    def file_hash(path):return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def rows(path):
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            # Some authoritative tables deliberately use WITHOUT ROWID.
            # Compare every column and duplicate row without assuming a rowid
            # or asking Python to order mixed SQLite scalar types directly.
            return {name:sorted(db.execute('SELECT * FROM "'+name.replace('"','""')+'"').fetchall(),key=repr)
                for name in names}

    def prepare(self,*,cold=False):
        old_source=self.legacy/'shared/solana-evidence.sqlite'
        old_consumer=self.legacy/'shared/solana-candidate-history.sqlite'
        self.state,self.history=state_at(old_source)
        self.closed=False
        def cleanup_owner():
            if not self.closed:self.state.writer.close()
        self.addCleanup(cleanup_owner)
        life=self.history.lifecycle;life.delivery_separated=True;life.path=old_consumer
        records=[]
        for transaction in FIXTURE['pump']:
            records.extend(economic_records('pump',PROGRAMS['pump'],deepcopy(transaction),
                endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream'))
        self.mint=next(row.payload['event']['mint'] for row in records
            if row.payload['event']['event_type']=='create')
        self.history.bind('pump',self.mint)
        self.history.ingest(records)
        for _ in range(8):
            batch=capture(life)
            if batch is None:break
            self.assertTrue(acknowledge(life,batch,deliver(batch)))
        self.assertIsNone(life.unconsumed(self.history.scope_for('pump',self.mint)))
        with closing(CandidateHistory(old_consumer)) as shared:
            self.expected=shared.events('pump',self.mint)
            self.assertTrue(self.expected)
            self.original_refs=shared.db.execute('SELECT * FROM canonical_event_refs ORDER BY rowid').fetchall()
            self.assertTrue(self.original_refs)
            self.assertTrue(all(json.loads(row[-2])['path']==str(old_source) for row in self.original_refs))
            self.assertEqual(shared.db.execute('PRAGMA synchronous').fetchone()[0],2)
        self.archives=[]
        if cold:
            ScopedRetirement(self.history)
            # This fixture tests retained locator resolution rather than hot-
            # page selection. Use its exact, already FULL-delivered identities
            # so an unrelated SQLite-version index-planner restriction does
            # not prevent constructing a genuine archive through prepare/apply.
            identities={json.loads(row[-2])['canonical_identity'] for row in self.original_refs}
            self.assertTrue(identities);self.assertLessEqual(len(identities),64)
            selected={identity:self.history.db.execute('SELECT * FROM canonical_evidence WHERE identity=?',
                (identity,)).fetchone() for identity in sorted(identities)}
            self.assertTrue(all(row is not None and row[9] is not None for row in selected.values()))
            plan=dict(selected=selected,pinned={},oldest=None,before=None,bindings=[],
                started=time.monotonic(),canonical_path=str(old_source.resolve()),
                generation=generation(life),limit=64,
                selection=dict(mode='disposable_exact_retained_identities',
                    metadata_rows=len(selected),metadata_row_bound=len(selected),candidate_scopes=1))
            prepared=prepare_archive(plan)
            result=apply_archive(self.history,plan,prepared)
            # Original apply independently rechecks generation, current source
            # bytes/hashes, durable ACK, every owner/pin and all addresses.
            self.assertTrue(result['canonical_generation_revalidated'])
            self.assertEqual(result['retired_records'],len(selected))
            self.archives=self.history.db.execute('SELECT id,path,hash FROM scoped_cold_manifests').fetchall()
            self.assertTrue(self.archives)
            self.assertTrue(self.history.db.execute('SELECT 1 FROM canonical_evidence WHERE body IS NULL LIMIT 1').fetchone())
            with closing(CandidateHistory(old_consumer)) as shared:
                self.assertEqual(shared.events('pump',self.mint),self.expected)
        # A separate disposable $500 book is retained byte-for-byte through
        # every read below; no relocation rule may promote its cohort identity.
        from meme_machine.runtime.survivor_paper_book import PaperBook
        self.history500=self.root/'preserved-500.sqlite'
        with closing(PaperBook(self.history500,run_id='original-500',lane='survivor',policy_hash='old',initial=500)) as book:
            self.assertTrue(book.replay()['verified'])
        self.history500_hash=self.file_hash(self.history500)
        self.owner_before=self.rows(old_source)
        self.consumer_before=self.rows(old_consumer)
        self.state.writer.close();self.closed=True
        shutil.move(str(self.legacy),str(self.aws))
        self.assertFalse(self.legacy.exists())
        os.environ['MM_STATE_ROOT']=str(self.aws)
        os.environ['MM_SOLANA_EVIDENCE_PLANE_DB']=str(self.canonical)
        os.environ['MM_SOLANA_CANDIDATE_HISTORY_DB']=str(self.consumer)
        self.assertEqual(self.rows(self.canonical),self.owner_before)
        self.assertEqual(self.rows(self.consumer),self.consumer_before)

    def read(self,**kwargs):
        with closing(CandidateHistory(self.consumer)) as shared:return shared.events('pump',self.mint,**kwargs)

    def restored(self,path):
        """Execute the actual cheap native startup reconstruction, without RPC."""
        from types import SimpleNamespace
        from meme_machine.lanes.pump import runner
        from meme_machine.runtime import stop
        created={};postgrad={};pools=[];creations=[];graduations=[]
        confirmations=SimpleNamespace(observe_creation=lambda row:creations.append(deepcopy(row)),
            observe_graduation=lambda mint,at:graduations.append((mint,at)))
        with closing(CandidateHistory(path)) as shared, \
                patch.object(runner,'CANDIDATE_HISTORY',shared), \
                patch.object(stop,'requested',threading.Event()):
            count=runner._restore_observed_pump_candidates(created,postgrad,
                SimpleNamespace(add_address=pools.append),object(),confirmations,
                max(row['market_time'] for row in self.expected))
        # LocalPumpHistory is a runtime adapter rather than persistent state.
        # Compare every reconstructed economic field and its adapter identity.
        for row in postgrad.values():
            history=row.pop('history')
            row['history_identity']=(history.pool,history.graduation_time)
        return count,created,postgrad,pools,creations,graduations

    def unchanged(self):
        self.assertEqual(self.rows(self.canonical),self.owner_before)
        self.assertEqual(self.rows(self.consumer),self.consumer_before)
        self.assertEqual(self.file_hash(self.history500),self.history500_hash)
        self.assertFalse(self.legacy.exists())

    @contextmanager
    def consumer_ref(self,**changes):
        with closing(sqlite3.connect(self.consumer,isolation_level=None)) as db:
            original=db.execute('SELECT lane,candidate,identity,body,hash FROM canonical_event_refs ORDER BY rowid LIMIT 1').fetchone()
            ref=json.loads(original[3]);ref.update(changes);raw=canonical(ref)
            db.execute('UPDATE canonical_event_refs SET body=?,hash=? WHERE lane=? AND candidate=? AND identity=?',
                (raw,digest(ref),*original[:3]))
            try:yield
            finally:db.execute('UPDATE canonical_event_refs SET body=?,hash=? WHERE lane=? AND candidate=? AND identity=?',
                (original[3],original[4],*original[:3]))

    def test_exact_pins_real_hot_references_preserve_economics_order_and_first_seen(self):
        self.assertEqual(self.production,(PRODUCTION_LEGACY,PRODUCTION_AWS,PRODUCTION_EPOCH))
        self.prepare()
        self.assertEqual(self.read(),self.expected)
        with closing(CandidateHistory(self.consumer)) as shared:
            self.assertEqual(shared.event('pump',self.mint,self.expected[0]['identity']),self.expected[0])
            self.assertEqual(shared.db.execute('SELECT * FROM canonical_event_refs ORDER BY rowid').fetchall(),self.original_refs)
        self.unchanged()

    def test_original_cantopen_reproduces_then_actual_native_restore_restarts_with_same_history(self):
        self.prepare()
        # The original implementation's exact read-only open still fails for
        # the retained absolute path; recovery is not an empty replacement DB.
        legacy=self.legacy/'shared/solana-evidence.sqlite'
        with self.assertRaises(sqlite3.OperationalError) as caught:
            sqlite3.connect(legacy.as_uri()+'?mode=ro',uri=True)
        self.assertEqual(caught.exception.sqlite_errorcode & 255,sqlite3.SQLITE_CANTOPEN)
        restored=self.restored(self.consumer)
        self.assertGreater(restored[0],0)
        self.assertIn(self.mint,restored[1])
        creation=next(row['payload'] for row in self.expected if row['kind']=='pump_create')
        self.assertEqual(restored[1][self.mint]['creation'],creation)
        self.assertEqual(self.restored(self.consumer),restored)
        self.unchanged()

    def test_default_canonical_selector_retains_exact_cohort_and_original_bytes(self):
        self.prepare()
        del os.environ['MM_SOLANA_EVIDENCE_PLANE_DB']
        self.assertEqual(self.read(),self.expected)
        self.unchanged()

    def test_real_cold_archive_paths_and_manifest_bytes_survive_move_without_rewrite(self):
        self.prepare(cold=True)
        self.assertEqual(self.read(),self.expected)
        for _identity,old_path,checksum in self.archives:
            old=Path(old_path);target=self.aws/old.relative_to(self.legacy)
            self.assertFalse(old.exists());self.assertEqual(self.file_hash(target),checksum)
        self.unchanged()

    def test_original_cantopen_remains_for_unconfigured_and_unknown_legacy_paths(self):
        self.prepare()
        with patch.dict(os.environ,MM_STATE_ROOT=str(self.legacy)):
            with self.assertRaises(sqlite3.OperationalError) as caught:self.read()
        self.assertEqual(caught.exception.sqlite_errorcode & 255,sqlite3.SQLITE_CANTOPEN)
        for path in (self.root/'unknown-cohort/shared/solana-evidence.sqlite',
                self.root/'meme-machine-paper-shared-500/shared/solana-evidence.sqlite'):
            with self.subTest(path=path),self.consumer_ref(path=str(path)):
                with self.assertRaises(sqlite3.OperationalError) as caught:self.read()
                self.assertEqual(caught.exception.sqlite_errorcode & 255,sqlite3.SQLITE_CANTOPEN)
            self.assertFalse(path.exists())
        self.unchanged()

    def test_wrong_epoch_mode_scope_and_explicit_plane_refuse_known_relocation(self):
        self.prepare()
        for key,value in (('MM_PAPER_EPOCH','paper-shared-500'),('MM_MODE','LIVE'),
                ('MM_STATE_ROOT',str(self.root/'another-root')),
                ('MM_SOLANA_EVIDENCE_PLANE_DB',str(self.aws/'shared/other.sqlite'))):
            with self.subTest(key=key),patch.dict(os.environ,{key:value}):
                with self.assertRaises((ValueError,sqlite3.OperationalError,FileNotFoundError)):self.read()
        with patch.dict(os.environ):
            del os.environ['MM_MODE']
            with self.assertRaisesRegex(ValueError,'candidate_canonical_reference_cohort_unverified'):
                self.read()
        copied=self.aws/'other/solana-candidate-history.sqlite';copied.parent.mkdir()
        shutil.copyfile(self.consumer,copied)
        with closing(CandidateHistory(copied)) as wrong_scope:
            with self.assertRaises((ValueError,sqlite3.OperationalError,FileNotFoundError)):
                wrong_scope.events('pump',self.mint)
        self.unchanged()

    def test_missing_and_symlink_canonical_target_refuse_without_creation(self):
        self.prepare();saved=self.aws/'retained-original.sqlite'
        self.canonical.rename(saved)
        try:
            with self.assertRaises((ValueError,sqlite3.OperationalError,FileNotFoundError)):self.read()
            self.assertFalse(self.canonical.exists())
            self.canonical.symlink_to(saved)
            with self.assertRaises((ValueError,sqlite3.OperationalError,FileNotFoundError)):self.read()
        finally:
            if self.canonical.is_symlink():self.canonical.unlink()
            saved.rename(self.canonical)
        self.unchanged()

    def test_symlink_state_root_shared_directory_and_candidate_store_refuse(self):
        self.prepare()
        for location in (self.aws,self.aws/'shared',self.consumer):
            with self.subTest(location=location):
                saved=location.with_name(location.name+'.retained')
                location.rename(saved)
                try:
                    location.symlink_to(saved,target_is_directory=saved.is_dir())
                    with self.assertRaisesRegex(ValueError,'candidate_canonical_reference_cohort_unverified'):
                        self.read()
                finally:
                    location.unlink();saved.rename(location)
        self.unchanged()

    def test_canonical_hash_and_reference_identity_corruption_never_use_cached_success(self):
        self.prepare()
        with closing(CandidateHistory(self.consumer)) as shared:
            self.assertEqual(shared.events('pump',self.mint),self.expected)
            self.assertTrue(shared._source_readers)
            with self.consumer_ref(canonical_hash='b'*64):
                with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):
                    shared.events('pump',self.mint)
            with self.consumer_ref(canonical_identity='missing-retained-record'):
                with self.assertRaisesRegex(ValueError,'candidate_canonical_reference_missing'):
                    shared.events('pump',self.mint)
        self.unchanged()

    def test_cold_manifest_sha_missing_target_and_unknown_archive_path_refuse(self):
        self.prepare(cold=True)
        identity,old_path,checksum=self.archives[0]
        target=self.aws/Path(old_path).relative_to(self.legacy)
        packed=target.read_bytes()
        try:
            target.write_bytes(packed+b'corrupt')
            with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):self.read()
        finally:target.write_bytes(packed)
        saved=target.with_suffix('.retained');target.rename(saved)
        try:
            with self.assertRaises((ValueError,FileNotFoundError)):self.read()
            self.assertFalse(target.exists())
        finally:saved.rename(target)
        with closing(sqlite3.connect(self.canonical,isolation_level=None)) as db:
            try:
                db.execute('UPDATE scoped_cold_manifests SET path=? WHERE id=?',
                    (str(self.root/'unknown-archive'/Path(old_path).name),identity))
                with self.assertRaises((ValueError,FileNotFoundError)):self.read()
            finally:db.execute('UPDATE scoped_cold_manifests SET path=? WHERE id=?',(old_path,identity))
        self.unchanged()

    def test_cold_symlink_and_rehashed_manifest_with_changed_economics_refuse(self):
        import zlib
        self.prepare(cold=True)
        identity,old_path,checksum=self.archives[0]
        target=self.aws/Path(old_path).relative_to(self.legacy)
        saved=target.with_suffix('.retained');target.rename(saved)
        try:
            target.symlink_to(saved)
            with self.assertRaisesRegex(ValueError,'candidate_canonical_reference_cohort_unverified'):
                self.read()
        finally:
            target.unlink();saved.rename(target)
        packed=target.read_bytes();rows=json.loads(zlib.decompress(packed))
        rows[0]['record']['payload']['event']['market_time']+=1
        modified=zlib.compress(canonical(rows).encode())
        with closing(sqlite3.connect(self.canonical,isolation_level=None)) as db:
            try:
                target.write_bytes(modified)
                db.execute('UPDATE scoped_cold_manifests SET hash=? WHERE id=?',
                    (hashlib.sha256(modified).hexdigest(),identity))
                # A matching manifest checksum cannot replace the original
                # canonical record and retained per-record checksum.
                with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):self.read()
            finally:
                target.write_bytes(packed)
                db.execute('UPDATE scoped_cold_manifests SET hash=? WHERE id=?',(checksum,identity))
        self.unchanged()

    def test_cancel_before_reference_open_and_reader_cleanup_preserve_state(self):
        self.prepare();opened=[];connect=reference_module.diagnostic_connect
        def tracked(*args,**kwargs):
            db=connect(*args,**kwargs)
            if kwargs.get('diagnostic_role')=='candidate_reference':opened.append(db)
            return db
        with patch.object(reference_module,'diagnostic_connect',side_effect=tracked):
            shared=CandidateHistory(self.consumer)
            try:
                with self.assertRaises(Shutdown):shared.events('pump',self.mint,cancelled=lambda:True)
                self.assertEqual(opened,[])
                self.assertEqual(shared.events('pump',self.mint),self.expected)
                self.assertTrue(opened)
                for db in opened:
                    self.assertFalse(db.in_transaction)
                    with self.assertRaises(sqlite3.OperationalError) as caught:
                        db.execute('DELETE FROM meta WHERE 0')
                    self.assertEqual(caught.exception.sqlite_errorcode & 255,sqlite3.SQLITE_READONLY)
                requested=threading.Event();requested.set()
                with self.assertRaises(Shutdown):shared.events('pump',self.mint,cancelled=requested.is_set)
            finally:shared.close()
        for db in opened:
            with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')
        self.unchanged()

