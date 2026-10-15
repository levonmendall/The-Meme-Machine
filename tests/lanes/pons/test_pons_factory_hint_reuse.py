"""Focused synthetic regressions for authenticated identity hint reuse.

Run with the prepared Pons tree on PYTHONPATH. No provider transport is used.
The native candidate acquisition function and real bounded hint store execute;
ABI/code/log authentication seams use the existing acquisition-test mock style.
"""
import copy
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError, CHAIN_ID
from meme_machine.lanes.pons.abi import calldata
from meme_machine.lanes.pons.pons_natural_observation import _authenticate_candidate
from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext


MODULE = "meme_machine.lanes.pons.pons_natural_observation"
CURVE = "0x" + "22" * 20
TOKEN = "0x" + "11" * 20
OTHER_TOKEN = "0x" + "33" * 20
NON_NATIVE = "0x" + "44" * 20


def word(value):
    return "0x" + f"{int(value):064x}"


class CandidateContext(SelectiveEvidenceContext):
    """Record native read batches while supplying fresh observation responses."""

    def __init__(self):
        super().__init__("https://robinhood-mainnet.g.alchemy.com/v2/offline")
        self.batches = []
        self.token = TOKEN
        self.snipe = 0
        self.bad_header = False
        self.event = None

    def observe(self, block):
        self.event = dict(
            address=CURVE,
            blockNumber=hex(block),
            blockHash="0x" + f"{block:064x}",
            transactionHash="0x" + f"{block + 1000:064x}",
            transactionIndex="0x0",
            logIndex="0x0",
            topics=[],
            data="0x",
        )
        return copy.deepcopy(self.event)

    def batch(self, calls, scope):
        self.batches.append((scope, copy.deepcopy(calls)))
        out = []
        for method, params in calls:
            if method == "eth_chainId":
                out.append(hex(CHAIN_ID))
            elif method == "eth_getBlockByNumber":
                out.append(dict(
                    number=self.event["blockNumber"],
                    hash="wrong" if self.bad_header else self.event["blockHash"],
                    timestamp=hex(1000),
                ))
            elif method == "eth_getTransactionReceipt":
                out.append(dict(
                    transactionHash=self.event["transactionHash"],
                    blockHash=self.event["blockHash"],
                    gasUsed=hex(100_000),
                    logs=[],
                ))
            elif method == "eth_getCode":
                out.append("0x6000")
            elif method == "eth_gasPrice":
                out.append(hex(10**9))
            elif method == "eth_call":
                data = params[0]["data"]
                if data == calldata("token()"):
                    out.append(word(int(self.token, 16)))
                elif data == calldata("getReserves()"):
                    out.append(word(2 * 10**18) + word(800 * 10**24)[2:])
                elif data == calldata("realQuoteReserve()"):
                    out.append(word(10**18))
                elif data == calldata("reservedTokens()"):
                    out.append(word(100 * 10**24))
                elif data == calldata("graduated()"):
                    out.append(word(0))
                elif data.startswith(calldata("currentSnipeTaxBps(address)", TOKEN)[:10]):
                    out.append(word(self.snipe))
                elif data.startswith(calldata("getLaunchedToken(address)", TOKEN)[:10]):
                    # Opaque mock record body keyed by the actually requested token.
                    out.append("record:" + "0x" + data[-40:])
                else:
                    raise AssertionError(data)
            else:
                raise AssertionError(method)
        return out


