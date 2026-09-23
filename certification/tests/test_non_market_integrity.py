"""Regression proofs for mutation and terminal-status certification boundaries."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from certification import run
from certification.worker import Observer


class SourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.lane=self.root/'worktrees'/'pump'
        self.lane.mkdir(parents=True)
        def git(*args):
            return subprocess.check_output(['git',*args],cwd=self.lane,stderr=subprocess.DEVNULL,text=True).strip()
        git('init')
        git('config','user.name','Certification Test')
        git('config','user.email','certification@example.invalid')
        (self.lane/'strategy.py').write_text('PAPER_ONLY=True\n')
        (self.lane/'.gitignore').write_text('ignored/\n__pycache__/\n*.pyc\nconfig.local.json\n')
        git('add','.')
        git('commit','-m','fixture')
        patches=self.root/'certification'/'patches'
        patches.mkdir(parents=True)
        (patches/'pump-accounting.patch').write_bytes(b'')
        self.spec={'lanes':{'pump':{'source_sha':git('rev-parse','HEAD'),
            'file_hashes':{'strategy.py':hashlib.sha256((self.lane/'strategy.py').read_bytes()).hexdigest()}}}}
        self.addCleanup(patch.stopall)
        patch.object(run,'ROOT',self.root).start()
        patch.object(run,'manifest',return_value=self.spec).start()

    def check(self):
        return run.source_integrity(self.root/'worktrees')

    def test_pinned_tree_passes(self):
        self.assertEqual(self.check(),{'pump':hashlib.sha256(b'').hexdigest()})

    def test_untracked_module_cannot_shadow_pinned_runtime(self):
        (self.lane/'provider.py').write_text('PAPER_ONLY=False\n')
        with self.assertRaisesRegex(ValueError,'unreviewed_lane_runtime_file:pump:provider.py'):
            self.check()

    def test_ignored_runtime_module_is_still_rejected(self):
        (self.lane/'ignored').mkdir()
        (self.lane/'ignored'/'strategy.py').write_text('PAPER_ONLY=False\n')
        with self.assertRaisesRegex(ValueError,'unreviewed_lane_runtime_file'):
            self.check()

    def test_native_module_and_sourceless_bytecode_are_rejected(self):
        for name in ('provider.so','provider.pyc','authority.pth','config.local.json'):
            with self.subTest(name=name):
                p=self.lane/name;p.write_bytes(b'unreviewed')
                with self.assertRaisesRegex(ValueError,'unreviewed_lane_runtime_file'):
                    self.check()
                p.unlink()

    def test_runtime_reports_are_not_mistaken_for_policy_mutations(self):
        (self.lane/'report.json').write_text('{}')
        self.check()

    def test_tracked_policy_mutation_fails(self):
        (self.lane/'strategy.py').write_text('PAPER_ONLY=False\n')
        with self.assertRaisesRegex(ValueError,'frozen_source_file_drift'):
            self.check()


class TerminalStatusTests(unittest.TestCase):
    def test_checkpoint_cannot_overwrite_terminal_truth_for_any_lane(self):
        for lane in ('pump','pons','meteora','ramses'):
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                with patch.dict(os.environ,{'MM_CERT_GOVERNOR_DB':str(root/'governor.sqlite')}):
                    observer=Observer(root/lane,lane,'a'*64)
                try:
                    observer.status('returned',{'settled':1,'open_positions':0})
                    terminal=(root/lane/'status.json').read_bytes()
                    observer.status('lane_checkpoint',{'settled':0,'open_positions':1})
                    self.assertEqual((root/lane/'status.json').read_bytes(),terminal)
                    observer.status('failed',{'error':'archive_failure'})
                    observer.status('returned',{'settled':1})
                    self.assertEqual(json.loads((root/lane/'status.json').read_text())['phase'],'failed')
                finally:
                    observer.raw.close();observer.journal.close()

    def test_legacy_live_job_is_explicitly_opt_in(self):
        workflow=(Path(__file__).resolve().parents[2]/'.github/workflows/ci.yml').read_text()
        job=workflow.split('  live-diagnostic:\n',1)[1]
        condition=next(line for line in job.splitlines() if line.startswith('    if:'))
        self.assertIn("github.event_name == 'push'",condition)
        self.assertIn("'[legacy-shadow-connectivity]'",condition)


class ConnectivityHarnessTests(unittest.TestCase):
    def test_solana_lane_calls_match_authoritative_adapter_contracts(self):
        from certification.connectivity_smoke import (
            solana_genesis_call_kwargs,solana_subscription_request)
        self.assertEqual(solana_genesis_call_kwargs('pump'),{'priority':True})
        self.assertEqual(solana_genesis_call_kwargs('meteora'),{'priority':True,'fresh':True})
        pump=solana_subscription_request('pump','pump-program')
        self.assertEqual(pump['method'],'logsSubscribe')
        self.assertEqual(pump['params'][1],{'commitment':'finalized'})
        meteora=solana_subscription_request('meteora','dlmm-program')
        self.assertEqual(meteora['method'],'programSubscribe')
        self.assertEqual(meteora['params'][1]['filters'],[{'dataSize':904}])
        self.assertEqual(meteora['params'][1]['commitment'],'finalized')
        with self.assertRaisesRegex(ValueError,'solana_lane_required'):
            solana_genesis_call_kwargs('pons')


if __name__=='__main__':
    unittest.main()
