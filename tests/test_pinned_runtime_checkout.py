"""Actual Git cleanliness for the immutable release's pinned interpreter link."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class PinnedRuntimeCheckoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'release'; self.source.mkdir()
        self.runtime = self.root / 'pinned-runtime'; self.runtime.mkdir()
        self.git('init', '--quiet')
        original = Path(__file__).resolve().parents[1] / '.gitignore'
        (self.source / '.gitignore').write_bytes(original.read_bytes())
        (self.source / 'application.py').write_text('# disposable tracked source\n')
        self.git('add', '.gitignore', 'application.py')
        self.git('-c', 'user.name=Offline Fixture', '-c', 'user.email=offline@example.invalid',
                 'commit', '--quiet', '-m', 'disposable source')

    def git(self, *arguments):
        return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null',
            '-C', str(self.source), '--no-optional-locks', *arguments],
            stderr=subprocess.DEVNULL, text=True).strip()

    def test_pinned_interpreter_symlink_keeps_tracked_source_clean(self):
        before = self.git('rev-parse', 'HEAD^{tree}')
        (self.source / '.venv').symlink_to(self.runtime)
        self.assertEqual(self.git('status', '--porcelain', '--untracked-files=normal'), '')
        self.assertEqual(self.git('rev-parse', 'HEAD^{tree}'), before)
        self.assertEqual((self.source / '.venv').resolve(), self.runtime)

    def test_unexpected_source_and_unrelated_symlinks_are_still_visible(self):
        (self.source / '.venv').symlink_to(self.runtime)
        (self.source / 'unexpected.py').write_text('# unexpected source\n')
        (self.source / '.venv-unapproved').symlink_to(self.runtime)
        status = self.git('status', '--porcelain', '--untracked-files=normal')
        self.assertIn('?? unexpected.py', status)
        self.assertIn('?? .venv-unapproved', status)
        self.assertNotIn('?? .venv\n', status + '\n')
