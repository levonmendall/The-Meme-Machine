"""An empty hot journal skips optional preservation, never financial replay."""
from contextlib import ExitStack, closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime import preserved_checkpoint
from meme_machine.runtime.journal import canonical, digest
from meme_machine.runtime.sleeve_reservations import SleeveReservations


class SleevePrefixSchedulingTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.enterContext(patch.dict(os.environ,dict(MM_MODE='PAPER',
            MM_PAPER_EPOCH='disposable-prefix-scheduling',MM_STATE_ROOT=str(self.root)),clear=True))

    def seed(self,name='sleeve',*,lane='pump',positions=True):
        path=self.root/name/'directional-sleeve.sqlite'
        args=dict(lane=lane,capital=1000,policies={'current':'a','survivor':'b'},cohort='fixture')
        book=SleeveReservations(path,**args)
        try:
            for at in (1,2,3):
                book.observe('candidate',strategy='survivor',at=at,state='qualified',
                    evidence={'at':at},regime={'original':True})
            if positions:
                book.reserve('settled',strategy='current',amount=100,at=4)
                with book.commit_fence('settled'):pass
                book.release('settled',pnl=10,at=5,terminal_hash='verified-native-terminal',native_verified=True)
                book.reserve('held',strategy='current',amount=100,at=6)
            proof=book.reconcile()
            self.assertGreater(book.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone()[0],0)
        finally:book.close()
        # Establish the prefix through the original constructor's actual SQLite
        # backup, raw snapshot authentication and transactional reducer.
        book=SleeveReservations(path,**args)
        try:
            self.assertEqual(book.reconcile(),proof)
            self.assertEqual(book.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone(),(0,))
            anchor=book._archive();self.assertGreater(anchor['seq'],0)
            self.assertEqual(anchor['final_hash'],proof['final_hash'])
        finally:book.close()
        return path,args,proof,anchor

    def rows(self,path):
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            return {table:db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
                for table in ('sleeve_genesis','sleeve_journal','sleeve_archive',
                    'sleeve_positions','sleeve_candidates','sleeve_rallies')}

    @contextmanager
    def preservation_calls(self):
        calls=[];compactions=[]
        snapshot=preserved_checkpoint.snapshot;compact=SleeveReservations._compact_preserved
        @contextmanager
        def preserved(path,**kwargs):
            with snapshot(path,**kwargs) as value:
                calls.append((Path(path),kwargs,None if value is None else dict(value[1])))
                yield value
        def reduced(book,path,authority):
            before=book.reconcile()
            result=compact(book,path,authority)
            self.assertEqual(book.reconcile(),before)
            compactions.append((result,dict(authority)))
            return result
        with patch.object(preserved_checkpoint,'snapshot',preserved),patch.object(
                SleeveReservations,'_compact_preserved',reduced):
            yield calls,compactions

    def test_archived_empty_prefix_reopens_without_snapshot_or_hash_rotation_but_replays(self):
        for lane in ('pump','pons'):
            with self.subTest(lane=lane):
                path,args,proof,anchor=self.seed(lane,lane=lane)
                before=self.rows(path);replayed=[];reconcile=SleeveReservations._reconcile
                def verified(book):
                    value=reconcile(book);replayed.append(value);return value
                with patch.object(preserved_checkpoint,'snapshot',side_effect=AssertionError('unneeded backup')) as backup, \
                        patch.object(SleeveReservations,'_compact_preserved',side_effect=AssertionError('unneeded rewrite')) as compact, \
                        patch.object(SleeveReservations,'_reconcile',verified):
                    for _ in range(2):
                        book=SleeveReservations(path,**args)
                        try:
                            self.assertEqual(book.reconcile(),proof)
                            self.assertEqual(book._archive(),anchor)
                            self.assertEqual(book.candidate('candidate')['generation'],3)
                            self.assertEqual(book.get('held')['held'],100)
                            self.assertEqual(book.get('settled')['pnl'],10)
                            self.assertTrue(book.opportunity_ready)
                            self.assertEqual(book.db.execute('PRAGMA synchronous').fetchone(),(2,))
                            self.assertEqual(book.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
                            with self.assertRaisesRegex(ValueError,'terminal_reservation_reused'):
                                book.reserve('settled',strategy='current',amount=100,at=9)
                            with self.assertRaisesRegex(ValueError,'sleeve_reservation_conflict'):
                                book.reserve('held',strategy='current',amount=101,at=9)
                        finally:book.close()
                backup.assert_not_called();compact.assert_not_called()
                self.assertGreaterEqual(len(replayed),2)
                self.assertTrue(all(value==proof for value in replayed))
                self.assertEqual(self.rows(path),before)

    def test_hot_tail_uses_original_snapshot_authority_and_compacts_without_financial_change(self):
        path,args,_,anchor=self.seed()
        book=SleeveReservations(path,**args)
        try:
            book.observe('candidate',strategy='survivor',at=7,state='qualified',evidence={'at':7},regime={})
            book.release('held',pnl=-5,at=8,terminal_hash='second-native-terminal',native_verified=True)
            proof=book.reconcile();self.assertEqual(proof['available'],1005)
        finally:book.close()
        with self.preservation_calls() as (backups,compactions):
            book=SleeveReservations(path,**args)
            try:
                self.assertEqual(book.reconcile(),proof)
                current=book._archive()
                self.assertEqual(current['previous_archive_hash'],digest(anchor))
                self.assertEqual(current['final_hash'],proof['final_hash'])
                self.assertEqual(current['authority'],backups[0][2])
                self.assertEqual(current['authority']['epoch_id'],os.environ['MM_PAPER_EPOCH'])
                self.assertEqual(current['authority']['snapshot_name'],'pump/directional-sleeve.sqlite')
                self.assertRegex(current['authority']['snapshot_sha256'],'^[0-9a-f]{64}$')
                self.assertEqual(book.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone(),(0,))
                with self.assertRaisesRegex(ValueError,'duplicate_settlement_conflict'):
                    book.release('held',pnl=-4,at=8,terminal_hash='second-native-terminal',native_verified=True)
            finally:book.close()
        self.assertEqual(len(backups),1);self.assertEqual(compactions,[(True,backups[0][2])])

    def test_real_append_after_empty_read_is_reconciled_and_next_open_preserves_it(self):
        path,args,old_proof,anchor=self.seed()
        writer=SleeveReservations(path,**args);self.addCleanup(writer.close)
        original_connect=sqlite3.connect;readers=[];appended=[]
        class Cursor:
            def __init__(self,native):self.native=native
            def fetchone(cursor):
                result=cursor.native.fetchone()
                if result is None and not appended:
                    appended.append(writer.observe('candidate',strategy='survivor',at=7,
                        state='qualified',evidence={'arrived_after_read':True},regime={}))
                return result
        class Connection:
            def __init__(self,native):self.native=native
            def __getattr__(self,name):return getattr(self.native,name)
            def execute(self,sql,*args):
                cursor=self.native.execute(sql,*args)
                return Cursor(cursor) if sql=='SELECT 1 FROM sleeve_journal LIMIT 1' else cursor
        def connected(database,*a,**kwargs):
            native=original_connect(database,*a,**kwargs)
            if kwargs.get('uri') and kwargs.get('timeout')==0:
                readers.append(native);return Connection(native)
            return native
        with patch.object(sqlite3,'connect',connected),patch.object(preserved_checkpoint,
                'snapshot',side_effect=AssertionError('empty decision acquired backup')):
            book=SleeveReservations(path,**args)
        try:
            proof=writer.reconcile();self.assertNotEqual(proof['final_hash'],old_proof['final_hash'])
            self.assertEqual(book.reconcile(),proof)
            self.assertEqual(book.candidate('candidate'),appended[0])
            self.assertEqual(book._archive(),anchor)
            self.assertEqual(book.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone(),(1,))
        finally:book.close()
        self.assertEqual(len(readers),1)
        with self.assertRaises(sqlite3.ProgrammingError):readers[0].execute('SELECT 1')
        with self.preservation_calls() as (backups,compactions):
            book=SleeveReservations(path,**args)
            try:
                self.assertEqual(book.reconcile(),proof)
                self.assertEqual(book._archive()['final_hash'],proof['final_hash'])
                self.assertEqual(book.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone(),(0,))
            finally:book.close()
        self.assertEqual(len(backups),1);self.assertEqual(compactions[0][0],True)

    def test_probe_query_or_close_error_keeps_original_preservation_and_closes_reader(self):
        for failure in ('query','close'):
            with self.subTest(failure=failure):
                path,args,proof,_=self.seed(failure)
                original_connect=sqlite3.connect;readers=[]
                class FailedProbe:
                    def __init__(self,native):self.native=native
                    def __getattr__(self,name):return getattr(self.native,name)
                    def execute(self,sql,*args):
                        if failure=='query' and sql=='SELECT 1 FROM sleeve_journal LIMIT 1':
                            raise sqlite3.OperationalError('disposable probe unavailable')
                        return self.native.execute(sql,*args)
                    def close(self):
                        self.native.close()
                        if failure=='close':raise sqlite3.OperationalError('disposable close unavailable')
                def connected(database,*a,**kwargs):
                    native=original_connect(database,*a,**kwargs)
                    if kwargs.get('uri') and kwargs.get('timeout')==0:
                        readers.append(native);return FailedProbe(native)
                    return native
                with patch.object(sqlite3,'connect',connected),self.preservation_calls() as (backups,compactions):
                    book=SleeveReservations(path,**args)
                    try:self.assertEqual(book.reconcile(),proof)
                    finally:book.close()
                self.assertEqual(len(backups),1);self.assertTrue(compactions[0][0])
                self.assertEqual(len(readers),1)
                with self.assertRaises(sqlite3.ProgrammingError):readers[0].execute('SELECT 1')

    def test_missing_file_and_absent_epoch_keep_original_snapshot_entry_contract(self):
        args=dict(lane='pump',capital=1000,policies={'current':'a','survivor':'b'},cohort='fixture')
        path=self.root/'new.sqlite'
        with self.preservation_calls() as (backups,compactions):
            book=SleeveReservations(path,**args)
            try:self.assertEqual(book.reconcile()['available'],1000)
            finally:book.close()
        self.assertEqual(backups,[(path,dict(name='pump/directional-sleeve.sqlite',lane='pump'),None)])
        self.assertEqual(compactions,[])
        path,args,proof,anchor=self.seed('no-epoch')
        with patch.dict(os.environ,MM_PAPER_EPOCH=''),self.preservation_calls() as (backups,compactions):
            book=SleeveReservations(path,**args)
            try:self.assertEqual(book.reconcile(),proof);self.assertEqual(book._archive(),anchor)
            finally:book.close()
        self.assertEqual(backups,[(path,dict(name='pump/directional-sleeve.sqlite',lane='pump'),None)])
        self.assertEqual(compactions,[])

    def test_empty_probe_never_replaces_archive_projection_or_genesis_validation(self):
        for corruption,expected in (('archive','sleeve_archive_integrity'),
                ('positions','sleeve_projection_corruption'),('candidates','sleeve_candidate_corruption'),
                ('genesis','sleeve_genesis_drift'),('policy','paper_policy_transition_unknown_strategy')):
            with self.subTest(corruption=corruption):
                path,args,_,_=self.seed(corruption)
                with closing(sqlite3.connect(path)) as db,db:
                    if corruption=='archive':db.execute('UPDATE sleeve_archive SET hash=?',('b'*64,))
                    elif corruption=='positions':
                        row=json.loads(db.execute("SELECT body FROM sleeve_positions WHERE id='held'").fetchone()[0])
                        db.execute("UPDATE sleeve_positions SET body=? WHERE id='held'",(canonical(dict(row,held=99)),))
                    elif corruption=='candidates':
                        row=json.loads(db.execute('SELECT body FROM sleeve_candidates').fetchone()[0])
                        db.execute('UPDATE sleeve_candidates SET body=?',(canonical(dict(row,generation=99)),))
                    elif corruption=='genesis':args=dict(args,cohort='foreign-cohort')
                    else:args=dict(args,policies={'current':'unapproved','survivor':'b'})
                before=self.rows(path)
                with patch.object(preserved_checkpoint,'snapshot',side_effect=AssertionError('empty prefix backup')):
                    with self.assertRaisesRegex(ValueError,expected):SleeveReservations(path,**args)
                self.assertEqual(self.rows(path),before)

    def test_original_reconcile_interruption_rolls_back_and_closes_constructor_connection(self):
        path,args,proof,_=self.seed();before=self.rows(path);connections=[]
        reconcile=SleeveReservations._reconcile
        def interrupted(book):
            self.assertEqual(reconcile(book),proof);connections.append(book.db)
            raise SystemExit('disposable interruption during original reconcile')
        with patch.object(SleeveReservations,'_reconcile',interrupted),patch.object(
                preserved_checkpoint,'snapshot',side_effect=AssertionError('empty prefix backup')):
            with self.assertRaisesRegex(SystemExit,'original reconcile'):SleeveReservations(path,**args)
        self.assertEqual(len(connections),1)
        with self.assertRaises(sqlite3.ProgrammingError):connections[0].execute('SELECT 1')
        self.assertEqual(self.rows(path),before)
        book=SleeveReservations(path,**args)
        try:self.assertEqual(book.reconcile(),proof)
        finally:book.close()

    def test_shared_authority_selection_and_unbacked_hold_checks_survive_empty_prefix(self):
        from tests import test_integrated_startup_rehearsal as shared_fixture
        from meme_machine.shared_capital.native_sleeve import SharedSleeve
        from meme_machine.shared_capital.model import CapitalError
        from meme_machine.shared_capital import runtime
        path,args,proof,_=self.seed('flat',positions=False)
        held,held_args,_,_=self.seed('unbacked')
        with ExitStack() as stack:
            shared,journal=shared_fixture.IntegratedStartupRehearsal.pons_shared_authority(self,stack)
            authority=runtime.connection(shared);before=authority.snapshot();replay=authority.verify_replay()
            with patch.object(preserved_checkpoint,'snapshot',side_effect=AssertionError('empty prefix backup')):
                book=SharedSleeve(path,**args)
                try:
                    self.assertIs(book.authority,authority)
                    self.assertEqual(book.reconcile(),proof)
                finally:book.close()
                with self.assertRaisesRegex(CapitalError,'unbacked_native_family_attribution'):
                    SharedSleeve(held,**held_args)
            self.assertEqual(authority.verify_replay(),replay)
            self.assertEqual(authority.snapshot(),before)
            with closing(sqlite3.connect(shared)) as db:
                self.assertEqual(db.execute('SELECT * FROM shared_capital_events ORDER BY sequence').fetchall(),journal)

    def test_real_retirement_scope_still_rejects_archived_lifecycle_after_empty_reopen(self):
        from tests import test_survivor_terminal_retirement as retirement_fixture
        from meme_machine.runtime import survivor_terminal_archive
        fixture=retirement_fixture.SurvivorTerminalArchiveTests()
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        identities=fixture.populate(0,count=1);fixture.preserve(0)
        self.assertTrue(survivor_terminal_archive.compact(fixture.book,fixture.sleeve,fixture.history))
        proof=fixture.sleeve.reconcile();anchor=fixture.sleeve._archive()
        self.assertIn('retirement_receipt',anchor)
        self.assertIn('survivor',anchor['archived_entry_scopes'])
        self.assertEqual(fixture.sleeve.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone(),(0,))
        args={key:fixture.sleeve.identity[key] for key in ('lane','capital','policies','cohort')}
        fixture.sleeve.close()
        with patch.object(preserved_checkpoint,'snapshot',side_effect=AssertionError('empty retired backup')):
            fixture.sleeve=SleeveReservations(fixture.hot/'sleeve.sqlite',**args)
        self.assertEqual(fixture.sleeve.reconcile(),proof)
        self.assertEqual(fixture.sleeve._archive(),anchor)
        with self.assertRaisesRegex(ValueError,'archived_lifecycle_replay'):
            fixture.sleeve.reserve(identities[0],strategy='survivor',amount=100,at=999999)
        self.assertEqual(fixture.sleeve.reconcile(),proof)
        self.assertEqual(fixture.sleeve._archive(),anchor)
