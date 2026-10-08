"""Actual WAL connections cannot mix journal and projection generations."""
import hashlib,sqlite3,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from meme_machine.runtime.sleeve_reservations import SleeveReservations

class SleeveReconciliationSnapshotTests(unittest.TestCase):
    def books(self,path):
        return [SleeveReservations(path,lane='pump',capital=1000,policies={'current':'a','survivor':'b'},cohort='existing-fixed-epoch') for _ in range(2)]

    def test_other_connection_commit_during_replay_cannot_look_like_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            reader,writer=self.books(Path(td)/'sleeve.sqlite');native=reader.db;interleaved=[]
            class Interleave:
                def __getattr__(self,name):return getattr(native,name)
                def execute(self,sql,*args):
                    cursor=native.execute(sql,*args)
                    if sql=='SELECT * FROM sleeve_journal ORDER BY seq' and not interleaved:
                        interleaved.append(True)
                        writer.reserve('existing-lifecycle',strategy='current',amount=100,at=1)
                    return cursor
            reader.db=Interleave()
            try:
                result=reader.reconcile()
                self.assertEqual(interleaved,[True]);self.assertTrue(result['reconciled'])
                self.assertEqual(result['available'],1000)
                self.assertEqual(result['reserved'],0)
                self.assertFalse(native.in_transaction)
                self.assertEqual(reader.reconcile()['available'],900)
                self.assertEqual(writer.get('existing-lifecycle')['held'],100)
            finally:
                reader.db=native;reader.close();writer.close()

    def test_reconcile_inside_mutation_does_not_commit_caller_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            reader,writer=self.books(Path(td)/'sleeve.sqlite')
            try:
                with self.assertRaisesRegex(RuntimeError,'interrupted-caller'):
                    with reader.transaction():
                        reader._event('reserve',dict(id='rolled-back',strategy='current',amount=100,held=100,at=1,candidate=None,generation=None,regime=None,status='reserved',pnl=0,asset=None,scale_committed=False))
                        self.assertEqual(reader.reconcile()['available'],900)
                        self.assertTrue(reader.db.in_transaction)
                        raise RuntimeError('interrupted-caller')
                self.assertIsNone(writer.get('rolled-back'))
                self.assertEqual(writer.reconcile()['available'],1000)
                self.assertFalse(reader.db.in_transaction)
            finally:reader.close();writer.close()

    def test_real_projection_corruption_still_fails_and_releases_read_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            reader,writer=self.books(Path(td)/'sleeve.sqlite')
            try:
                writer.reserve('existing-lifecycle',strategy='current',amount=100,at=1)
                writer.db.execute("UPDATE sleeve_positions SET body='{}' WHERE id='existing-lifecycle'")
                with self.assertRaisesRegex(ValueError,'sleeve_projection_corruption'):
                    reader.reconcile()
                self.assertFalse(reader.db.in_transaction)
                self.assertFalse(writer.db.in_transaction)
            finally:
                # Deliberately corrupt disposable projections cannot reconcile.
                reader.db.close();writer.db.close()

    def preserved(self,reader,path):
        db=sqlite3.connect(path)
        try:reader.db.backup(db)
        finally:db.close()
        return dict(snapshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),state_hash='existing-preserved-state')

    def test_preserved_snapshot_replay_compacts_without_changing_open_reservation(self):
        with tempfile.TemporaryDirectory() as td:
            reader,writer=self.books(Path(td)/'sleeve.sqlite')
            try:
                writer.reserve('existing-lifecycle',strategy='current',amount=100,at=1)
                before=reader.reconcile();path=Path(td)/'preserved.sqlite'
                authority=self.preserved(reader,path)
                self.assertTrue(reader._compact_preserved(path,authority))
                self.assertEqual(reader.reconcile(),before)
                self.assertEqual(reader.get('existing-lifecycle')['held'],100)
                self.assertFalse(reader._compact_preserved(path,authority))
                self.assertEqual(writer.reconcile(),before)
            finally:reader.close();writer.close()

    def test_interrupted_preserved_compaction_restores_original_journal_and_reservation(self):
        with tempfile.TemporaryDirectory() as td:
            reader,writer=self.books(Path(td)/'sleeve.sqlite')
            try:
                writer.reserve('existing-lifecycle',strategy='current',amount=100,at=1)
                before=reader.reconcile();path=Path(td)/'preserved.sqlite'
                authority=self.preserved(reader,path);original=SleeveReservations._reconcile
                def interrupted(book):
                    if book is reader and not book.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone()[0] and book.db.execute('SELECT 1 FROM sleeve_archive').fetchone():
                        raise RuntimeError('interrupted-archive-verification')
                    return original(book)
                with patch.object(SleeveReservations,'_reconcile',interrupted):
                    with self.assertRaisesRegex(RuntimeError,'interrupted-archive-verification'):
                        reader._compact_preserved(path,authority)
                self.assertFalse(reader.db.in_transaction)
                self.assertEqual(reader.reconcile(),before)
                self.assertEqual(reader.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone()[0],1)
                self.assertIsNone(reader.db.execute('SELECT 1 FROM sleeve_archive').fetchone())
                self.assertEqual(writer.get('existing-lifecycle')['held'],100)
            finally:reader.close();writer.close()

    def test_readonly_directional_terminal_replays_existing_books_without_constructor(self):
        from meme_machine.runtime.directional_accounting import terminal
        from meme_machine.runtime.directional_sleeve import policies
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.survivor_history import History
        from meme_machine.lanes.pump.paper_accounting import PaperBook as CurrentBook
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'pump-survivor';folder.mkdir()
            approved=policies('pump');survivor=next(k for k in approved if 'survivor' in k)
            current=next(k for k in approved if k!=survivor)
            sleeve=SleeveReservations(root/'directional-sleeve.sqlite',lane='pump',capital=1000,policies=approved,cohort='existing-fixed-epoch')
            sleeve.close()
            book=PaperBook(folder/'paper.sqlite',run_id='existing-fixed-epoch',lane=survivor,policy_hash=approved[survivor],initial=1000)
            book.close()
            history=History(folder/'history.sqlite',policy=approved[survivor]);history.db.close()
            native=CurrentBook(root/'pump-acceleration-natural-prospective.accounting.sqlite3',run_id='existing-fixed-epoch',lane=current,policy_hash=approved[current],initial=1000)
            accounting=native.reconcile();native.close()
            files=list(root.rglob('*.sqlite'))+list(root.rglob('*.sqlite3'))
            before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            result=terminal('pump',root,dict(accounting=accounting,open_positions=0,verified=True))
            self.assertTrue(result['verified']);self.assertTrue(result['accounting']['one_funded_genesis'])
            self.assertEqual(result['accounting']['cash'],1000)
            self.assertEqual(result['survivor']['sleeve']['available'],1000)
            self.assertEqual(before,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
