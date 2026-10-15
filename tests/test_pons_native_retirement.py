"""Ordinary Pons terminal retirement across native books and restart cuts."""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import json,os,sqlite3,tempfile,unittest
from unittest.mock import patch
from meme_machine.lanes.pons.evidence import Store,digest,canonical
from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
from meme_machine.lanes.pons import pons_selective_cohort as cohort
from meme_machine.runtime import pons_terminal_archive as archive,survivor_terminal_archive
from meme_machine.runtime.lifecycle_identity import issue
from meme_machine.runtime.directional_sleeve import open_sleeve
from meme_machine.runtime.robinhood.plane import Plane

class PonsNativeRetirementTests(unittest.TestCase):
    def fixture(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);environment=patch.dict(os.environ,{
            'MM_PAPER_EPOCH':'offline-native-retirement','MM_DIRECTIONAL_SLEEVE_DB':str(root/'sleeve.sqlite'),
            'MM_DIRECTIONAL_COHORT_ID':'same-native-books'})
        environment.start();self.addCleanup(environment.stop)
        bindings=patch.multiple(cohort,ROOT=root,STRATEGY_CAPITAL_QUOTE=1_000_000)
        bindings.start();self.addCleanup(bindings.stop)
        plane=Plane(root/'plane.sqlite');self.addCleanup(plane.close)
        result=dict(qualifiers=[],lifecycles=[],candidate_plane_path=str(plane.path))
        capital=CohortCapital(root/'pons-selective-cohort-capital.sqlite',1_000_000)
        return root,plane,result,capital

    def add_trial(self,root,result,capital,index,*,at=100,settle=True):
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        fixture=PartialAccountingTests();identity=issue('trial:'+str(index));path=root/('trial-'+str(index)+'.sqlite')
        features=fixture.features(at);features['token_age_seconds']=100
        with closing(Store(path)) as store:
            book=SelectivePaper(store,STRATEGY_NAMESPACE,1_000_000,delay=1,natural_policy_hash=POLICY_HASH,
                clock_ns=lambda:at*10**9,on_commit=capital.observe)
            capital.reserve(identity,120,at=at,decision_hash=digest(features),trial_path=path)
            position=book.reserve(identity,market='m',amount=100,gas_budget=20,now=at,features=features)
            if settle:
                book.advance(identity,now=at+1,action='entry',quote=fixture.quote(at+1,'buy',100,1000))
                book.advance(identity,now=at+2,action='exit_intent',exit_tokens=500)
                book.advance(identity,now=at+3,action='exit',quote=fixture.quote(at+3,'sell',500,70))
                book.advance(identity,now=at+4,action='exit_intent')
                position=book.advance(identity,now=at+5,action='exit',quote=fixture.quote(at+5,'sell',500,82))
                capital.settle(identity,position,at=at+5)
        result['qualifiers'].append(dict(index=index,curve='curve:'+str(index),vector=features))
        result['lifecycles'].append(dict(index=index,curve='curve:'+str(index),lifecycle_id=identity,
            status='settled' if settle else 'reserved',final_position=position,
            reconciliation={'open_exposure':0 if settle else 120},realized_pnl_quote=position.get('pnl',0)))
        return identity,path

    def save(self,plane,result):plane.checkpoint('pons_cohort',{'result':deepcopy(result),'cursor':27,'phase':'running'})

    def test_expired_terminal_churn_preserves_live_recent_entries_and_exact_capital(self):
        root,plane,result,capital=self.fixture();live,live_path=self.add_trial(root,result,capital,0,settle=False)
        recent,recent_path=self.add_trial(root,result,capital,1,at=1900)
        sizes=[]
        for cycle in range(3):
            for index in range(2+cycle*8,10+cycle*8):self.add_trial(root,result,capital,index)
            before=capital.reconcile()
            with closing(open_sleeve('pons',1_000_000)) as sleeve:sleeve_before=sleeve.reconcile()
            self.save(plane,result)
            with patch.object(archive.time,'time',return_value=2000):archive.retire_controller(result)
            self.assertEqual(capital.reconcile(),before)
            with closing(open_sleeve('pons',1_000_000)) as sleeve:self.assertEqual(sleeve.reconcile(),sleeve_before)
            self.assertTrue(live_path.exists());self.assertTrue(recent_path.exists())
            self.assertEqual([q['index'] for q in result['qualifiers']],[0,1])
            self.assertEqual(len(list(root.glob('trial-*.sqlite'))),2)
            self.assertEqual(archive.controller_anchor(result)['qualifiers'],8*(cycle+1))
            with closing(capital._connect()) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM capital_positions').fetchone()[0],2)
                self.assertNotIn('retirement_pending',archive.anchor(db))
            saved=plane.checkpoint_read('pons_cohort')['result'];self.assertEqual(saved,result)
            sizes.append(sum(p.stat().st_size for p in root.glob('*.sqlite')))
        self.assertLessEqual(max(sizes)-min(sizes),65536,sizes)
        self.assertEqual(capital.reconcile()['reserved'],120)
        self.assertEqual(archive.controller_anchor(result)['next_index'],26)

    def test_restart_cuts_and_corrupt_pending_receipt_preserve_original_books(self):
        for cut in ('before_sleeve','before_controller'):
            with self.subTest(cut=cut):
                root,plane,result,capital=self.fixture();identity,path=self.add_trial(root,result,capital,0)
                before=capital.reconcile();self.save(plane,result)
                target=patch.object(survivor_terminal_archive,'_sleeve_commit',side_effect=SystemExit('injected_cut')) if cut=='before_sleeve' else patch.object(Plane,'checkpoint',side_effect=SystemExit('injected_cut'))
                with patch.object(archive.time,'time',return_value=2000),target:
                    with self.assertRaisesRegex(SystemExit,'injected_cut'):archive.retire_controller(result)
                self.assertTrue(path.exists());self.assertEqual(capital.reconcile(),before)
                with closing(capital._connect()) as db:self.assertIn('retirement_pending',archive.anchor(db))
                result=plane.checkpoint_read('pons_cohort')['result']
                with patch.object(archive.time,'time',return_value=2000):archive.retire_controller(result)
                self.assertFalse(path.exists());self.assertEqual(capital.reconcile(),before)
                with closing(open_sleeve('pons',1_000_000)) as sleeve:
                    self.assertIsNone(sleeve.get(identity));self.assertEqual(sleeve.reconcile()['reserved'],0)
                saved=deepcopy(result)
                with patch.object(archive.time,'time',return_value=2000):archive.retire_controller(result)
                self.assertEqual(result,saved);self.assertEqual(capital.reconcile(),before)
                with self.assertRaisesRegex(Exception,'archived'):
                    capital.reserve(identity,120,at=2000,decision_hash='old',trial_path=path)
        # Recompute the outer row digest: the independently checked pending-plan
        # digest must still reject a forged retirement before changing any book.
        root,plane,result,capital=self.fixture();identity,path=self.add_trial(root,result,capital,0)
        self.save(plane,result);before=capital.reconcile()
        with patch.object(archive.time,'time',return_value=2000),patch.object(survivor_terminal_archive,'_sleeve_commit',side_effect=SystemExit):
            with self.assertRaises(SystemExit):archive.retire_controller(result)
        with closing(capital._connect()) as db:
            row=archive.anchor(db);row['retirement_pending']['drop'].append(999)
            db.execute('UPDATE capital_archive SET body=?,hash=? WHERE id=1',(canonical(row),digest(row)))
        with patch.object(archive.time,'time',return_value=2000):
            with self.assertRaisesRegex(ValueError,'pons_retirement_pending_corruption'):archive.retire_controller(result)
        self.assertTrue(path.exists());self.assertEqual(capital.reconcile(),before)
