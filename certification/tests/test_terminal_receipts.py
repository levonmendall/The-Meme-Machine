import json
import unittest
from certification.terminal_receipts import emit_pons

class TerminalReceiptTests(unittest.TestCase):
    def test_exact_unresolved_accounting_and_secret_boundary_are_preserved_safely(self):
        lines=[]
        report=dict(boundary='provider_recovery_exhausted:provider_shared_admission_deadline',
            cohort_accounting=dict(cash=999999999999999999,unsettled=1,remaining_cost_basis=123,reserved=456,realized=-123),
            lifecycles=[dict(index=1,status='boundary',boundary='https://provider.example/private-secret',
                lifecycle_id='private-secret',final_position=dict(tokens=100,cost=123,realized_proceeds=0))])
        emit_pons(report,emit=lambda line,**kw:lines.append(line))
        self.assertNotIn('private-secret','\n'.join(lines))
        parsed=[json.loads(line.split(' ',1)[1]) for line in lines]
        self.assertEqual(parsed[0]['accounting']['cash'],999999999999999999)
        self.assertEqual(parsed[0]['accounting']['unsettled'],1)
        self.assertEqual(parsed[1]['status'],'boundary')
        self.assertEqual(parsed[1]['position']['realized_proceeds'],0)
        self.assertFalse(parsed[1]['liquidity_writeoff'])
        self.assertTrue(parsed[1]['raw_artifact_required_for_replay'])
