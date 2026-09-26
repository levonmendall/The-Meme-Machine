"""Historical receipt bytes must not depend on Git's display configuration."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from certification.native_historical_meteora_resolution import overlay_digest


class HistoricalReceiptFormatTests(unittest.TestCase):
    def test_original_receipt_survives_longer_git_abbreviations_but_not_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            def git(*args):
                return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL)
            git('init')
            source=root/'accounting.py'
            source.write_text('balance = 100\n')
            git('add','accounting.py')
            git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                'commit','-m','historical source')
            source.write_text('balance = 0\n')
            git('config','core.abbrev','7')
            legacy=hashlib.sha256(git('diff','--binary','HEAD')).hexdigest()
            git('config','core.abbrev','12')
            self.assertNotEqual(legacy,hashlib.sha256(git('diff','--binary','HEAD')).hexdigest())
            self.assertEqual(overlay_digest(root),legacy)
            source.write_text('balance = 1\n')
            self.assertNotEqual(overlay_digest(root),legacy)
