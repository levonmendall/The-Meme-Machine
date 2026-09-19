from dataclasses import replace
import tempfile
import unittest
from robinhood_research import BoundaryError
from robinhood_research.evidence import Stamp, Store
from robinhood_research.finality import Finality


class FinalityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=self.tmp.name+'/evidence.sqlite'
        self.store=Store(self.path);self.ledger=Finality(self.store)
        self.a=Stamp(4663,10,'a',100,101,'confirmed','natural')
        self.b=Stamp(4663,11,'b',101,102,'confirmed','natural')
        self.c=Stamp(4663,12,'c',102,103,'confirmed','natural')
        self.ledger.observe(self.a,'prior')
        self.ledger.observe(self.b,'a')
        self.ledger.observe(self.c,'b')

    def tearDown(self):
        self.store.close();self.tmp.cleanup()

    def test_confirmed_requires_ledger_and_freshness_unchanged(self):
        with self.assertRaisesRegex(BoundaryError,'unfinalized'):
            self.c.check(103,5)
        self.c.check(103,5,finality_ledger=self.ledger)
        with self.assertRaisesRegex(BoundaryError,'stale'):
            self.c.check(108,5,finality_ledger=self.ledger)

    def test_duplicate_idempotent_conflict_rejected(self):
        self.assertFalse(self.ledger.observe(replace(self.b,observed_at=104),'a'))
        with self.assertRaisesRegex(BoundaryError,'conflicting'):
            self.ledger.observe(replace(self.b,event_at=100),'a')

    def test_fork_invalidates_transitive_dependencies(self):
        self.ledger.bind('candidate',[self.a,self.c],asof=103)
        self.ledger.observe(Stamp(4663,11,'replacement',101,104,'confirmed','natural'),'a')
        self.assertEqual(self.ledger.status('b'),'invalidated')
        self.assertEqual(self.ledger.status('c'),'invalidated')
        with self.assertRaisesRegex(BoundaryError,'dependent'):
            self.ledger.check_dependency('candidate')

    def test_removed_log_invalidates_descendants(self):
        self.ledger.removed('b',observed_at=104)
        with self.assertRaisesRegex(BoundaryError,'displaced'):
            self.c.check(104,5,finality_ledger=self.ledger)
        self.assertEqual(self.ledger.status('a'),'confirmed')

    def test_finalization_preserves_availability_and_restart(self):
        self.ledger.bind('candidate',[self.a,self.c],asof=103)
        frontier=Stamp(4663,20,'f',150,180,'finalized','natural')
        self.ledger.reconcile(frontier=frontier,canonical_headers=[dict(block=10,block_hash='a'),dict(block=11,block_hash='b'),dict(block=12,block_hash='c')],observed_at=180)
        self.store.close();self.store=Store(self.path);self.ledger=Finality(self.store)
        self.assertEqual(self.ledger.check_dependency('candidate'),'finalized')
        self.assertEqual(self.ledger.block('c')['stamp']['observed_at'],103)
        with self.assertRaisesRegex(BoundaryError,'finalized_chain'):
            self.ledger.removed('b',observed_at=181)

    def test_missing_finalization_coverage(self):
        with self.assertRaisesRegex(BoundaryError,'coverage'):
            self.ledger.reconcile(frontier=Stamp(4663,20,'f',150,180,'finalized','natural'),canonical_headers=[],observed_at=180)

    def test_canonical_disagreement_invalidates_without_promotion(self):
        with self.assertRaisesRegex(BoundaryError,'hash_disagreement'):
            self.ledger.reconcile(frontier=Stamp(4663,20,'f',150,180,'finalized','natural'),canonical_headers=[dict(block=10,block_hash='a'),dict(block=11,block_hash='other'),dict(block=12,block_hash='other2')],observed_at=180)
        self.assertEqual(self.ledger.status('c'),'invalidated')
        self.assertEqual(self.ledger.status('a'),'confirmed')

    def test_unknown_ancestry_and_backdating_fail(self):
        with self.assertRaisesRegex(BoundaryError,'ancestry'):
            self.ledger.observe(Stamp(4663,14,'d',103,104,'confirmed','natural'),'unknown')
        with self.assertRaisesRegex(BoundaryError,'backdated'):
            self.ledger.removed('c',observed_at=100)
