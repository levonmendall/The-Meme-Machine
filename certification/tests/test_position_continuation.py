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


if __name__=='__main__':
    unittest.main()
