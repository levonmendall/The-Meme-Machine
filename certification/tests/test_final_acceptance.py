import json
from pathlib import Path
import tempfile
import unittest

from certification.final_acceptance import run

LANES=("pump","pons","meteora","ramses")

class FinalAcceptanceTests(unittest.TestCase):
    def build(self,root,*,integrated=True,connectivity=True):
        root=Path(root);(root/"offline").mkdir();(root/"restart-safety").mkdir();(root/"integrated-acceptance").mkdir()
        (root/"offline/result.json").write_text(json.dumps(dict(
            passed=True,integration_sha="sha",test_counts={lane:1 for lane in LANES})))
        (root/"crash.json").write_text(json.dumps(dict(
            lanes=[dict(lane=lane,passed=True) for lane in LANES])))
        (root/"restart-safety/result.json").write_text(json.dumps(dict(passed=True)))
        (root/"integrated-acceptance/result.json").write_text(json.dumps(dict(passed=integrated)))
        (root/"historical-resolution.json").write_text(json.dumps(dict(
            disposition="certified_historical_unreplayable_zero_proceeds_writeoff",
            immutable_original_artifact_preserved=True,market_settlement_performed=False,
            after=dict(open_positions=0,reserved=0,stale_marks=0,writeoffs=1,
                       realized_pnl_lamports=-100))))
        for lane in LANES:
            (root/f"{lane}-connectivity.json").write_text(json.dumps(dict(
                passed=connectivity,scope="bounded")))
        (root/"pump-resource.json").write_text(json.dumps(dict(real_provider_calls=0,peak_rss_kib=1)))
        (root/"meteora-resource.json").write_text(json.dumps(dict(real_provider_calls=0,peak_rss_kib=1)))
        (root/"meteora-dlmm-resource.json").write_text(json.dumps(dict(real_provider_calls=0,peak_rss_kib=1)))

    def test_every_gate_required_for_non_market_certification(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"e";root.mkdir();self.build(root)
            out=Path(td)/"out.json"
            self.assertEqual(run(root,out,"sha"),0)
            result=json.loads(out.read_text())
            self.assertEqual(result["engineering_certification"],"CERTIFIED_NON_MARKET_ENGINEERING")
            self.assertTrue(result["passed"])

    def test_integrated_or_connectivity_failure_fails_closed(self):
        for key in ("integrated","connectivity"):
            with self.subTest(key=key),tempfile.TemporaryDirectory() as td:
                root=Path(td)/"e";root.mkdir()
                self.build(root,integrated=key!="integrated",connectivity=key!="connectivity")
                out=Path(td)/"out.json"
                self.assertEqual(run(root,out,"sha"),1)
                result=json.loads(out.read_text())
                self.assertEqual(result["engineering_certification"],"NOT_CERTIFIED")

    def test_wrong_integration_sha_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"e";root.mkdir();self.build(root)
            out=Path(td)/"out.json"
            self.assertEqual(run(root,out,"different"),1)
            self.assertFalse(json.loads(out.read_text())["gates"]["exact_integration_identity"])

if __name__=="__main__":unittest.main()
