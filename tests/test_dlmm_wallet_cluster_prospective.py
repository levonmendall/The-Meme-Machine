import unittest

from meme_machine import dlmm
from meme_machine.provider import Unavailable
from tests import dlmm_wallet_cluster_prospective as prospective


class WalletClusterProspective(unittest.TestCase):
    def test_frozen_candidate_preserves_failed_confirmatory_gate(self):
        body=prospective.load_candidate()
        gate=body["source"]["confirmatory_repeatability_gate"]
        self.assertFalse(gate["passed"])
        self.assertEqual(body["exploratory_cluster"]["wallet_count"],14)
        self.assertEqual(body["exploratory_cluster"]["exact_hold_seconds"],491)
        self.assertEqual(body["exploratory_cluster"]["exact_width_bins"],70)
        self.assertFalse(body["allocation_authority"])

    def _effect(self,width=70,sol_side="x"):
        deposits=[]
        for bid in range(10,10+width):
            deposits.append(dict(
                bin_id=bid,
                x=100 if sol_side=="x" else 0,
                y=100 if sol_side=="y" else 0,
            ))
        return dict(
            amount_x=100*width if sol_side=="x" else 0,
            amount_y=100*width if sol_side=="y" else 0,
            bin_deposits=deposits,
        )

    def test_signal_requires_exact_70_bin_one_sided_sol_add(self):
        event={"effect":self._effect(70,"x")}
        info={"x":dlmm.WSOL,"y":"token"}
        qualified,reason=prospective._qualify_signal(event,info)
        self.assertIsNone(reason)
        self.assertEqual(qualified["width_bins"],70)
        self.assertEqual(len(qualified["source_sol_weights"]),70)

        rejected,reason=prospective._qualify_signal(
            {"effect":self._effect(69,"x")},info)
        self.assertIsNone(rejected)
        self.assertEqual(reason,"source_width_not_70")

        rejected,reason=prospective._qualify_signal(
            {"effect":self._effect(70,"y")},info)
        self.assertIsNone(rejected)
        self.assertEqual(reason,"source_not_one_sided_sol")

    def test_wallet_cursor_advances_only_after_all_bodies_are_readable(self):
        class RPC:
            def __init__(self):
                self.calls=[]
            def call(self,method,params,priority):
                self.calls.append((method,params,priority))
                if method=="getSignaturesForAddress":
                    return [
                        dict(signature="new-2",slot=12,err=None),
                        dict(signature="new-1",slot=11,err=None),
                    ]
                if method=="getTransaction":
                    if params[0]=="new-2":
                        raise Unavailable("provider_request_failed")
                    return dict(meta=dict(err=None),transaction=dict(message=dict()))
                raise AssertionError(method)
        class Pool:
            def __init__(self):
                self.rpc=RPC()
            def current(self,extra_calls=0):
                return self.rpc
        pool=Pool()
        with self.assertRaisesRegex(Unavailable,"provider_request_failed"):
            prospective._read_wallet_rows(pool,"wallet","old")
        # The function returns no replacement cursor on failure; the caller keeps old.
        self.assertEqual(
            pool.rpc.calls[0][1][1]["until"],"old")
        self.assertEqual(
            [call[1][0] for call in pool.rpc.calls if call[0]=="getTransaction"],
            ["new-1","new-2"])

    def test_wallet_scan_uses_serial_provider_calls(self):
        class RPC:
            def __init__(self):
                self.calls=[]
            def call(self,method,params,priority):
                self.calls.append(method)
                if method=="getSignaturesForAddress":
                    return [dict(signature="s1",slot=11,err=None)]
                if method=="getTransaction":
                    return dict(meta=dict(err=None),transaction=dict(message=dict()))
                raise AssertionError(method)
        class Pool:
            def __init__(self):
                self.rpc=RPC()
            def current(self,extra_calls=0):
                self.assertEqual(extra_calls,1)
                return self.rpc
        pool=Pool()
        inspected,newest=prospective._read_wallet_rows(pool,"wallet","old")
        self.assertEqual(newest,"s1")
        self.assertEqual(len(inspected),1)
        self.assertEqual(pool.rpc.calls,["getSignaturesForAddress","getTransaction"])

    def test_paper_deposit_mirrors_weights_at_fixed_capital(self):
        bins={}
        for bid in range(10,80):
            bins[str(bid)]=dict(
                x=1_000_000,y=0,price=dlmm.Q,supply=dlmm.Q,
                fee_x=0,fee_y=0,
            )
        state=dict(
            x=dlmm.WSOL,y="token",active=9,slot=100,time=1000,bins=bins,
        )
        signal={"source_sol_weights":{bid:1 for bid in range(10,80)}}
        p=prospective._paper_deposit(state,signal)
        self.assertEqual(p["lower"],10)
        self.assertEqual(p["upper"],79)
        self.assertEqual(len(p["shares"]),70)
        self.assertEqual(sum(
            p["virtual"]["bins"][str(bid)]["x"]-1_000_000
            for bid in range(10,80)
        )+p["idle_sol"],prospective.CAPITAL)


if __name__=="__main__":
    unittest.main()
