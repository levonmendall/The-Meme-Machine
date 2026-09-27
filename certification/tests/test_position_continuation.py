import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from certification.position_continuation import _find,_meteora_open_identity,_runtime_identity


class PositionContinuationTests(unittest.TestCase):
    def test_find_requires_one_durable_state_file(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'a').mkdir()
            p=root/'a'/'state.sqlite';p.write_text('x')
            self.assertEqual(_find(root,'state.sqlite'),p)
            (root/'state.sqlite').write_text('y')
            with self.assertRaisesRegex(RuntimeError,'ambiguous_continuation_state'):
                _find(root,'state.sqlite')

    def test_meteora_open_identity_comes_from_append_only_terminal_state(self):
        events=[
            dict(action='genesis',identity=None,data={}),
            dict(action='reserve',identity='one',data={}),
            dict(action='entry',identity='one',data={'entry_state':{}}),
            dict(action='mark',identity='one',data={}),
            dict(action='reserve',identity='done',data={}),
            dict(action='entry',identity='done',data={'entry_state':{}}),
            dict(action='settle',identity='done',data={}),
        ]
        identity,entry=_meteora_open_identity(events)
        self.assertEqual(identity,'one')
        self.assertEqual(entry['action'],'entry')

    def test_runtime_identity_binds_source_policy_integration_and_implementation(self):
        current=json.loads((Path(__file__).parents[1]/'sources.json').read_text())
        lane=current['lanes']['meteora']
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);runtime=root/'certification-hourly';runtime.mkdir()
            (runtime/'manifest.json').write_text(json.dumps(dict(
                integration_sha='integration',
                lanes={'meteora':{
                    'source_sha':lane['source_sha'],
                    'policy_hash':lane['policy_hash'],
                    'strategy_version':lane['strategy_version'],
                }},
            )))
            (runtime/'result.json').write_text(json.dumps(dict(
                phase='hourly',integration_sha='integration',
                implementation_hash='implementation',
            )))
            with patch('certification.run.implementation_hash',return_value='implementation'):
                observed=_runtime_identity(root,'meteora')
            self.assertEqual(observed['source_sha'],lane['source_sha'])
            self.assertEqual(observed['implementation_hash'],'implementation')
            with patch('certification.run.implementation_hash',return_value='changed'):
                with self.assertRaisesRegex(RuntimeError,'implementation_hash_mismatch'):
                    _runtime_identity(root,'meteora')

    def test_meteora_resume_refuses_ambiguous_exposure(self):
        events=[
            dict(action='genesis',identity=None,data={}),
            dict(action='entry',identity='one',data={'entry_state':{}}),
            dict(action='entry',identity='two',data={'entry_state':{}}),
        ]
        with self.assertRaisesRegex(RuntimeError,'exactly_one_open_position'):
            _meteora_open_identity(events)

    def test_all_lane_artifact_does_not_mix_directional_book_namespaces(self):
        from certification.position_continuation import native_lane_root
        from certification.market_assurance import native_positions
        from certification.survivor_paper_book import PaperBook
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for lane in ('pump','pons'):
                folder=root/'certification-native/hourly'/lane;folder.mkdir(parents=True)
                book=PaperBook(folder/'paper.sqlite',run_id='original',lane=lane,policy_hash='frozen-'+lane,initial=1000)
                book.reserve('original:'+lane,100,1,{'qualified':True})
                book.transition('original:'+lane,'filled',2,amount=100,tokens=100);book.close()
            # The former whole-artifact scan mixes identical ledger schemas.
            self.assertEqual(len(native_positions(root,'pump')['positions']),2)
            for lane in ('pump','pons'):
                observed=native_positions(native_lane_root(root,lane),lane)
                self.assertEqual(set(observed['positions']),{'original:'+lane})
                self.assertEqual(observed['natural_entries'],1)
            (root/'certification-native/duplicate/pump').mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError,'ambiguous'):native_lane_root(root,'pump')

    def test_autonomous_position_claim_carries_original_authority_but_no_entry(self):
        from copy import deepcopy
        from certification.tests.test_campaign_state import CampaignStateTests
        from certification import campaign_state as transfer
        fixture=CampaignStateTests();fixture.setUp()
        try:
            state=fixture.root/'position-state';runtime=state/'certification-position'
            transfer.restore(fixture.capsule,worktrees=state/'certification-native/position',run=runtime,
                expected_identity=fixture.identity,expected_state_hash=fixture.body['state_hash'],
                campaign_id=fixture.window['campaign_id'],prior_index=0,authorization_hash=fixture.window['authorization_hash'])
            claim=fixture.claim();claim['window'].update(mode='position',entry_authority=False,
                positions={lane:['original-paper-books:position'] if lane in ('pump','pons') else [] for lane in transfer.LANES})
            path=state/'autonomous-position-authority.json';path.write_text(json.dumps(claim))
            result=_runtime_identity(state,'pump')
            self.assertFalse(result['entry_authority']);self.assertEqual(result['campaign_id'],fixture.window['campaign_id'])
            for changes in ({'entry_authority':True},{'native_run_id':'new-capital'},
                            {'parent_state_hash':'0'*64},{'index':5},{'mode':'hourly'}):
                changed=deepcopy(claim);changed['window'].update(changes);path.write_text(json.dumps(changed))
                with self.subTest(changes=changes),self.assertRaisesRegex(RuntimeError,'authority_identity'):
                    _runtime_identity(state,'pump')
        finally:fixture.doCleanups()


if __name__=='__main__':
    unittest.main()
