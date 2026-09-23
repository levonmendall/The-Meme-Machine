"""Exercise stopped-worker reconciliation against actual prepared native books."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT=r'''
import hashlib,json,sys,os,subprocess
from pathlib import Path
sys.path.append(sys.argv[1])
from certification.terminal_reconciliation import reconcile
lane,folder=sys.argv[2],Path(sys.argv[3])
source_root=Path.cwd()
def snapshot():
 return {str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest()
         for p in folder.rglob('*') if p.is_file() and not p.name.endswith('-shm')
         and not (p.name.endswith('-wal') and p.stat().st_size==0)}
try:reconcile(lane,folder)
except Exception:pass
else:raise AssertionError('missing native book accepted')
assert snapshot()=={},'read-only replay created missing native evidence'
if lane=='pump':
 from meme_machine.paper_accounting import PaperBook
 from meme_machine.pump_acceleration_strategy import policy_hash,STRATEGY_ID
 book=PaperBook(folder/'pump-acceleration-natural-prospective.accounting.sqlite3',
  run_id='fixture',lane=STRATEGY_ID,policy_hash=policy_hash(),initial=1000)
 book.reserve('fixture:one',400,10,{'fixture_kind':'synthetic_ledger_input'})
 book.db.close()
elif lane=='meteora':
 from meme_machine.dlmm_independent_accounting import PaperBook,NAMESPACE
 from tests import solana_dlmm_independent_v1 as strategy
 book=PaperBook(folder/'solana-dlmm-independent-v1-live.accounting.sqlite3',
  run_id='fixture',policy_hash=strategy.digest(strategy.load_policy()),capital=1_000_000_000)
 book.append(NAMESPACE+':fixture:one','reserve',{'amount':400},at_ns=10)
elif lane=='pons':
 from robinhood_research.pons_selective_capital import CohortCapital
 book=CohortCapital(folder/'pons-selective-continuation-v1-cohort/pons-selective-cohort-capital.sqlite',1000)
 book.reserve('one',400,at=10,decision_hash='fixture',trial_path=folder/'missing-trial.sqlite')
else:
 from robinhood_research.ramses_strategy_ledger import RamsesStrategyLedger
 from robinhood_research.ramses_strategy import POLICY_HASH
 from robinhood_tests.test_ramses_capital_replay import decision
 base=folder/'robinhood-ramses-extended-market.sqlite.campaign';base.mkdir()
 (base/'capital-manifest.json').write_text(json.dumps({'policy_hash':POLICY_HASH,
  'genesis_by_quote_asset':{'synthetic_quote':1000}}))
 book=RamsesStrategyLedger(base/'synthetic_quote.sqlite',paper_capital=1000,quote_asset='synthetic_quote')
 book.reserve('one',pool='fixture',decision=decision(400),at=10);book.db.close()
os.chdir(sys.argv[1])  # Match the actual supervisor launch directory.
before=snapshot();receipt=reconcile(lane,folder)
cli=subprocess.run([sys.executable,str(Path(sys.argv[1])/'certification/terminal_reconciliation.py'),
 '--lane',lane,'--root',str(folder),'--source-root',str(source_root)],capture_output=True,text=True)
assert json.loads(cli.stdout)['verified']==receipt['verified'],cli.stdout+cli.stderr
assert snapshot()==before,'terminal reconciliation mutated native evidence'
assert receipt['open_positions']==1,receipt
if lane=='pons':
 assert receipt['verified'] is False,'unobserved native commit must fail closed'
else:assert receipt['verified'] is True,receipt
accounting=receipt['accounting']
reserved=(accounting['by_quote_asset']['synthetic_quote']['committed'] if lane=='ramses' else accounting['reserved'])
assert reserved==400,(lane,reserved)
print(json.dumps({'lane':lane,'read_only':True,'reserve_retained':reserved,'open_positions':1,
 'verified':receipt['verified'],'missing_book_not_created':True}))
'''


class NativeTerminalReconciliationTests(unittest.TestCase):
    def test_restored_pons_relative_trial_paths_replay_without_journal_mutation(self):
        roots=os.environ.get('MM_TEST_LANE_WORKTREES')
        if not roots:self.skipTest('requires prepared native lane sources')
        integration=Path(__file__).resolve().parents[2]
        script=r'''
import hashlib,os,shutil,sys,tempfile
from pathlib import Path
sys.path.append(sys.argv[1])
from certification.terminal_reconciliation import reconcile
from robinhood_research.evidence import Store,digest
from robinhood_research.pons_selective_capital import CohortCapital
from robinhood_research.pons_selective_continuation import POLICY_HASH
from robinhood_research.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
from robinhood_tests.test_pons_partial_accounting import PartialAccountingTests
with tempfile.TemporaryDirectory() as td:
 root=Path(td);original=root/'original';original.mkdir();os.chdir(original)
 folder=Path('pons-selective-continuation-v1-cohort');folder.mkdir()
 trial=folder/'trial-000.sqlite';store=Store(trial)
 guard=CohortCapital(folder/'pons-selective-cohort-capital.sqlite',1000)
 paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=POLICY_HASH,on_commit=guard.observe)
 decision=PartialAccountingTests().features(10)
 guard.reserve('x',120,at=10,decision_hash=digest(decision),trial_path=trial)
 paper.reserve('x',market='m',amount=100,gas_budget=20,now=10,features=decision)
 position=paper.advance('x',now=11,action='cancel',cancel_reason='synthetic_relocation_fixture');guard.settle('x',position,at=11);store.close()
 restored=root/'restored';shutil.copytree(original,restored);os.chdir(sys.argv[1])
 def snapshot():return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*.sqlite')}
 before=snapshot();result=reconcile('pons',restored)
 assert result['verified'] and result['open_positions']==0,result
 assert result['accounting']['native_observation_complete']
 assert snapshot()==before,'read-only relocation changed journal bytes'
 (restored/trial).unlink()
 assert reconcile('pons',restored)['verified'] is False,'missing restored native trial accepted'
print('Restored native Pons paths verified read-only; missing trial still fails closed')
'''
        result=subprocess.run([sys.executable,'-c',script,str(integration)],
            cwd=Path(roots)/'pons',text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_reserved_capital_survives_cancellation_without_inventing_settlement(self):
        roots=os.environ.get('MM_TEST_LANE_WORKTREES')
        if not roots:self.skipTest('requires prepared native lane sources; required in full certification workflow')
        integration=Path(__file__).resolve().parents[2]
        for lane in ('pump','pons','meteora','ramses'):
            with self.subTest(lane=lane),tempfile.TemporaryDirectory() as tmp:
                result=subprocess.run([sys.executable,'-c',SCRIPT,str(integration),lane,tmp],
                    cwd=Path(roots)/lane,text=True,capture_output=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertEqual(json.loads(result.stdout)['reserve_retained'],400)


if __name__=='__main__':unittest.main()
