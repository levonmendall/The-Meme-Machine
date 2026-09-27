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
        receipt="c"*64
        (root/"historical-resolution.json").write_text(json.dumps(dict(
            disposition="certified_historical_unreplayable_zero_proceeds_writeoff",
            receipt_sha256=receipt,
            immutable_original_artifact_preserved=True,market_settlement_performed=False,
            after=dict(open_positions=0,reserved=0,stale_marks=0,writeoffs=1,
                       realized_pnl_lamports=-100))))
        (root/"registry.json").write_text(json.dumps(dict(
            schema_version=1,unresolved=[],resolved=[dict(lane="meteora",
                resolution=dict(
                    disposition="certified_historical_unreplayable_zero_proceeds_writeoff",
                    receipt_sha256=receipt))])))
        for lane in LANES:
            (root/f"{lane}-connectivity.json").write_text(json.dumps(dict(
                passed=connectivity,scope="bounded")))
        (root/"pump-resource.json").write_text(json.dumps(dict(real_provider_calls=0,peak_rss_kib=1)))
        (root/"meteora-resource.json").write_text(json.dumps(dict(real_provider_calls=0,peak_rss_kib=1)))
        (root/"meteora-dlmm-resource.json").write_text(json.dumps(dict(
            real_provider_calls=0,samples=[dict(rss_kib=1),dict(rss_kib=2)])))
        (root/'run381-pressure').mkdir()
        (root/'run381-pressure/result.json').write_text(json.dumps(dict(
            passed=True,integration_sha='sha',provider_calls=0,source_seconds=600.21,
            candidate_checks=60,archive_records_verified=200000,
            counters={'compacted_records':200000},lag_peak=2,hot_peak=1000000000,
            measured_contention=dict(profile='run381-fullcert-36293751021',
                owner_seconds_per_frame=.165,archive_seconds_per_thousand=.36,
                additional_commit_latency_seconds=.006,delayed_commits=100),
            integrity=['ok'],oldest_hot_age_peak=181,oldest_retained_age_peak=182)))

    def test_missing_short_or_failed_mature_pressure_cannot_certify(self):
        for change in ('missing','short','wrong_sha','no_compaction','failed','growing_backlog','index_cleanup_backlog','missing_index_cleanup','no_contention','fast_owner','fast_archive','fast_durability','unused_durability'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as td:
                root=Path(td);self.build(root);path=root/'run381-pressure/result.json'
                row=json.loads(path.read_text())
                if change=='missing':path.unlink()
                else:
                    if change=='short':row['source_seconds']=130
                    if change=='wrong_sha':row['integration_sha']='other'
                    if change=='no_compaction':row['counters']['compacted_records']=0
                    if change=='failed':row['passed']=False
                    if change=='growing_backlog':row['oldest_hot_age_peak']=300
                    if change=='index_cleanup_backlog':row['oldest_retained_age_peak']=300
                    if change=='missing_index_cleanup':row.pop('oldest_retained_age_peak')
                    if change=='no_contention':row.pop('measured_contention')
                    if change=='fast_owner':row['measured_contention']['owner_seconds_per_frame']=0
                    if change=='fast_archive':row['measured_contention']['archive_seconds_per_thousand']=0
                    if change=='fast_durability':row['measured_contention']['additional_commit_latency_seconds']=0
                    if change=='unused_durability':row['measured_contention']['delayed_commits']=0
                    path.write_text(json.dumps(row))
                self.assertEqual(run(root,root/'result.json','sha',root/'registry.json'),1)
                self.assertFalse(json.loads((root/'result.json').read_text())['gates']['mature_solana_pressure'])

    def test_every_gate_required_for_non_market_certification(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"e";root.mkdir();self.build(root)
            out=Path(td)/"out.json"
            self.assertEqual(run(root,out,"sha",root/"registry.json"),0)
            result=json.loads(out.read_text())
            self.assertEqual(result["engineering_certification"],"CERTIFIED_NON_MARKET_ENGINEERING")
            self.assertTrue(result["passed"])

    def test_integrated_or_connectivity_failure_fails_closed(self):
        for key in ("integrated","connectivity"):
            with self.subTest(key=key),tempfile.TemporaryDirectory() as td:
                root=Path(td)/"e";root.mkdir()
                self.build(root,integrated=key!="integrated",connectivity=key!="connectivity")
                out=Path(td)/"out.json"
                self.assertEqual(run(root,out,"sha",root/"registry.json"),1)
                result=json.loads(out.read_text())
                self.assertEqual(result["engineering_certification"],"NOT_CERTIFIED")

    def test_dlmm_sample_rss_is_required_when_top_level_peak_is_absent(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"e";root.mkdir();self.build(root)
            (root/"meteora-dlmm-resource.json").write_text(json.dumps(dict(
                real_provider_calls=0,samples=[dict(rss_kib=0)])))
            out=Path(td)/"out.json"
            self.assertEqual(run(root,out,"sha",root/"registry.json"),1)
            self.assertFalse(json.loads(out.read_text())["gates"]["resource_bounds"])

    def test_wrong_integration_sha_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"e";root.mkdir();self.build(root)
            out=Path(td)/"out.json"
            self.assertEqual(run(root,out,"different",root/"registry.json"),1)
            self.assertFalse(json.loads(out.read_text())["gates"]["exact_integration_identity"])

    def test_preserved_scope_requires_all_exact_sha_reports_without_claiming_connectivity(self):
        for changed in (None,'directional_sha','preserved_sha','fresh_data','failed','missing'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as td:
                root=Path(td)/'e';root.mkdir();self.build(root,connectivity=False)
                (root/'directional-acceptance').mkdir()
                (root/'directional-acceptance/result.json').write_text(json.dumps(dict(
                    passed=True,integration_sha='other' if changed=='directional_sha' else 'sha')))
                path=root/'preserved-validation.json'
                path.write_text(json.dumps(dict(passed=changed!='failed',
                    integration_sha='other' if changed=='preserved_sha' else 'sha',
                    fresh_market_data_used=changed=='fresh_data')))
                out=root/'final.json'
                if changed=='missing':
                    path.unlink()
                    with self.assertRaises(FileNotFoundError):run(root,out,'sha',root/'registry.json',True)
                    continue
                self.assertEqual(run(root,out,'sha',root/'registry.json',True),0 if changed is None else 1)
                result=json.loads(out.read_text())
                self.assertFalse(result['fresh_provider_connectivity_checked'])
                self.assertNotIn('production_adapter_connectivity',result['gates'])

if __name__=="__main__":unittest.main()
