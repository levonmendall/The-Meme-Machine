"""Completed identity churn through the existing deterministic native lifecycle."""
import unittest
from certification.tests import test_survivor_candidate_progress as launcher

COMMON=r'''
import hashlib,json,sqlite3,shutil
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from certification.offline_tests import install_network_guard
from certification.archive_native import copy_snapshot
from certification.meteora_archive import compact,anchor
from certification.market_assurance import native_positions,continuity
from certification.autonomous_positions import no_new_native_entries
from certification.position_continuation import restore_meteora_strategy
from tests.test_dlmm_independent_accounting import DurableIndependentAccounting
from tests import solana_dlmm_independent_v1 as native
install_network_guard()
case=DurableIndependentAccounting();case.setUp()
case.path=Path(case.tmp.name)/'solana-dlmm-independent-v1-live.accounting.sqlite3';case.book=case.reopen()
callbacks=(native._build_position,native._advance_position,native._mark)
def window(index):return dict(campaign_id='meteora-churn-fixture',authorization_hash='a'*64,index=index)
def preserve(index):
 path=Path(case.tmp.name)/('preserved-'+str(index)+'.sqlite');records=[]
 copy_snapshot(case.path,path,records)
 assert not any(r.get('error_type') for r in records),records
 authority=dict(schema='preserved-native-prefix-v1',state_hash=str(index).zfill(64),
     snapshot_sha256=records[0]['sha256'],snapshot_name='meteora/'+case.path.name,
     artifact={'digest':'sha256:'+'b'*64},campaign_id=window(index)['campaign_id'],
     authorization_hash='a'*64,window_index=index)
 return path,authority
'''

CHURN=r'''
sizes=[];old=[]
try:
 for index in range(8):
  with patch('certification.campaign_state.active_window',return_value=window(index)):
   for n in range(2):
    # An approved immediate range exit discriminates identity retention without
    # repeating the full maximum-hold matrix for every completed identity.
    def exit_next(position,*args):return ['range_boundary'],{},native._mark(position),0
    with patch.object(native,'_segment_exit',side_effect=exit_next):
     result=case.run_lifecycle()
    assert result['complete'];old.append(result['lifecycle_id'])
  before=case.book.reconcile();economic=case.book.replay_economics(*callbacks)
  report=native_positions(Path(case.tmp.name),'meteora');path,authority=preserve(index)
  assert compact(case.book,path,authority,callbacks)
  case.book=case.reopen()
  assert case.book.reconcile()==before
  assert case.book.replay_economics(*callbacks)==economic
  after=native_positions(Path(case.tmp.name),'meteora')
  assert no_new_native_entries(report,after)
  for k in ('natural_entries','natural_settlements','natural_monitoring','complete_natural_lifecycles'):
   assert report[k]==after[k],(k,report[k],after[k])
  with closing(case.book.connect()) as db:
   assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==1
   assert not case.book._replay(db)['positions']
   assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
   db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
  sizes.append(case.path.stat().st_size)
  with patch('certification.campaign_state.active_window',return_value=window(index+1)):
   for identity in old:
    try:case.book.append(identity,'reserve',{'amount':1})
    except ValueError:pass
    else:raise AssertionError('archived entry replay')
 assert before['settled']==16
 assert max(sizes[2:])-min(sizes[2:])<=65536,sizes
 print('Meteora changing native lifecycle identities: 8 windows, 16 settlements, hot bytes',sizes)
finally:case.doCleanups()
'''

