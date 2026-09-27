"""Changing native Ramses settlements retain capital and active command replay."""
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from certification.tests import test_survivor_candidate_progress as launcher
from certification.tests import test_pons_window_archive as transport
from certification import campaign_state

COMMON=r'''
import hashlib,json,tempfile,shutil
from pathlib import Path
from unittest.mock import patch
from certification.offline_tests import install_network_guard
from certification.archive_native import copy_snapshot
from certification.ramses_archive import compact,anchor
from certification.lifecycle_identity import issue
from certification.market_assurance import native_positions,continuity
from certification.autonomous_positions import no_new_native_entries
from robinhood_research.ramses_campaign import CampaignBooks
from robinhood_research.ramses_strategy import USDG_ADDRESS,STRATEGY_DOMAIN
from robinhood_tests.test_ramses_strategy import RamsesStrategyTests
from robinhood_tests.test_ramses_continuous_campaign import screen
install_network_guard()
temp=tempfile.TemporaryDirectory();root=Path(temp.name)
fixture=RamsesStrategyTests();decision=fixture._decision()
capital=decision['freeze']['proposals'][0]['capital_employed']
campaign=CampaignBooks(root/'robinhood-ramses-extended-market.sqlite.campaign',screen([
 dict(token_y=USDG_ADDRESS,paper_capital_quote_raw=capital+1000)]))
book=campaign.ledger(USDG_ADDRESS)
def window(index):return dict(campaign_id='ramses-churn-fixture',authorization_hash='a'*64,index=index)
def populate(index,count):
 identities=[]
 with patch('certification.campaign_state.active_window',return_value=window(index)):
  for n in range(count):
   identity=issue('ramses:'+str(index)+':'+str(n));identities.append(identity);at=1000+index*3600+n*10
   book.reserve(identity,pool='pool:'+str(index)+':'+str(n),decision=decision,at=at);book.open(identity,at=at)
   book.checkpoint(identity,action='monitor',detail={'observed':n},at=at+1)
   book.checkpoint(identity,action='segment_close',detail={'segment':n},at=at+2)
   book.checkpoint(identity,action='rebalance',detail={'proposal_hash':'b'*64},at=at+3)
   position=book.settle(identity,pnl={'strategy_domain':STRATEGY_DOMAIN,'net_result_quote':n-2},at=at+4)
   campaign.record('natural_lifecycle',position)
 return identities
def preserve(index):
 path=root/('preserved-'+str(index)+'.sqlite');records=[];copy_snapshot(Path(book.path),path,records)
 assert not any(r.get('error_type') for r in records)
 return path,dict(schema='preserved-native-prefix-v1',state_hash=str(index).zfill(64),
  snapshot_sha256=records[0]['sha256'],snapshot_name='ramses/'+Path(book.path).parent.name+'/'+Path(book.path).name,
  artifact={'digest':'sha256:'+'b'*64},campaign_id=window(index)['campaign_id'],authorization_hash='a'*64,window_index=index)
'''

CHURN=r'''
sizes=[]
try:
 for index in range(12):
  identities=populate(index,8);before=campaign.reconcile();report=native_positions(campaign.root,'ramses')
  source,authority=preserve(index);assert compact(book,source,authority)
  assert campaign.reconcile()==before
  after=native_positions(campaign.root,'ramses');assert no_new_native_entries(report,after)
  for k in ('natural_entries','natural_settlements','natural_monitoring','natural_exits','complete_natural_lifecycles'):
   assert report[k]==after[k],(k,report[k],after[k])
  assert book.db.execute('SELECT COUNT(*) FROM ramses_strategy_position').fetchone()[0]==0
  assert book.db.execute('SELECT COUNT(*) FROM ramses_strategy_journal').fetchone()[0]==0
  with patch('certification.campaign_state.active_window',return_value=window(index+1)):
   for identity in identities:
    try:book.reserve(identity,pool='old',decision=decision,at=999999)
    except ValueError:pass
    else:raise AssertionError('archived reservation replay')
  campaign.close();campaign=CampaignBooks.recover(campaign.root);book=campaign.ledger(USDG_ADDRESS)
  assert campaign.reconcile()==before;sizes.append(Path(book.path).stat().st_size)
 assert before['position_count']==96 and before['by_quote_asset'][USDG_ADDRESS]['realized']==144
 assert max(sizes[2:])-min(sizes[2:])<=65536,sizes
 print('Ramses completed churn: 12 windows, 96 positions, exact P&L 144 quote units, hot SQLite bytes',sizes)
finally:campaign.close();temp.cleanup()
'''

