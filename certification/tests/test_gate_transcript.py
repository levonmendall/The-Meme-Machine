import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from certification.run import verify

class GateTranscriptTests(unittest.TestCase):
    def test_zero_exit_without_full_transcript_is_failed_and_preserved(self):
        for body,expected in [(b'test_one ... ok\n',False),(b'test_one ... ok\n\nRan 1 test in 0.1s\n\nOK\n',True)]:
            with tempfile.TemporaryDirectory() as tmp, \
                 patch('certification.run.LANES',('pons',)), \
                 patch('certification.run.source_integrity',return_value={'pons':'overlay'}), \
                 patch('certification.run.manifest',return_value={}), \
                 patch('certification.run.implementation_hash',return_value='implementation'), \
                 patch('certification.run.git',return_value='sha'), \
                 patch('certification.run.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=body)):
                result=verify(tmp,tmp)
                self.assertEqual(result['passed'],expected)
                self.assertEqual((Path(tmp)/'pons-gate-0.log').read_bytes(),body)
