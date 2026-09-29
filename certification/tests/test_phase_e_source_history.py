"""Ordinary CI must make frozen historical policy inputs available, not waive them."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[2]

class SourceHistoryTests(unittest.TestCase):
    def test_generic_ci_fetches_history_needed_by_policy_contract(self):
        text=(ROOT/'.github/workflows/ci.yml').read_text()
        first_checkout=text.split('- uses: actions/checkout@',1)[1].split('- uses:',1)[0]
        self.assertIn('fetch-depth: 0',first_checkout)
        self.assertNotIn('fetch-depth: 2',first_checkout)

    def test_frozen_policy_base_is_resolvable_and_contract_still_checked(self):
        raw=subprocess.check_output(['git','show',
            'af60b355995dfa960555288fa73808bb7aba5d25:certification/sources.json'],cwd=ROOT)
        self.assertIn(b'"lanes"',raw)
        self.assertIn('policy_contract_checks', (ROOT/'certification/build_consistency.py').read_text())
