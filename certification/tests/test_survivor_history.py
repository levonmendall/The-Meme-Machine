"""Incremental history has no provider and never fills unknown observations."""
from pathlib import Path
import tempfile,unittest
from certification.survivor_history import History
from certification.survivor_commit import handoff_ready

class HistoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'history')
  self.h=History(self.path,policy='frozen',maximum_candidates=2)
 def tearDown(self):self.h.close();self.tmp.cleanup()
 def graduate(self,i='a'):return self.h.graduate(i,dict(at=1,identity=i))
 def test_same_graduation_and_conflicting_lineage(self):
  self.graduate();self.assertEqual(len(self.h.rows()),1);self.graduate()
  with self.assertRaisesRegex(ValueError,'conflicting'):self.h.graduate('a',dict(at=2,identity='a'))
 def test_point_in_time_extrema_survive_same_second_and_restart(self):
  self.graduate();self.h.append('a',through=3,events=[],points=[(2,'10'),(2,'8'),(2,'9'),(3,'11')],complete=True)
  self.h.close();self.h=History(self.path,policy='frozen',maximum_candidates=2)
  points,_=self.h.facts('a',2)
  self.assertEqual(points,[dict(at=2,price='9',low='8',high='10')])
 def test_gaps_are_not_reconstructed_from_later_evidence(self):
  self.graduate();self.h.append('a',through=3,events=[],points=[],complete=False)
  self.h.append('a',through=4,events=[],points=[(4,'10')],complete=True)
  self.assertFalse(self.h.get('a')['complete'])
 def test_bounded_active_set_retains_identity_tombstone(self):
  a=self.graduate();self.graduate('b')
  with self.assertRaisesRegex(ValueError,'capacity'):self.graduate('c')
  self.h.retire(a);self.graduate('c')
  self.assertEqual(len(self.h.rows()),2);self.assertEqual(self.h.get('a')['state'],'retired')
  self.assertEqual(len(self.h.rows(include_retired=True)),3)
 def test_all_lifecycle_states_reopen_exactly(self):
  row=self.graduate()
  for stage in ('aging','survivor','trend_eligible','reset','reset_or_base','base','continuation_watch',
                'breakout_watch','qualified','reserved','filled','runner','settled'):
   row['state']=stage;self.h.save(row);self.h.close();self.h=History(self.path,policy='frozen')
   self.assertEqual(self.h.get('a'),row)
 def test_pre_reservation_controller_cannot_handoff(self):
  class Book:
   def _load(self,i):raise ValueError('missing')
  self.assertFalse(handoff_ready(Book(),[dict(position='pending')]))
  self.assertTrue(handoff_ready(Book(),[dict(position=None)]))
