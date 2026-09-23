import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from certification import run


class HistoricalExposureTests(unittest.TestCase):
    def registry(self,root,body):
        path=Path(root)/"certification";path.mkdir()
        (path/"historical_exposure.json").write_text(json.dumps(body))
        return Path(root)

    def unresolved_row(self):
        return dict(
            lane="meteora",observed_open_positions=1,resolution=None,
            artifact_id=1,artifact_sha256="a"*64,
        )

    def resolved_row(self):
        return dict(
            lane="meteora",observed_open_positions=1,
            resolution=dict(
                disposition="certified_historical_unreplayable_zero_proceeds_writeoff",
                immutable_original_artifact_preserved=True,
                market_settlement_performed=False,
                proceeds_lamports=0,open_positions_after=0,reserved_after=0,
                stale_marks_after=0,writeoffs_after=1,receipt_sha256="b"*64,
            ),
        )

    def test_repository_registry_has_no_remaining_admission_quarantine(self):
        self.assertEqual(run.historical_exposure(),[])

    def test_new_output_directory_cannot_hide_unresolved_old_policy_position(self):
        with tempfile.TemporaryDirectory() as td:
            root=self.registry(td,dict(schema_version=1,unresolved=[self.unresolved_row()],resolved=[]))
            gate=root/"gate.json";out=root/"new-campaign"
            gate.write_text(json.dumps(dict(passed=True,source_manifest_hash="hash",
                integration_sha="head",implementation_hash="impl",source_diff_hashes={})))
            with patch.object(run,"ROOT",root),patch.object(run,"integration_integrity"),\
                 patch.object(run,"manifest",return_value={"lanes":{}}),\
                 patch.object(run,"digest",return_value="hash"),patch.object(run,"git",return_value="head"),\
                 patch.object(run,"implementation_hash",return_value="impl"),\
                 patch.object(run,"source_integrity",return_value={}),patch.object(run.subprocess,"Popen") as spawn:
                unresolved=run.historical_exposure()
                result=run.launch(root,out,600,"smoke",gate)
            spawn.assert_not_called()
            self.assertEqual(result["status"],"BLOCKED")
            self.assertIn("historical_unresolved_exposure:meteora",result["blockers"])
            self.assertEqual(result["historical_exposure"],unresolved)

    def test_verified_resolution_is_retained_but_no_longer_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root=self.registry(td,dict(schema_version=1,unresolved=[],resolved=[self.resolved_row()]))
            with patch.object(run,"ROOT",root):
                self.assertEqual(run.historical_exposure(),[])

    def test_invalid_resolution_receipt_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            row=self.resolved_row();row["resolution"]["open_positions_after"]=1
            root=self.registry(td,dict(schema_version=1,unresolved=[],resolved=[row]))
            with patch.object(run,"ROOT",root),self.assertRaisesRegex(
                    ValueError,"historical_exposure_resolution_receipt_invalid"):
                run.historical_exposure()


if __name__=="__main__":unittest.main()
