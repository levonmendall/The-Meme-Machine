import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meme_machine.engine import Engine
from meme_machine.store import Store
from tests.support import MINT, SCOUT, event, evidence, snapshot


class Longevity(unittest.TestCase):
    def test_journal_tail_rotates_and_restart_preserves_chain(self):
        with tempfile.TemporaryDirectory() as td:
            path=str(Path(td)/'state.db')
            with patch('meme_machine.store.JOURNAL_MAX_ROWS',12), \
                 patch('meme_machine.store.JOURNAL_KEEP_ROWS',6):
                store=Store(path,'synthetic',100_000_000,'longevity test')
                for _ in range(40):
                    with store.transaction('soak_write'):
                        store.state['progress']+=1
                stats=store.journal_stats()
                self.assertLessEqual(stats['rows'],12)
                self.assertGreater(stats['rotations'],0)
                self.assertGreater(stats['anchor_seq'],0)
                self.assertTrue(store.verify_archive())
                tail=(store.state['journal_seq'],store.state['journal_hash'])
                store.close()

                store=Store(path,'synthetic',100_000_000,'longevity test')
                self.assertEqual((store.state['journal_seq'],store.state['journal_hash']),tail)
                self.assertTrue(store.verify_archive())
                self.assertLessEqual(store.journal_stats()['rows'],12)
                store.close()

    def test_rotated_retained_tail_still_detects_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            path=str(Path(td)/'state.db')
            with patch('meme_machine.store.JOURNAL_MAX_ROWS',10), \
                 patch('meme_machine.store.JOURNAL_KEEP_ROWS',5):
                store=Store(path,'synthetic',100_000_000,'longevity test')
                for _ in range(24):
                    with store.transaction('soak_write'):
                        store.state['progress']+=1
                first=store.db.execute('SELECT seq FROM journal ORDER BY seq LIMIT 1').fetchone()[0]
                store.db.execute("UPDATE journal SET event='corrupt' WHERE seq=?",(first,))
                with self.assertRaisesRegex(RuntimeError,'journal_corruption'):
                    store.verify_archive()
                store.close()

    def test_identical_unresolved_marks_are_coalesced_but_real_exit_attempts_are_not(self):
        with tempfile.TemporaryDirectory() as td:
            path=str(Path(td)/'state.db')
            store=Store(path,'synthetic',100_000_000,'longevity test')
            engine=Engine(store,[SCOUT])
            nomination=engine.scout([event(100)],100)[0]
            self.assertEqual(engine.consider(nomination,evidence(100),100),'qualified')
            self.assertEqual(engine.fill(nomination['id'],snapshot(102),102),'settled')

            before=store.state['journal_seq']
            self.assertEqual(engine.monitor(MINT,{},107),'unresolved')
            first=store.state['journal_seq']
            self.assertEqual(first,before+1)
            for now in (112,117,122,127,132,137,142,147,152,157,162):
                self.assertEqual(engine.monitor(MINT,{},now),'unresolved_coalesced')
                self.assertEqual(store.state['journal_seq'],first)
            self.assertEqual(engine.monitor(MINT,{},167),'unresolved')
            self.assertEqual(store.state['journal_seq'],first+1)

            # A recovered real quote is persisted immediately.
            recovered_before=store.state['journal_seq']
            self.assertIn(engine.monitor(MINT,snapshot(172),172),('holding','exit_intended'))
            self.assertEqual(store.state['journal_seq'],recovered_before+1)

            # Real failed exit attempts carry economic gas cost and are never coalesced.
            if store.state['positions'][MINT]['exit_due'] is None:
                self.assertEqual(engine.monitor(MINT,snapshot(177,sol=40_000_000_000),177),'exit_intended')
            failed_before=store.state['journal_seq']
            due=max(182,store.state['positions'][MINT]['exit_due'])
            self.assertEqual(engine.monitor(MINT,snapshot(due,sol=40_000_000_000),due,failed=True),'exit_failed')
            self.assertEqual(store.state['journal_seq'],failed_before+1)
            second_before=store.state['journal_seq']
            self.assertEqual(engine.monitor(MINT,snapshot(due+5,sol=40_000_000_000),due+5,failed=True),'exit_failed')
            self.assertEqual(store.state['journal_seq'],second_before+1)
            store.reconcile()
            store.close()


if __name__=='__main__':
    unittest.main()
