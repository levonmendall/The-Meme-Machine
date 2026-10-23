"""Independent regression: bounded planning must retain parallel history access.

All proofs and jobs are declared temporary fixtures. No provider response,
financial effect, real market opportunity or authenticated live rate is implied.
"""
from pathlib import Path
import tempfile
import unittest

from tests.test_solana_closure import NOW, state_at
from tests.test_solana_prewarm_startup import proof
from meme_machine.solana_history_work import HistoricalTasks, prepare_history
from meme_machine.solana_rolling_history import program_scope


class OwnerPlanningFanoutTests(unittest.TestCase):
    def exercise(self, method):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'canonical.sqlite'
            clock = [NOW]
            state, history = state_at(path, lambda: clock[0])
            try:
                history.historical_tasks = HistoricalTasks(history)
                history.bind('pumpswap', 'independent-history-pieces')
                for lo, hi in ((100, 100), (103, 103), (106, 106), (109, 110)):
                    history.prove(proof(program_scope('pumpswap'), lo, hi))
                parent = history.request('pumpswap', 'independent-history-pieces',
                    100, 110, priority=3, deadline=NOW+150)
                expected = {(101, 102), (104, 105), (107, 108)}
                flights = set()
                acquired = set()
                for turn in range(128):
                    # Exercise the real separated historian and authoritative
                    # apply, outside each planner transaction. No fake verdict.
                    for _ in range(32):
                        task = history.historical_tasks.claim()
                        if task is None:
                            break
                        history.historical_tasks.apply(task, prepare_history(path, task))
                    result = getattr(history, method)(excluding=tuple(sorted(flights)))
                    plan = result if method == 'plan' else result.plan
                    if plan is not None:
                        job = plan[0]
                        self.assertNotEqual(job['id'], parent)
                        self.assertEqual(job['deadline'], NOW+150)
                        self.assertIn((job['lo'], job['hi']), expected)
                        self.assertNotIn(job['id'], flights)
                        flights.add(job['id'])
                        acquired.add((job['lo'], job['hi']))
                    if acquired == expected:
                        break
                    # The first physical child remains in flight throughout.
                    # Other disjoint pieces must become independently eligible.
                    clock[0] += .11
                self.assertEqual(acquired, expected,
                    'later missing pieces must not wait for first-child coverage')
                self.assertEqual(history.db.execute(
                    'SELECT lo,hi,deadline,status,token,pages FROM acquisition_jobs WHERE id=?',
                    (parent,)).fetchone(), (100, 110, NOW+150, 'pending', None, 0))
                self.assertEqual(history.db.execute(
                    'SELECT COUNT(*) FROM acquisition_page_receipts').fetchone(), (0,))
                self.assertFalse(history.db.in_transaction)
            finally:
                state.writer.close()

    def test_original_planner_materializes_independent_children_before_first_io_finishes(self):
        self.exercise('plan')

    def test_bounded_planner_preserves_independent_children_before_first_io_finishes(self):
        self.exercise('plan_step')