RECOVERY=r'''
try:
 populate(0,2)
 with patch('certification.campaign_state.active_window',return_value=window(0)):
  live=issue('ramses:held');book.reserve(live,pool='held',decision=decision,at=2000);book.open(live,at=2000)
  command={'proposal_hash':'c'*64}
  book.checkpoint(live,action='segment_close',detail={'original_segment':1},at=2001)
  book.checkpoint(live,action='rebalance',detail=command,at=2002)
  book.checkpoint(live,action='monitor',detail={'later':True},at=2003)
 before=campaign.reconcile();held=book.position(live);report=native_positions(campaign.root,'ramses')
 source,authority=preserve(0);original=book.reconcile;calls=[0]
 def crash():
  calls[0]+=1
  if calls[0]==2:raise SystemExit('before commit')
  return original()
 try:
  with patch.object(book,'reconcile',side_effect=crash):compact(book,source,authority)
 except SystemExit:pass
 else:raise AssertionError('missing rollback cut')
 assert campaign.reconcile()==before and anchor(book.db) is None
 campaign.close();shutil.copyfile(source,book.path)
 with patch('certification.preserved_checkpoint.authority',return_value=authority):
  campaign=CampaignBooks.recover(campaign.root)
 book=campaign.books[USDG_ADDRESS];assert anchor(book.db) is not None
 assert campaign.reconcile()==before and book.position(live)==held
 assert continuity(report,native_positions(campaign.root,'ramses'))['status']=='pass'
 assert book.checkpoint(live,action='rebalance',detail=command,at=2002)==held
 assert book.position(live)['rebalances']==1
 book.settle(live,pnl={'strategy_domain':STRATEGY_DOMAIN,'unresolved_inventory':True},at=2004)
 source,authority=preserve(1);before=campaign.reconcile();held=book.position(live)
 assert compact(book,source,authority)
 assert campaign.reconcile()==before and book.position(live)==held
 assert held['reserved']>0 and held['status']=='unresolved'
 book.db.execute("UPDATE ramses_terminal_archive SET hash=?",('f'*64,))
 try:book.reconcile()
 except ValueError as error:assert str(error)=='ramses_terminal_archive_integrity'
 else:raise AssertionError('corruption accepted')
 print('Ramses atomic rollback, original recenter receipt, unresolved reserve and corruption rejection passed')
finally:campaign.close();temp.cleanup()
'''


class RamsesTerminalArchiveTests(unittest.TestCase):
    run_native=launcher.SurvivorCandidateProgressTests.run_native
    fixture=transport.PonsWindowArchive.fixture
    staged=transport.PonsWindowArchive.staged

    def test_changing_completed_positions_plateau(self):
        print(self.run_native(COMMON+CHURN,lanes=('ramses',))['ramses'].strip())

    def test_active_recenter_and_unresolved_reserve_survive_rollback_and_restore(self):
        self.run_native(COMMON+RECOVERY,lanes=('ramses',))

    def test_campaign_logs_leave_hot_capsule_only_after_verified_preservation(self):
        f=self.fixture();parent=None
        for index in range(6):
            folder=f.lanes/'ramses/robinhood-ramses-extended-market.sqlite.campaign';folder.mkdir(exist_ok=True)
            path=folder/'lifecycles.jsonl'
            path.write_text(''.join(json.dumps(dict(kind='natural_lifecycle',identity=f'{index}:{n}'))+'\n' for n in range(12)))
            output,runtime,artifact=self.staged(f,index)
            window=dict(f.window,index=index,workflow_run_id=index+1)
            if parent:window['parent_state_hash']=parent
            body=campaign_state.seal(output/'capsule',worktrees=f.lanes,run=runtime,window=window,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
            copied=output/'capsule/files/ramses'/folder.name
            self.assertFalse((copied/path.name).exists())
            self.assertEqual(json.loads((copied/'lifecycle-archive.json').read_text())['counts']['natural_lifecycle'],12*(index+1))
            self.assertEqual((artifact/'certification-native/hourly/ramses'/folder.name/path.name).read_bytes(),path.read_bytes())
            next_work=f.root/'next-lanes';next_run=f.root/'next-run'
            campaign_state.restore(output/'capsule',worktrees=next_work,run=next_run,expected_identity=f.identity,
                expected_state_hash=body['state_hash'],campaign_id=window['campaign_id'],prior_index=index,authorization_hash=window['authorization_hash'])
            shutil.rmtree(f.lanes);shutil.rmtree(f.run);next_work.rename(f.lanes);next_run.rename(f.run);parent=body['state_hash']

    def test_campaign_log_corruption_and_publication_cut_cannot_seal(self):
        f=self.fixture();folder=f.lanes/'ramses/robinhood-ramses-extended-market.sqlite.campaign';folder.mkdir()
        path=folder/'lifecycles.jsonl';path.write_text(json.dumps(dict(kind='terminal_boundary',reason='fixture'))+'\n')
        output,runtime,artifact=self.staged(f,0)
        original=Path.unlink
        def cut(path,*args,**kwargs):
            if path.name=='lifecycles.jsonl':raise SystemExit('after prefix write before seal')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',cut),self.assertRaises(SystemExit):
            campaign_state.seal(output/'cut',worktrees=f.lanes,run=runtime,window=f.window,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
        self.assertFalse((output/'cut/campaign-state.json').exists())
        self.assertTrue(path.exists())
        preserved=artifact/'certification-native/hourly/ramses'/folder.name/path.name
        preserved.write_text('corrupted')
        with self.assertRaises(ValueError):
            campaign_state.seal(output/'corrupt',worktrees=f.lanes,run=runtime,window=f.window,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
        self.assertFalse((output/'corrupt/campaign-state.json').exists())
