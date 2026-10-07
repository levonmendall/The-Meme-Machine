"""Explicit synthetic risk policy; no migration or activation of a runtime."""
from dataclasses import replace
from decimal import Decimal
import tempfile
import unittest
from meme_machine.shared_capital import CapitalError,RiskPolicy
from meme_machine.shared_capital.operational_candidate import PumpPonsCapital,ACTIVE_REGIMES,verify_two_family_plan
from tests.shared_capital_support import Harness,CONTRACTS


class PreparedCapitalTests(unittest.TestCase):
    def harness(self,policy=RiskPolicy()):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup)
        h=Harness(td.name,policy);h.authority.close()
        h.authority=PumpPonsCapital(h.path);self.addCleanup(h.close)
        def finish(round_id,requests):
            for r in ACTIVE_REGIMES:
                h.authority.seal(operation_id='seal:'+round_id+':'+r,round_id=round_id,
                    regime_name=r,request_ids=[q.request_id for q in requests if q.regime==r],at=h.at)
        h.finish_round=finish
        return h

    def test_shared_cash_can_fund_beyond_old_sleeve_without_enlarging_native_targets(self):
        h=self.harness();basis=Decimal(0)
        for i in range(21):
            requests,result=h.allocate([('pump_current',{'asset':'asset:'+str(i)})])
            q=requests[0];decision=result['decisions'][q.request_id]
            self.assertEqual(decision['basis'],'6.25')
            h.fill(q);basis+=Decimal(decision['basis'])
        self.assertEqual(basis,Decimal('131.25'))
        snap=h.check()
        self.assertEqual(Decimal(snap['capital']['realized_equity']),Decimal('500'))
        self.assertEqual(snap['capital']['actual_cash'],'368.75')
        self.assertIs(snap['capital']['conservation'],True)

    def test_paused_empty_manifests_survive_restart_but_active_silence_still_blocks(self):
        h=self.harness();a=h.authority
        a.open_round(operation_id='open:r',round_id='r',at=0,cutoff=0)
        before=a.snapshot();a.close();h.authority=PumpPonsCapital(h.path);a=h.authority
        self.assertEqual(before,a.snapshot())
        a.open_round(operation_id='open:r',round_id='r',at=0,cutoff=0)
        with self.assertRaisesRegex(CapitalError,'watermarks'):a.allocate(round_id='r',at=0)
        h.finish_round('r',[])
        result=a.allocate(round_id='r',at=0)
        self.assertEqual(result['decisions'],{})

    def test_paused_admissions_cannot_acquire_new_claims_or_block_pons(self):
        h=self.harness();a=h.authority
        before=a.snapshot()
        for r in ('meteora','ramses'):
            with self.assertRaisesRegex(CapitalError,'paused_family_capital_admission'):
                a.observe(operation_id='obs:'+r,at=0,regime_name=r,candidate_id='old',generation=1,status='QUALIFIED',economic_keys=['old'],evidence={},policy_hash=CONTRACTS[r]['policy_hash'])
            with self.assertRaisesRegex(CapitalError,'paused_family_capital_admission'):
                a.require_obligation(operation_id='risk:'+r,obligation_id=r,regime_name=r,amount_usd='1',at=0,proof_sha256='a'*64)
        self.assertEqual(a.snapshot(),before)
        requests,result=h.allocate([('pons_current',{})])
        self.assertEqual(result['decisions'][requests[0].request_id]['basis'],'6.25')

    def test_unapproved_sizing_and_adaptive_economics_fail_closed_on_restore(self):
        for policy in (replace(RiskPolicy(),sizing_basis='shared_realized_equity'),replace(RiskPolicy(),adaptive=True)):
            td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup)
            h=Harness(td.name,policy);h.close()
            with self.assertRaisesRegex(CapitalError,'fixed_native_equivalent_sizing_required'):PumpPonsCapital(h.path)
            with self.assertRaisesRegex(CapitalError,'fixed_native_equivalent_sizing_required'):verify_two_family_plan(h.plan)


if __name__=='__main__':unittest.main()
