import unittest
from engineering.solana_capacity.live_probe import normal_drain
from engineering.solana_capacity.final_mixed import position_disposition,candidate_census,required_gap_census


class RunningDrain(unittest.TestCase):
    def sample(self,t,n,closed=False):
        return dict(at=t,depth=n,closed=closed,completed=t*10)
    def test_shutdown_zero_cannot_prove_live_drain(self):
        samples=[self.sample(t,58) for t in range(20)]+[self.sample(t,0,True) for t in range(20,40)]
        self.assertFalse(normal_drain(samples,0,19,64)['proven'])
    def test_peak_then_completed_running_service_with_stable_tail(self):
        samples=[self.sample(0,58)]+[self.sample(t,max(0,58-t*6)) for t in range(1,30)]
        proof=normal_drain(samples,0,29,64)
        self.assertTrue(proof['proven']);self.assertEqual(proof['peak_to_half_seconds'],5)
    def test_high_queue_cannot_redefine_normal_baseline(self):
        samples=[self.sample(t,58 if t<20 else 40) for t in range(40)]
        self.assertFalse(normal_drain(samples,0,39,64)['proven'])
    def test_no_observation_is_not_zero(self):
        self.assertFalse(normal_drain([],0,30,64)['proven'])
    def test_mark_without_continuation_is_not_complete(self):
        self.assertEqual(position_disposition(dict(ready=True,dependencies=dict(ordered_history_ready=False))),'incomplete')
        self.assertEqual(position_disposition(dict(ready=True,dependencies=dict(ordered_history_ready=True))),'completed')
    def test_unrestored_candidate_history_is_observed_without_creation(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'not-yet-created.sqlite'
            self.assertFalse(candidate_census(path)['initialized']);self.assertFalse(path.exists())

    def test_gap_census_retains_all_active_aliases_with_bounded_observer_work(self):
        import sqlite3
        with sqlite3.connect(':memory:') as db:
            db.executescript('''CREATE TABLE candidate_lifecycle(family,address,state,PRIMARY KEY(family,address));
                CREATE TABLE evidence_bindings(family,address,coverage_scope,PRIMARY KEY(family,address));
                CREATE TABLE candidate_gaps(id INTEGER PRIMARY KEY,scope,repaired);''')
            active=set();gaps=[]
            for n in range(3000):
                state='warming' if n%17==0 else 'cheap_retained'
                scope='candidate:'+str(n//2) # Multiple aliases share one view.
                db.execute('INSERT INTO candidate_lifecycle VALUES(?,?,?)',('meteora',str(n),state))
                db.execute('INSERT INTO evidence_bindings VALUES(?,?,?)',('meteora',str(n),scope))
                if state=='warming':active.add(scope)
                repaired=1 if n%5==0 else None
                db.execute('INSERT INTO candidate_gaps VALUES(?,?,?)',(n,scope,repaired))
                gaps.append((n,scope,repaired))
            # The independent set oracle includes repaired/quiet/alias cases.
            expected={n for n,scope,repaired in gaps if repaired is None and scope in active}
            steps=[0]
            def bounded():
                steps[0]+=1;return steps[0]>5000
            db.set_progress_handler(bounded,200)
            actual=required_gap_census(db)
            db.set_progress_handler(None,0)
            self.assertEqual({r['id'] for r in actual},expected)
            self.assertLess(steps[0],5000)
