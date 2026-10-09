"""Owner-approved count-veto removal and durable worker-pressure disposition."""
import ast
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import pons_postgrad_survivor as strategy
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
from meme_machine.runtime.directional_sleeve import open_sleeve
from meme_machine.runtime.robinhood.pons import Broker
from tests.lanes.pons.test_pons_candidate_plane import event
from tests.lanes.pons.test_pons_postgrad_survivor import facts
from tests import test_forward_survivor as forward_fixture


class OwnerAdmissionTests(unittest.TestCase):
    def test_all_twenty_qualified_rows_remain_selectable_with_twenty_existing_positions(self):
        rows=[facts() for _ in range(20)]
        for count in (0,1,2,8,20):
            selected,decisions=strategy.select_entries(rows,open_positions=count)
            self.assertEqual(len(selected),20)
            self.assertTrue(all(d['candidate'] for d in decisions))
        failed=facts();failed['flow_30m']['creator_sell_quote']=1
        self.assertFalse(strategy.evaluate_entry(failed)['candidate'])

    def test_existing_economic_policy_and_native_exit_functions_are_exact(self):
        path='meme_machine/lanes/pons/pons_postgrad_survivor.py'
        old=subprocess.check_output(['git','show','cbfcb4137f10474ffc7fe0e19f0b8772f25c1563:'+path],text=True)
        before=ast.parse(old);after=ast.parse(Path(path).read_text())
        def economic(tree):
            return [ast.dump(n,include_attributes=False) for n in tree.body
                if not isinstance(n,ast.FunctionDef) or n.name!='select_entries']
        self.assertEqual(economic(before),economic(after))
        # The frozen legacy receipt hash remains usable by restart reconciliation.
        self.assertEqual(strategy.POLICY['execution']['max_open_positions'],2)

    def test_twenty_native_capital_reservations_reconcile_after_restart_and_refuse_overflow(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{
                'MM_DIRECTIONAL_SLEEVE_DB':td+'/sleeve','MM_DIRECTIONAL_COHORT_ID':'owner-cap'},clear=True):
            sleeve=open_sleeve('pons',1000)
            try:
                for i in range(20):sleeve.reserve('position:'+str(i),strategy=strategy.STRATEGY_VERSION,amount=50,at=100)
                self.assertEqual(sleeve.reconcile()['reserved'],1000)
                self.assertEqual(sleeve.reconcile()['available'],0)
                with self.assertRaises(ValueError):sleeve.reserve('overflow',strategy=strategy.STRATEGY_VERSION,amount=1,at=100)
            finally:sleeve.close()
            sleeve=open_sleeve('pons',1000)
            try:
                self.assertEqual(sleeve.reconcile()['reserved'],1000)
                self.assertTrue(sleeve.reconcile()['reconciled'])
            finally:sleeve.close()

    def test_real_survivor_dispatch_after_twenty_controllers_still_reaches_native_capital_refusal(self):
        f=forward_fixture.ForwardSurvivorTests();f.setUp();self.addCleanup(f.doCleanups)
        token,state=f.seed_complete_winner()
        f.runtime.sleeve.reserve('capital-committed',strategy='pons-selective-continuation-v1',amount=10**18,at=state['at']-1)
        original=f.runtime.history.rows
        held=[dict(deepcopy(original()[0]),id='held:'+str(i),position='held:'+str(i)) for i in range(20)]
        with patch.object(f.runtime.history,'rows',side_effect=lambda:original()+held),patch.object(f.runtime,'_position') as protection:
            result=f.run_winner(token,state)
        row=f.runtime.history.get(token)
        self.assertTrue(row['decision']['candidate'])
        self.assertEqual(row['last_failure']['category'],'QUALIFIED_BUT_CAPITAL_UNAVAILABLE')
        self.assertEqual(protection.call_count,20)
        self.assertEqual(result['admission']['position_count_limit'],None)
        self.assertEqual(f.runtime.book.reconcile()['open_positions'],0)

