import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.evidence import Store
from meme_machine.lanes.pons.pons import CurveState
from meme_machine.lanes.pons.pons_selective_paper import _prove_impossible_full_exit

MODULE='meme_machine.lanes.pons.pons_selective_paper.'


class WriteoffProofTests(unittest.TestCase):
    def prove(self,age=1,real_quote=1,error=None):
        state=CurveState(1680000,10000000,real_quote,2000000,100,200,False,100,9900,14,120)
        header=dict(number='0x64',hash='h100',parentHash='h99',timestamp='0x78')
        with tempfile.TemporaryDirectory() as d:
            store=Store(d+'/proof.sqlite')
            try:
                with patch(MODULE+'_latest_header',return_value=header),patch(
                    MODULE+'_curve_state',side_effect=error,return_value=(state,None)),patch(
                    MODULE+'time.monotonic',side_effect=[100,100+age]),patch(
                    MODULE+'time.time',return_value=121):
                    proof=_prove_impossible_full_exit(None,
                        dict(curve='curve',auth={},report={}),
                        dict(id='p',version=3,tokens=200000),store)
                count=store.db.execute("SELECT count(*) FROM records WHERE category='selective_writeoff_proof'").fetchone()[0]
                return proof,count
            finally:store.close()

    def test_fresh_full_remaining_size_has_durable_zero_proceeds_proof(self):
        proof,count=self.prove()
        self.assertEqual(count,1)
        self.assertEqual(proof['tokens'],200000)
        self.assertEqual(proof['sale_proceeds'],0)
        self.assertEqual(proof['stamp']['finality'],'confirmed')

    def test_arithmetic_impossibility_with_stale_acquisition_cannot_write_off(self):
        with self.assertRaisesRegex(BoundaryError,'stale_state'):self.prove(age=5.01)

    def test_returned_liquidity_requires_real_exit(self):
        proof,count=self.prove(real_quote=680000)
        self.assertIsNone(proof)
        self.assertEqual(count,0)

    def test_provider_error_never_becomes_writeoff_evidence(self):
        with self.assertRaisesRegex(BoundaryError,'provider_rpc_429'):
            self.prove(error=BoundaryError('provider_rpc_429'))