class FactoryHintReuseTests(unittest.TestCase):
    def setUp(self):
        self.ctx = CandidateContext()
        self.authentication = self.enterContext(patch(
            MODULE + ".authenticate_curve",
            return_value={"immutables": {"feeBps": 100, "creatorTaxBps": 0}},
        ))
        self.factory = self.enterContext(patch(
            MODULE + ".factory_record",
            side_effect=lambda raw, role: dict(
                token=raw.removeprefix("record:"), curve=CURVE,
                deployer=TOKEN, creatorFeeRecipient=TOKEN,
                pairToken=NON_NATIVE, exists=True,
            ),
        ))
        self.raw_event = self.enterContext(patch(
            MODULE + ".raw_event",
            return_value={"decoded": {"name": "CurveBuy"}, "event_at": 1000},
        ))
        self.enterContext(patch(MODULE + ".time.time", return_value=1000.0))
        self.enterContext(patch(MODULE + ".time.monotonic", return_value=100.0))

    def reject(self, block, reason="natural_non_native_quote_not_supported"):
        report = {"reads": []}
        event = self.ctx.observe(block)
        with self.assertRaisesRegex(BoundaryError, "^" + reason + "$"):
            _authenticate_candidate(self.ctx, event, report)
        return report

    def assert_fresh_candidate_batch(self, batch_index, block):
        scope, calls = self.ctx.batches[batch_index]
        self.assertEqual(scope, "pons_natural")
        methods = [method for method, _ in calls]
        for required in ("eth_chainId", "eth_getBlockByNumber", "eth_getTransactionReceipt",
                         "eth_getCode", "eth_gasPrice"):
            self.assertIn(required, methods)
        getters = {params[0]["data"] for method, params in calls
                   if method == "eth_call" and params[0]["to"] == CURVE}
        for signature in ("token()", "getReserves()", "realQuoteReserve()",
                          "reservedTokens()", "graduated()"):
            self.assertIn(calldata(signature), getters)
        self.assertTrue(any(data.startswith(calldata("currentSnipeTaxBps(address)", TOKEN)[:10])
                            for data in getters))
        for method, params in calls:
            if method in ("eth_call", "eth_getCode"):
                self.assertEqual(params[-1], hex(block))

    def test_two_non_native_observations_reuse_hint_without_skipping_fresh_reads(self):
        first = self.reject(123)
        self.assertEqual(self.ctx.factory_token_hint(CURVE), TOKEN)
        second = self.reject(124)
        self.assertEqual([len(calls) for _, calls in self.ctx.batches], [11, 1, 12])
        self.assertFalse(first["timing"]["factory_record_in_first_batch"])
        self.assertTrue(second["timing"]["factory_record_in_first_batch"])
        self.assert_fresh_candidate_batch(0, 123)
        self.assert_fresh_candidate_batch(2, 124)
        self.assertEqual(self.authentication.call_count, 2)
        self.assertEqual(self.factory.call_count, 2)
        self.assertEqual(self.raw_event.call_count, 2)

    def test_current_snipe_is_still_read_and_rejected_after_hint_reuse(self):
        self.reject(123)
        self.ctx.snipe = 9900
        report = self.reject(124, "invalid_current_snipe_bps")
        self.assertTrue(report["timing"]["factory_record_in_first_batch"])
        self.assert_fresh_candidate_batch(2, 124)
        self.assertEqual(self.authentication.call_count, 2)

    def test_token_mismatch_uses_current_token_factory_read_and_reauthenticates(self):
        self.reject(123)
        self.ctx.token = OTHER_TOKEN
        report = self.reject(124)
        self.assertEqual([len(calls) for _, calls in self.ctx.batches], [11, 1, 12, 1])
        self.assertFalse(report["timing"]["factory_record_in_first_batch"])
        last_call = self.ctx.batches[-1][1][0]
        self.assertEqual(last_call[1][0]["data"], calldata("getLaunchedToken(address)", OTHER_TOKEN))
        self.assertEqual(self.authentication.call_args.kwargs["factory_record"]["token"], OTHER_TOKEN)
        self.assertEqual(self.ctx.factory_token_hint(CURVE), OTHER_TOKEN)

    def test_failed_factory_authentication_never_seeds_identity_hint(self):
        self.authentication.side_effect = BoundaryError("curve_factory_disagreement")
        self.reject(123, "curve_factory_disagreement")
        self.assertIsNone(self.ctx.factory_token_hint(CURVE))
        self.authentication.side_effect = None
        report = self.reject(124)
        self.assertEqual([len(calls) for _, calls in self.ctx.batches], [11, 1, 11, 1])
        self.assertFalse(report["timing"]["factory_record_in_first_batch"])

    def test_existing_hint_cannot_bypass_current_factory_or_header_failure(self):
        self.reject(123)
        self.authentication.side_effect = BoundaryError("curve_factory_disagreement")
        self.reject(124, "curve_factory_disagreement")
        self.assertEqual(self.authentication.call_count, 2)
        self.assertEqual(len(self.ctx.batches[-1][1]), 12)
        self.ctx.bad_header = True
        self.reject(125, "candidate_identity_disagreement")
        # Header/receipt identity must reject before factory authentication.
        self.assertEqual(self.authentication.call_count, 2)


if __name__ == "__main__":
    unittest.main()
