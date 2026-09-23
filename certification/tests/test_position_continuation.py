import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from certification.position_continuation import _find,_meteora_open_identity


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
