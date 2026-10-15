"""Run 377: use the real provider constructor under the existing governor."""
import os,tempfile,unittest
from contextlib import contextmanager
from unittest.mock import patch
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
from meme_machine.lanes.pons.provider import Rpc
from meme_machine.lanes.pons.provider_topology import PacedRpc
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.provider_topology import configured_rpc
from engineering.pons_history.fixtures import Tape

URL='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_RUN377_FIXTURE'

class SurvivorProviderTests(unittest.TestCase):
 @contextmanager
 def reporting_runtime(self,count=1):
  """Periodic reporting with synthetic, explicitly incomplete non-held history."""
  with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{
    'MM_DIRECTIONAL_SLEEVE_DB':td+'/sleeve','MM_DIRECTIONAL_COHORT_ID':'reporting'},clear=True):
   runtime=Runtime(td+'/survivor',10**18,'reporting',URL)
   runtime.rpc=Tape(candidates=0);runtime.deployments_verified=True
   runtime.now=lambda:1000
   for index in range(count):
    row=runtime.history.graduate('candidate-'+str(index),dict(at=100))
    row['complete']=False;runtime.history.save(row)
   try:yield runtime
   finally:runtime.close()

 def test_periodic_report_reuses_final_rows_and_preserves_native_accounting(self):
  from meme_machine.runtime.survivor_commit import handoff_ready
  with self.reporting_runtime(12) as runtime:
   def old_reporting():
    # Original four independent final-population reads, preserved as an oracle.
    protected=[r['id'] for r in runtime.history.rows()]
    safety=[r.get('position_safety',dict(at=0,evidence_current=False,
      blocker='pons_survivor_position_not_observed')) for r in runtime.history.rows() if r.get('position')]
    count=len(runtime.history.rows());handoff=handoff_ready(runtime.book,runtime.history.rows())
    return protected,dict(position_safety=safety,candidate_count=count,durable_handoff=handoff)
   with patch.object(runtime.history,'rows',wraps=runtime.history.rows) as rows:
    expected_protected,expected=old_reporting()
   self.assertEqual(rows.call_count,4)
   native_before=runtime.book.reconcile();proof_before=runtime.book.replay();sleeve_before=runtime.sleeve.reconcile()
   history_before=runtime.history.db.execute('SELECT * FROM candidates ORDER BY id').fetchall()
   maintain=runtime.attempts.maintain
   runtime.attempts._maintenance_due=2000  # The original maintenance guard still skips this turn.
   def maintenance(now,*,protected=()):
    captured=list(protected);protected_seen.extend(captured)
    return maintain(now,protected=captured)
   protected_seen=[]
   with patch.object(runtime.history,'rows',wraps=runtime.history.rows) as rows, \
     patch.object(runtime.attempts,'maintain',side_effect=maintenance), \
     patch.object(runtime.book,'replay',wraps=runtime.book.replay) as replay:
    result=runtime.step(admit=False)
   # Two independent early strategy/protection populations remain; only the
   # four adjacent final reads become one authenticated reporting population.
   self.assertEqual(rows.call_count,3);self.assertEqual(replay.call_count,1)
   self.assertEqual(protected_seen,expected_protected)
   self.assertEqual({key:result[key] for key in expected},expected)
   self.assertEqual(result['accounting'],native_before);self.assertEqual(result['accounting_replay'],proof_before)
   self.assertEqual(result['sleeve'],sleeve_before)
   self.assertEqual(runtime.history.db.execute('SELECT * FROM candidates ORDER BY id').fetchall(),history_before)
   self.assertTrue(result['accounting']['reconciled']);self.assertTrue(result['accounting_replay']['verified'])

 def test_final_reporting_population_follows_owned_discovery_mutations(self):
  with self.reporting_runtime() as runtime:
   events=[];original=runtime.history.rows
   def rows(*args,**kwargs):events.append('rows');return original(*args,**kwargs)
   def discover():
    # Controlled owner-side mutation at the actual discovery boundary. This
    # tests report ordering, not retirement eligibility or market performance.
    events.append('discover');row=runtime.history.get('candidate-0')
    row['state']='retired';runtime.history.save(row)
   with patch.object(runtime.history,'rows',side_effect=rows), \
     patch.object(runtime,'discover',side_effect=discover):
    result=runtime.step(admit=True)
   self.assertEqual(events,['rows','discover','rows','rows'])
   self.assertEqual(result['candidate_count'],0);self.assertEqual(result['position_safety'],[])
   self.assertTrue(result['durable_handoff']);self.assertEqual(runtime.history.rows(),[])

 def test_reporting_population_is_fresh_on_each_turn_and_still_authenticates_rows(self):
  with self.reporting_runtime() as runtime:
   first=runtime.step(admit=False);self.assertEqual(first['candidate_count'],1)
   row=runtime.history.graduate('later-candidate',dict(at=200));row['complete']=False;runtime.history.save(row)
   second=runtime.step(admit=False)
   self.assertEqual(second['candidate_count'],2);self.assertEqual(first['candidate_count'],1)
   runtime.history.db.execute("UPDATE candidates SET hash='corrupt' WHERE id='later-candidate'")
   with self.assertRaisesRegex(ValueError,'survivor_history_corruption'):runtime.step(admit=False)

 def test_survivor_constructs_governed_session_and_advances_discovery(self):
  with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{
    'MM_ROBINHOOD_READ_RPC_URL':URL,'MM_ROBINHOOD_STATE_DIR':td+'/provider',
    'MM_DIRECTIONAL_SLEEVE_DB':td+'/sleeve','MM_DIRECTIONAL_COHORT_ID':'run377'},clear=True):
   runtime=Runtime(td+'/survivor',10**18,'run377',URL)
   try:
    # Preserve the real configured/PacedRpc/Rpc constructors and chain guard;
    # only their transport is injected. No provider connection is opened.
    tape=Tape(candidates=0);tape.top=tape.grad
    def provider(endpoint,**kwargs):return configured_rpc(endpoint,transport=tape._read,**kwargs)
    with patch('meme_machine.lanes.pons.pons_survivor_runtime.configured_rpc',side_effect=provider):
     result=runtime.step(admit=True)
    self.assertIsNone(result['last_boundary'])
    self.assertEqual(runtime.history.get_meta('discovery_block'),tape.top)
    self.assertLessEqual(runtime.rpc.limit,200)
    self.assertLessEqual(runtime.rpc.per_scope,runtime.rpc.limit)
    self.assertTrue(runtime.rpc.canonical_authority)
    self.assertTrue(runtime.rpc.chain_verified)
    self.assertEqual(runtime.rpc.shared_admission.interval,.5)
    first=runtime.rpc;first.used=151
    with patch('meme_machine.lanes.pons.pons_survivor_runtime.configured_rpc',side_effect=provider):
     self.assertIsNone(runtime.step(admit=True)['last_boundary'])
    self.assertIsNot(first,runtime.rpc)
    self.assertTrue(runtime.rpc.chain_verified)
    self.assertEqual(runtime.book.reconcile()['open_positions'],0)
    self.assertTrue(runtime.sleeve.reconcile()['reconciled'])
   finally:runtime.close()
 def test_provider_still_rejects_original_invalid_bounds(self):
  with self.assertRaisesRegex(BoundaryError,'invalid_request_bounds'):
   Rpc(URL,limit=240,per_scope=220,retries=0)
