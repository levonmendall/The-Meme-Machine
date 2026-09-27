"""Current-strategy sleeve churn reuses native books and preserved capsules."""
import json,os,shutil,sqlite3,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
from certification import campaign_state as transfer
from certification.tests import test_robinhood_window_archive as helpers
from certification.journal import canonical

POPULATE=r'''
import json,os,sys
from pathlib import Path
from unittest.mock import patch
from certification.offline_tests import install_network_guard
install_network_guard()
from meme_machine.paper_accounting import PaperBook
from meme_machine.pump_acceleration_strategy import STRATEGY_ID,policy_hash
from certification.directional_sleeve import open_sleeve,native_terminal
from certification.lifecycle_identity import issue
root=Path(sys.argv[1]);window=json.loads(sys.argv[2]);index=window['index'];os.chdir(root)
os.environ.update(MM_DIRECTIONAL_SLEEVE_DB=str(root/'directional-sleeve.sqlite'),MM_DIRECTIONAL_COHORT_ID='original-paper-books')
book=PaperBook(root/'pump-acceleration-natural-prospective.accounting.sqlite3',run_id='current',lane=STRATEGY_ID,policy_hash=policy_hash(),initial=1000000)
sleeve=open_sleeve('pump',1000000)
if index==0:
 survivor=next(s for s in sleeve.identity['policies'] if 'survivor' in s)
 sleeve.reserve('survivor-held',strategy=survivor,amount=200,at=0)
with patch('certification.campaign_state.active_window',return_value=window):
 for n in range(8):
  at=index*3600+n*10;identity=issue('current:'+str(index)+':'+str(n))
  from meme_machine.pump_acceleration_paper import PumpAccelerationPaperLifecycle
  from tests.test_pump_acceleration_paper import qualification
  life=PumpAccelerationPaperLifecycle(book=book,lifecycle_id=identity)
  life.reserve(qualification(),100,at)
  with life.sleeve.commit_fence(identity):life.fill(100,100,at+1,'pump.fun')
  life.mark(130,at+2,80);life.harvest(25,30,at+3)
  if index==0 and n==0:
   book.checkpoint_runtime(identity,'fill_context',{'original':True})
   life.sleeve.close()
  else:
   assert life.mark(80,at+4,80)['exit_reason']
   life.settle(80,at+5)
print(json.dumps(sleeve.reconcile()));sleeve.close();book.close()
'''

class CurrentSleeveArchive(unittest.TestCase):
    def test_current_changing_terminal_identities_plateau_with_live_reservation_unchanged(self):
        helper=helpers.RobinhoodWindowArchive();f,pons,ramses=helper.initialize();self.addCleanup(helper.doCleanups)
        roots=os.environ.get('MM_TEST_LANE_WORKTREES')
        if not roots:self.skipTest('requires canonical native lanes')
        native=Path(roots)/'pump';(f.lanes/'pump/directional-sleeve.sqlite').unlink();sizes=[];last=None
        for index in range(6):
            lane=f.lanes/'pump';(lane/'meme_machine').symlink_to(native/'meme_machine',target_is_directory=True)
            window=dict(f.window,index=index,workflow_run_id=index+1)
            if last:window['parent_state_hash']=last
            run=subprocess.run([sys.executable,'-c',POPULATE,str(lane),canonical(window)],cwd=native,
                env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2])),capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr);before=json.loads(run.stdout)
            output,runtime,artifact=helper.staged(f,index)
            body=transfer.seal(output/'capsule',worktrees=f.lanes,run=runtime,window=window,terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
            self.assertEqual(body['current_sleeve_handoff']['retired'],7 if not index else 8)
            path=output/'capsule/files/pump/directional-sleeve.sqlite'
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM sleeve_positions').fetchone()[0],2)
                held=json.loads(db.execute("SELECT body FROM sleeve_positions WHERE id!='survivor-held'").fetchone()[0])
                survivor=json.loads(db.execute("SELECT body FROM sleeve_positions WHERE id='survivor-held'").fetchone()[0])
                self.assertEqual((survivor['held'],survivor['status']),(200,'reserved'))
                self.assertEqual(held['held'],100)
                prefix=json.loads(db.execute('SELECT body FROM sleeve_archive').fetchone()[0])
                self.assertEqual(prefix['folded']['positions'],(index+1)*8-1)
                self.assertEqual(prefix['folded']['realized'],((index+1)*8-1)*10)
            next_work=f.root/'next-lanes';next_run=f.root/'next-run'
            transfer.restore(output/'capsule',worktrees=next_work,run=next_run,expected_identity=f.identity,expected_state_hash=body['state_hash'],campaign_id=window['campaign_id'],prior_index=index,authorization_hash=window['authorization_hash'])
            sizes.append((next_work/'pump/directional-sleeve.sqlite').stat().st_size)
            shutil.rmtree(f.lanes);shutil.rmtree(f.run);next_work.rename(f.lanes);next_run.rename(f.run);last=body['state_hash']
        self.assertLessEqual(max(sizes[2:])-min(sizes[2:]),8192,sizes)
        code=r'''
import json,os,sys
from pathlib import Path
from meme_machine.paper_accounting import PaperBook
from meme_machine.pump_acceleration_paper import PumpAccelerationPaperLifecycle
from meme_machine.pump_acceleration_strategy import STRATEGY_ID,policy_hash
from certification.directional_sleeve import bind_pump_recovered_allocation
root=Path(sys.argv[1]);os.environ.update(MM_DIRECTIONAL_SLEEVE_DB=str(root/'directional-sleeve.sqlite'),MM_DIRECTIONAL_COHORT_ID='original-paper-books')
book=PaperBook(root/'pump-acceleration-natural-prospective.accounting.sqlite3',run_id='current',lane=STRATEGY_ID,policy_hash=policy_hash(),initial=1000000)
assert book.db.execute('SELECT COUNT(*) FROM positions').fetchone()[0]==1
assert book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0]==0
identity=book.db.execute('SELECT id FROM positions').fetchone()[0]
life=PumpAccelerationPaperLifecycle.restore(book,identity);bind_pump_recovered_allocation(book,life)
assert life.position.partial_harvest_taken and life.position.tokens==75 and life.position.peak_return_bps==3000
before=book.reconcile();life.sleeve.close();book.close()
'''
        result=subprocess.run([sys.executable,'-c',code,str(f.lanes/'pump')],cwd=native,
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2])),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        print('Current Pump sleeve: 47 acknowledged terminals folded, live hold unchanged; hot bytes',sizes)
