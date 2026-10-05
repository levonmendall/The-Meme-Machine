"""Preserved research and owner mandates have no runtime allocation authority."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class StrategicReferenceTests(unittest.TestCase):
    def test_sources_and_authority_categories_preserved(self):
        data=json.loads((ROOT/'operational/strategic-reference-sources.json').read_text())
        categories={'ACTIVE_STRATEGY','REQUIRED_FINAL_AUDIT','DEFERRED_IMPLEMENTATION',
                    'RESEARCH_ONLY','INTENTIONALLY_REJECTED','SUPERSEDED','OPERATIONAL_REFERENCE'}
        records=data['records']
        by_path={r['source_path']:r for r in records}
        expected={
            'certification/strategy-prep/right-tail-market-evidence-20261001.json':'RESEARCH_ONLY',
            'research/PUMP_REJECTED_WINNER_HYPOTHESIS_V1.json':'RESEARCH_ONLY',
            'research/PUMP_REJECTED_WINNER_TRAJECTORY_V1.json':'RESEARCH_ONLY',
            'research/public-market-7d-20261001/REPORT.md':'RESEARCH_ONLY',
            'docs/RESET_RECOVERY_V1_RESEARCH_CONTRACT.md':'DEFERRED_IMPLEMENTATION',
            'certification/profitability_protocol.json':'SUPERSEDED',
            'certification/shadow_registry.json':'RESEARCH_ONLY',
        }
        for path,category in expected.items():
            self.assertEqual(by_path[path]['classification'],category)
        for record in records:
            self.assertIn(record['classification'],categories)
            self.assertRegex(record['source_commit'],r'^[0-9a-f]{40}$')
            self.assertRegex(record['source_sha256'],r'^[0-9a-f]{64}$')
        self.assertIn('none',data['runtime_authority'])

    def test_future_winner_capture_audit_remains_explicit(self):
        text=(ROOT/'operational/STRATEGIC_REFERENCE.md').read_text()
        mandate=text.split('## REQUIRED_FINAL_AUDIT',1)[1].split('\n## ',1)[0]
        for required in ('RIGHT-TAIL CAPTURE EFFICIENCY AUDIT','5x','10x','25x','50x',
                         'position sizing','partial realization','trailing exits','right-tail behavior',
                         'maximum-hold behavior','Current tail bridge','staged winner scaling',
                         'conflict/reservation rules','family/sleeve capital constraints',
                         'realized-equity compounding'):
            self.assertIn(required,mandate)
        self.assertIn('does not run the audit',mandate)
        self.assertIn('Research has no allocation authority',text)
        self.assertIn('73.33%',text)
        self.assertIn('Future outcomes cannot create candidate membership',text)

    def test_incident_references_point_to_permanent_current_regressions(self):
        from operational.tests import OPERATIONAL
        data=json.loads((ROOT/'operational/incident-reference-sources.json').read_text())
        self.assertEqual(data['classification'],'OPERATIONAL_REFERENCE')
        for path in data['current_tests']:
            self.assertTrue((ROOT/path).is_file(),path)
            self.assertIn(path[:-3].replace('/','.'),OPERATIONAL)
        limits=' '.join(data['preserved_limits'])
        self.assertNotIn('Run380 pressure regression remains pending',limits)
        self.assertIn('permanent OPERATIONAL regressions',limits)
        self.assertIn('Information and engineering invariants only',data['authority'])