RECOVERY=r'''
try:
 seen=[0]
 def observe(*args):
  seen[0]+=1
  if seen[0]>1:raise SystemExit('after first mark')
  return case.observe(*args)
 with patch('certification.campaign_state.active_window',return_value=window(0)),patch.object(native,'_rotate',side_effect=lambda a,*args:a),patch.object(native,'_observe_window',side_effect=observe):
  try:native._lifecycle(None,case.entry['pool'],case.entry,case.features,case.policy,None,[],book=case.book)
  except SystemExit:pass
  else:raise AssertionError('cut missing')
 before=case.book.reconcile();recovered=restore_meteora_strategy(case.book,native)
 report=native_positions(Path(case.tmp.name),'meteora');path,authority=preserve(0)
 for kind in ('source_hash','economic_corruption','commit_rollback'):
  bad=dict(authority,snapshot_sha256='f'*64) if kind=='source_hash' else authority
  callbacks_used=(native._build_position,native._advance_position,lambda p:dict(native._mark(p),ending_sol_lamports=1)) if kind=='economic_corruption' else callbacks
  original=case.book.reconcile
  def cut(*args,**kwargs):
   if kwargs.get('db') is not None:raise SystemExit('before commit')
   return original(*args,**kwargs)
  try:
   with patch.object(case.book,'reconcile',side_effect=cut if kind=='commit_rollback' else original):
    compact(case.book,path,bad,callbacks_used)
  except (ValueError,SystemExit):pass
  else:raise AssertionError('cut not rejected '+kind)
  assert case.book.reconcile()==before
  with closing(case.book.connect()) as db:assert anchor(db,case.book.genesis) is None
 # Actual production constructor opens the exact restored main-file bytes;
 # only the supervisor receipt adapter is a fixture in this isolated check.
 shutil.copyfile(path,case.path)
 with patch('certification.preserved_checkpoint.authority',return_value=authority):
  case.book=type(case.book)(case.path,run_id='test',policy_hash=native.digest(case.policy),
      capital=1_000_000_000,economic_replay=callbacks)
 with closing(case.book.connect()) as db:assert anchor(db,case.book.genesis) is not None
 assert case.book.reconcile()==before
 restored=restore_meteora_strategy(case.book,native)
 assert restored==recovered,(restored,recovered)
 from certification.terminal_reconciliation import reconcile as native_reconcile
 proof=native_reconcile('meteora',case.path.parent)
 assert proof['verified'] and proof['durable_handoff'] and proof['open_positions']==1
 assert continuity(report,native_positions(Path(case.tmp.name),'meteora'))['status']=='pass'
 def exit_next(position,*args):return ['range_boundary'],{},native._mark(position),0
 with patch.object(native,'_rotate',side_effect=lambda a,*args:a),patch.object(native,'_observe_window',side_effect=case.observe),patch.object(native,'_segment_exit',side_effect=exit_next):
  result,_=native._position_lifecycle(None,case.entry['pool'],case.entry,case.features,case.policy,None,[],book=case.book,identity=restored['identity'],recovered=restored)
 assert result['complete'] and case.book.reconcile()['settled']==1
 assert case.book.replay_economics(*callbacks)['verified']
 assert native_reconcile('meteora',case.path.parent)['open_positions']==0
 print('Meteora preserved live tape/exit state, corruption refusal, atomic rollback and one resumed settlement passed')
finally:case.doCleanups()
'''

TERMINALS=r'''
try:
 with patch('certification.campaign_state.active_window',return_value=window(0)):
  cancelled=case.book.identity();case.book.append(cancelled,'reserve',{'amount':1000})
  assert case.book.recover_unfilled_reservations()==[cancelled]
  for reason in ('dlmm_add_liquidity_by_strategy2_mixed_with_swap_interval','temporary_unavailable'):
   def missing(*args):return dict(verified=False,reason=reason),None,None,None,None
   with patch.object(native,'_rotate',side_effect=lambda a,*args:a),patch.object(native,'_observe_window',side_effect=missing):
    result=native._lifecycle(None,case.entry['pool'],case.entry,case.features,case.policy,None,[],book=case.book)[0]
   assert not result['complete']
 live=result['lifecycle_id']
 for index in range(6):
  case.book.fail(live,'temporary_unavailable')
  before=case.book.reconcile();path,authority=preserve(index)
  assert compact(case.book,path,authority,callbacks)
  case.book=case.reopen();assert case.book.reconcile()==before
  with closing(case.book.connect()) as db:
   saved=anchor(db,case.book.genesis)
   assert list(saved['state']['positions'])==[live]
   assert len(saved['lifecycle_events'])==3
   assert saved['folded']['cancelled']==1 and saved['folded']['writeoffs']==1
  assert before['unsettled']==1 and before['stale_marks']==1 and before['reserved']>0
  assert restore_meteora_strategy(case.book,native)['identity']==live
 with closing(case.book.connect()) as db:
  db.execute("UPDATE events_archive SET hash=? WHERE id=1",('f'*64,))
 try:case.reopen()
 except ValueError as error:assert str(error)=='meteora_archive_integrity'
 else:raise AssertionError('corrupted prefix accepted')
 print('Meteora cancelled/writeoff totals conserved; unresolved exposure and original ID retained over six checkpoints')
finally:case.doCleanups()
'''


class MeteoraTerminalArchiveTests(unittest.TestCase):
    run_native=launcher.SurvivorCandidateProgressTests.run_native

    def test_completed_native_identity_churn_plateaus(self):
        print(self.run_native(COMMON+CHURN,lanes=('meteora',))['meteora'].strip())

    def test_live_exit_state_survives_checkpoint_and_failed_publication(self):
        self.run_native(COMMON+RECOVERY,lanes=('meteora',))

    def test_writeoffs_cancellations_and_unresolved_inventory_remain_truthful(self):
        self.run_native(COMMON+TERMINALS,lanes=('meteora',))
