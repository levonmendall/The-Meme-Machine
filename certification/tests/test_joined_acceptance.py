"""A shrinking no-entry window must not hide growth or fail a fixed daily peak."""
from copy import deepcopy
import unittest
from certification.joined_acceptance import evaluate


class JoinedAcceptanceTests(unittest.TestCase):
    def fixture(self):
        identity=dict(integration_sha='exact',paper_only=True,live_money=False)
        samples=[]
        for hour in range(192):
            position=hour%24==23
            proof={lane:dict(verified=True,survivor=dict(active=True,accounting={'settled':1}))
                for lane in ('pump','pons','meteora','ramses')}
            samples.append(dict(hour=hour,bytes=2491268,wal_bytes=0,
                preseal={'bytes':2697146 if position else 2888949},tables={'native:positions':1},
                fd=4,threads=1,children=[],projection_violations=False,accounting=proof,
                mode='position' if position else 'hourly',workers={
                    lane:dict(children=[],threads=1) for lane in proof}))
        control=dict(bytes=10725,tables={'controller:recent_events':32,
            'controller:window':1,'controller:predecessor':1})
        soak=dict(identity=identity,paper_only=True,measurement_complete=True,virtual_seconds=192*3600,
            terminal_drained=True,final_successor_accounting_exact=True,samples=samples,
            base_fd=4,base_threads=1,controller=[control]*168)
        receipt=dict(identity=identity,passed=True,paper_only=True)
        return soak,[receipt,deepcopy(receipt),deepcopy(receipt)],identity

    def test_position_only_shrink_preserves_daily_plateau_but_growth_fails(self):
        soak,proofs,identity=self.fixture()
        self.assertTrue(evaluate(soak,*proofs,identity)['passed'])
        soak['samples'][-1]['preseal']['bytes']=4000000
        result=evaluate(soak,*proofs,identity)
        self.assertFalse(result['passed'])
        self.assertIn('preseal_hot_bytes_not_plateaued',result['violations'])

    def test_new_terminal_owner_or_wrong_receipt_identity_fails(self):
        for mutation in ('new_owner','wrong_identity'):
            soak,proofs,identity=self.fixture()
            if mutation=='new_owner':soak['samples'][-1]['tables']['new_owner:terminal_ids']=1000
            else:proofs[1]['identity']['integration_sha']='different'
            self.assertFalse(evaluate(soak,*proofs,identity)['passed'],mutation)
