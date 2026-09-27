"""Both production constructors consume verified snapshot receipts before work.

This isolates constructor ordering and identity binding. Receipt fixtures are
made from exact SQLite backups; full artifact transport has separate coverage.
No provider or strategy observation is fabricated as market evidence.
"""
import unittest
from certification.tests import test_survivor_candidate_progress as launcher

SCRIPT=r'''
import json,os,shutil,tempfile
from pathlib import Path
from unittest.mock import MagicMock,patch
from certification.offline_tests import install_network_guard
from certification.archive_native import copy_snapshot
from certification.campaign_state import identity as source_identity
from certification.lifecycle_identity import issue
from certification.journal import digest
install_network_guard()
if LANE=='pump':
 from meme_machine import pumpswap_survivor_runtime as native
 strategy=native.STRATEGY_ID;folder='pump-survivor';transport='RuntimeEvidence'
else:
 from robinhood_research import pons_survivor_runtime as native
 strategy=native.STRATEGY_VERSION;folder='pons-selective-continuation-v1-cohort/pons-survivor';transport='Plane'
with tempfile.TemporaryDirectory() as td:
 root=Path(td);hot=root/'window0';(hot/folder).mkdir(parents=True)
 identity=source_identity();capital=1000
 os.environ.update(MM_DIRECTIONAL_COMPOSITE_REQUIRED='1',MM_DIRECTIONAL_COHORT_ID='fixture',
     MM_CERTIFICATION_RUN_ID='run',MM_DIRECTIONAL_SLEEVE_DB=str(hot/'directional-sleeve.sqlite'))
 window=dict(campaign_id='constructor-fixture',authorization_hash='a'*64,index=0,native_run_id='run',workflow_run_id=1)
 claim=dict(schema='autonomous-paper-window-claim-v1',identity=identity,
     campaign_id=window['campaign_id'],authorization_hash=window['authorization_hash'],
     window=dict(window,entry_authority=True))
 claim_path=root/'autonomous-window-claim.json';claim_path.write_text(json.dumps(claim))
 os.environ['MM_AUTONOMOUS_WINDOW_CLAIM']=str(claim_path)
 with patch.object(native,transport,MagicMock()):
  runtime=native.Runtime(hot/folder,capital,'run',2 if LANE=='pump' else 'offline')
  row=runtime.history.graduate('terminal',dict(at=1))
  candidate=runtime.sleeve.observe('terminal',strategy=strategy,at=1,state='qualified',evidence={},regime={})
  entry=issue('run:terminal')
  runtime.sleeve.reserve(entry,strategy=strategy,amount=100,at=1,candidate='terminal',generation=1,regime={})
  runtime.book.reserve(entry,100,1,{'candidate':'terminal'})
  with runtime.sleeve.commit_fence(entry):pass
  runtime.book.transition(entry,'filled',2,amount=100,tokens=100,evidence={'execution':{'gas':1}})
  runtime.book.transition(entry,'partial_harvest',3,amount=40,tokens=25,evidence={'execution':{'gas':1}})
  runtime.book.transition(entry,'settled',4,amount=80,evidence={'execution':{'gas':1}})
  position=runtime.book._load(entry)
  runtime.sleeve.release(entry,pnl=position['realized'],at=4,terminal_hash=digest(position),native_verified=True)
  runtime.history.retire(row,expired_before=5)
  before=runtime.book.reconcile();shared=runtime.sleeve.reconcile();runtime.close()
  preserved=root/'preserved';restored=root/'window1';snapshots={}
  for relative in (folder+'/paper.sqlite',folder+'/history.sqlite','directional-sleeve.sqlite'):
   records=[];copy_snapshot(hot/relative,preserved/relative,records)
   assert not any(r.get('error_type') for r in records),records
   snapshots[LANE+'/'+relative]=records[0]['sha256']
   (restored/relative).parent.mkdir(parents=True,exist_ok=True)
   shutil.copyfile(preserved/relative,restored/relative)
  shutil.rmtree(hot)
  receipt=dict(identity=identity,entry_authority=False,state_hash='f'*64,window=window,
      ledger_snapshots={k:v for k,v in snapshots.items() if not k.endswith('history.sqlite')},
      history_snapshots={k:v for k,v in snapshots.items() if k.endswith('history.sqlite')})
  receipt_path=root/'restored-campaign-state.json';receipt_path.write_text(json.dumps(receipt))
  claim['previous']=dict(window,state_hash=receipt['state_hash'],artifact={'digest':'sha256:'+'b'*64})
  claim['window'].update(index=1,workflow_run_id=2);claim_path.write_text(json.dumps(claim))
  os.environ.update(MM_AUTONOMOUS_STATE_RECEIPT=str(receipt_path),
      MM_DIRECTIONAL_SLEEVE_DB=str(restored/'directional-sleeve.sqlite'))
  runtime=native.Runtime(restored/folder,capital,'run',2 if LANE=='pump' else 'offline')
  assert runtime.book.reconcile()==before and runtime.sleeve.reconcile()==shared
  assert runtime.book.db.execute('SELECT COUNT(*) FROM positions').fetchone()[0]==0
  assert runtime.sleeve.db.execute('SELECT COUNT(*) FROM sleeve_candidates').fetchone()[0]==0
  assert runtime.history.get('terminal') is None
  try:runtime.book.reserve(entry,100,3600,{})
  except ValueError:pass
  else:raise AssertionError('old issued identity admitted')
  assert issue('run:new')!=entry
  runtime.close()
print(LANE+' actual constructor folds terminal projections and rejects predecessor reentry')
'''


class SurvivorTerminalNativeTests(unittest.TestCase):
    run_native=launcher.SurvivorCandidateProgressTests.run_native

    def test_native_survivor_startup_from_exact_preserved_snapshots(self):
        self.run_native(SCRIPT)
