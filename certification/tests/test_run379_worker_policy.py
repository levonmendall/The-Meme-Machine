"""Run 379: native worker startup must bind the approved composed policy."""
from contextlib import chdir
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from certification import worker


class WorkerPolicyIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.policy = self.root / 'SOLANA_DLMM_INDEPENDENT_V1.json'
        self.base = b'{"revision":"source"}\n'
        self.composed = b'{"revision":"approved-composed"}\n'
        self.policy.write_bytes(self.composed)
        self.row = dict(policy_hash='a' * 64,
            file_hashes={self.policy.name: hashlib.sha256(self.base).hexdigest()},
            composed_file_hashes={self.policy.name: hashlib.sha256(self.composed).hexdigest()})

    def startup_policy(self):
        (self.root / 'sources.json').write_text(json.dumps({'lanes': {'meteora': self.row}}))
        with chdir(self.root), patch.object(worker, '__file__', str(self.root / 'worker.py')):
            return worker.policy_for('meteora')

    def test_approved_composed_policy_passes_real_worker_check(self):
        self.assertEqual(self.startup_policy(), self.row['policy_hash'])

    def test_pre_overlay_source_cannot_replace_approved_composed_policy(self):
        self.policy.write_bytes(self.base)
        with self.assertRaisesRegex(ValueError, 'frozen_source_file_drift:meteora'):
            self.startup_policy()

    def test_modified_composed_policy_fails_closed(self):
        self.policy.write_bytes(self.composed + b' ')
        with self.assertRaisesRegex(ValueError, 'frozen_source_file_drift:meteora'):
            self.startup_policy()

    def test_legacy_uncomposed_policy_still_binds_source_bytes(self):
        del self.row['composed_file_hashes']
        self.policy.write_bytes(self.base)
        self.assertEqual(self.startup_policy(), self.row['policy_hash'])

    def test_incomplete_composed_manifest_does_not_fall_back_to_old_source(self):
        self.row['composed_file_hashes'] = {}
        self.policy.write_bytes(self.base)
        with self.assertRaises((KeyError, ValueError)):
            self.startup_policy()


class PreparedWorkerStartupTests(unittest.TestCase):
    def test_all_four_prepared_workers_accept_exact_active_policy_identity(self):
        work = os.environ.get('MM_TEST_LANE_WORKTREES')
        if not work:
            self.skipTest('Prepared lanes required; exercised by full hosted certification')
        root = Path(__file__).resolve().parents[2]
        spec = json.loads((root / 'certification/sources.json').read_text())
        code = ('import socket,sys; from unittest.mock import patch; '
                'from certification.worker import policy_for; '
                '\nwith patch.object(socket.socket,"connect",side_effect=AssertionError("nonmarket_network")):'
                '\n print(policy_for(sys.argv[1]))')
        for lane, row in spec['lanes'].items():
            with self.subTest(lane=lane):
                env = {k: v for k, v in os.environ.items()
                       if not k.startswith(('MM_', 'GH_', 'GITHUB_'))
                       and not any(s in k.upper() for s in ('TOKEN', 'SECRET', 'PRIVATE_KEY'))}
                env['PYTHONPATH'] = str(root)
                result = subprocess.run([sys.executable, '-c', code, lane],
                    cwd=Path(work) / lane, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip(), row['policy_hash'])


if __name__ == '__main__':
    unittest.main()
