from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from robinhood_research import BoundaryError
from robinhood_research.abi import topic
from robinhood_research.ramses import decode_ramses_event
from robinhood_research.ramses_branch_b_cost_route_fallback import build
import robinhood_research.ramses_branch_b_public_geometry as branch_b


def word(value):
    if isinstance(value,int):
        return int(value).to_bytes(32,"big")
    if isinstance(value,bytes):
        if len(value)!=32: raise ValueError
        return value
    raise TypeError


def dynamic_event(count=140, *, malformed_count=None):
    ids=[8380000+i for i in range(count)]
    amounts=[(i+1).to_bytes(32,"big") for i in range(count)]
    head_bytes=64
    ids_offset=head_bytes
    amounts_offset=ids_offset+32*(1+count)
    data=bytearray()
    data+=word(ids_offset)
    data+=word(amounts_offset)
    data+=word(count if malformed_count is None else malformed_count)
    for value in ids:
        data+=word(value)
    data+=word(count)
    for value in amounts:
        data+=word(value)
    address_word=("00"*12)+("11"*20)
    return {
        "topics":[
            topic("WithdrawnFromBins(address,address,uint256[],bytes32[])"),
            "0x"+address_word,
            "0x"+address_word,
        ],
        "data":"0x"+bytes(data).hex(),
    }


class LargeRamsesEventTests(unittest.TestCase):
    def test_140_bin_liquidity_event_decodes(self):
        from robinhood_research.identity import load
        event=dynamic_event(140)
        decoded=decode_ramses_event(load("ramses_pool_implementation")["abi"],event)
        self.assertEqual(decoded["name"],"WithdrawnFromBins")
        self.assertEqual(len(decoded["args"]["ids"]),140)
        self.assertEqual(len(decoded["args"]["amounts"]),140)
        self.assertEqual(decoded["args"]["ids"][0],8380000)
        self.assertEqual(decoded["args"]["ids"][-1],8380139)

    def test_dynamic_count_cannot_exceed_bounded_payload(self):
        from robinhood_research.identity import load
        event=dynamic_event(140,malformed_count=10000)
        with self.assertRaisesRegex(BoundaryError,"event_dynamic_capacity"):
            decode_ramses_event(load("ramses_pool_implementation")["abi"],event)


class BranchBCostFallbackTests(unittest.TestCase):
    @staticmethod
    def _digest(body):
        return hashlib.sha256(
            json.dumps(body,sort_keys=True,separators=(",",":")).encode()
        ).hexdigest()

    def test_builder_uses_max_verified_direct_route_cost(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"rows";root.mkdir()
            cost={
                "kind":"ramses_branch_b_cost_anchor_v1",
                "frozen":True,
                "native_cycle_cost_raw":100,
            }
            cost_path=Path(td)/"cost.json"
            cost_path.write_text(json.dumps(cost))
            sha=self._digest(cost)
            for idx,q in enumerate((11,19,15)):
                p=root/str(idx);p.mkdir()
                body={
                    "kind":"ramses_branch_b_candidate_v1",
                    "phase":"development","status":"complete",
                    "candidate_index":idx,
                    "candidate":{"pool":"0x"+f"{idx+1:040x}"},
                    "cost_anchor_sha256":sha,
                    "holds":[{
                        "cost_quote_raw":q,
                        "cost_route":{"route_kind":"direct_wnative_quote_pool"},
                    }],
                }
                (p/"ramses-branch-b-candidate.json").write_text(json.dumps(body))
            result=build(root,cost_path)
            self.assertEqual(result["max_verified_quote_cycle_cost_raw"],19)
            self.assertEqual(result["verified_candidate_count"],3)
            self.assertFalse(result["cost_model_changed"])

    def test_missing_candidate_route_uses_frozen_upper_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"fallback.json"
            fallback={
                "kind":"ramses_branch_b_cost_route_fallback_v1",
                "frozen":True,
                "cost_model_changed":False,
                "native_cycle_cost_raw":100,
                "cost_anchor_sha256":"abc",
                "max_verified_quote_cycle_cost_raw":25,
                "verified_candidate_count":7,
                "verified_pool_count":6,
                "source":"verified direct Ramses routes",
                "supporting_maximum":[],
            }
            path.write_text(json.dumps(fallback))
            with patch.object(branch_b,"COST_FALLBACK",path), \
                 patch.object(branch_b,"_wnative",return_value="0x"+"22"*20), \
                 patch.object(branch_b,"_factory_direct_routes",return_value=[]):
                q,meta=branch_b._quote_cycle_cost(
                    object(),"0x"+"33"*20,123,{"cycle":100},
                    cost_anchor_sha256="abc",
                )
            self.assertEqual(q,25)
            self.assertEqual(meta["route_kind"],"verified_ramses_direct_route_upper_envelope")
            self.assertTrue(meta["conservative_upper_envelope"])

    def test_fallback_rejects_wrong_cost_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"fallback.json"
            path.write_text(json.dumps({
                "kind":"ramses_branch_b_cost_route_fallback_v1",
                "frozen":True,"cost_model_changed":False,
                "native_cycle_cost_raw":100,
                "cost_anchor_sha256":"other",
                "max_verified_quote_cycle_cost_raw":25,
            }))
            with patch.object(branch_b,"COST_FALLBACK",path), \
                 patch.object(branch_b,"_wnative",return_value="0x"+"22"*20), \
                 patch.object(branch_b,"_factory_direct_routes",return_value=[]):
                with self.assertRaisesRegex(BoundaryError,"branch_b_cost_route_fallback_identity"):
                    branch_b._quote_cycle_cost(
                        object(),"0x"+"33"*20,123,{"cycle":100},
                        cost_anchor_sha256="abc",
                    )


if __name__=="__main__":
    unittest.main()
