"""Native durable lifecycle commits precede shared evidence pin consumption."""
import unittest
from certification.tests import test_survivor_candidate_progress as launcher

METEORA=r'''
from pathlib import Path
from unittest.mock import patch
from tests.test_dlmm_independent_accounting import DurableIndependentAccounting
from tests import solana_dlmm_independent_v1 as native
from meme_machine.solana_evidence_plane import EvidenceWriter
from meme_machine.solana_evidence_service import FinalizedFence
from meme_machine.solana_evidence_runtime import RuntimeEvidence,METEORA_SCOPE
from certification.position_continuation import restore_meteora_strategy
from meme_machine.solana_evidence_plane import IntervalProof,digest
def proof(lo,hi,scope):
 return IntervalProof(scope,lo,hi,'alchemy_finalized_stream','a'*64,dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=hi,lineage_hash=digest([scope,lo,hi])),100)
for cut in ('before_mark_commit','after_mark_commit','after_ack'):
 case=DurableIndependentAccounting();case.setUp()
 path=Path(case.tmp.name)/'shared'
 writer=EvidenceWriter(path,clock=lambda:1_800_000_000)
 fence=FinalizedFence(writer,endpoint_identity='a'*64,decoders={})
 plane=RuntimeEvidence(path,owner='meteora',clock=lambda:1_800_000_000,command=fence.command)
 writer.ingest([],proof=proof(case.entry['slot'],case.entry['slot']+10,scope=METEORA_SCOPE))
 append=case.book.append;advance=plane.advance_interest
 def interrupted_append(identity,action,data,**kw):
  if action=='mark' and cut=='before_mark_commit':raise SystemExit(cut)
  result=append(identity,action,data,**kw)
  if action=='mark' and cut=='after_mark_commit':raise SystemExit(cut)
  return result
 def interrupted_ack(*args,**kw):
  result=advance(*args,**kw)
  if cut=='after_ack':raise SystemExit(cut)
  return result
 try:
  with patch.object(native,'EVIDENCE_PLANE',plane),patch.object(case.book,'append',side_effect=interrupted_append),patch.object(plane,'advance_interest',side_effect=interrupted_ack):
   try:case.run_lifecycle()
   except SystemExit:pass
   else:raise AssertionError('missing '+cut)
  case.book=case.reopen();recovered=restore_meteora_strategy(case.book,native)
  expected=0 if cut=='before_mark_commit' else 300
  assert recovered['elapsed']==expected,(cut,recovered['elapsed'])
  owner='meteora:position:'+recovered['identity']
  pin=lambda:writer.db.execute('SELECT lower_slot,lifecycle,active FROM interests WHERE owner=?',(owner,)).fetchone()
  assert pin()==(case.entry['slot']+(cut=='after_ack'),'open',1),(cut,pin())
  def exit_at_next_segment(position,*args):return ['range_boundary'],{},native._mark(position),0
  with patch.object(native,'EVIDENCE_PLANE',plane),patch.object(native,'_rotate',side_effect=lambda a,*args:a),patch.object(native,'_observe_window',side_effect=case.observe),patch.object(native,'_segment_exit',side_effect=exit_at_next_segment):
   result,_=native._position_lifecycle(None,case.entry['pool'],case.entry,case.features,case.policy,None,[],book=case.book,identity=recovered['identity'],recovered=recovered)
  assert result['complete'] and result['realized_hold_seconds']==expected+300
  assert pin()[2]==0
  replay=case.reopen().replay_economics(native._build_position,native._advance_position,native._mark)
  assert replay['verified'],replay
  final=case.reopen().reconcile()
  assert final['settled']==1 and final['open_positions']==0 and final['reserved']==0
  assert writer.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 finally:
  plane.close();writer.close();case.doCleanups()
for terminal in ('cancelled','written_off','unresolved'):
 case=DurableIndependentAccounting();case.setUp()
 writer=EvidenceWriter(Path(case.tmp.name)/'shared',clock=lambda:1_800_000_000)
 fence=FinalizedFence(writer,endpoint_identity='a'*64,decoders={})
 plane=RuntimeEvidence(writer.path,owner='meteora',command=fence.command)
 try:
  with patch.object(native,'EVIDENCE_PLANE',plane):
   if terminal=='cancelled':
    with patch.object(native,'_build_position',side_effect=ValueError('synthetic_bad_entry')):
     try:case.run_lifecycle()
     except ValueError:pass
     else:raise AssertionError('missing failed fill')
   else:
    reason='dlmm_add_liquidity_by_strategy2_mixed_with_swap_interval' if terminal=='written_off' else 'synthetic_missing_evidence'
    with patch.object(native,'_recover_position_observation',return_value=(dict(verified=False,reason=reason),None,None,None,None,[])):
     case.run_lifecycle()
  pins=writer.db.execute('SELECT active FROM interests').fetchall()
  assert pins==[(int(terminal=='unresolved'),)],(terminal,pins)
 finally:plane.close();writer.close();case.doCleanups()
case=DurableIndependentAccounting();case.setUp()
writer=EvidenceWriter(Path(case.tmp.name)/'shared',clock=lambda:1_800_000_000)
fence=FinalizedFence(writer,endpoint_identity='a'*64,decoders={})
plane=RuntimeEvidence(writer.path,owner='meteora',command=fence.command)
try:
 orphan=case.book.identity();cancelled=case.book.identity()
 case.book.append(cancelled,'reserve',dict(amount=1000))
 case.book.recover_unfilled_reservations()
 for identity in (orphan,cancelled,'foreign:book:position'):
  plane.interest(METEORA_SCOPE,owner='meteora:position:'+identity,lower_slot=1,addresses=['pool'],lifecycle='open',priority=0)
 with patch.object(native,'EVIDENCE_PLANE',plane):
  native._recover_position_evidence(case.reopen());native._recover_position_evidence(case.reopen())
 active=[r[0] for r in writer.db.execute('SELECT owner FROM interests WHERE active=1')]
 assert active==['meteora:position:foreign:book:position'],active
 assert case.reopen().reconcile()['cash']==1_000_000_000
finally:plane.close();writer.close();case.doCleanups()
print('Meteora native tape commits, pin acknowledgement, crash recovery and one settlement passed')
'''

class NativeEvidenceCheckpointTests(unittest.TestCase):
    run_native=launcher.SurvivorCandidateProgressTests.run_native
    def test_meteora_native_commit_acknowledgement_crash_boundaries(self):
        self.run_native(METEORA,lanes=('meteora',))
