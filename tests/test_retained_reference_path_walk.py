"""Every original retained reference authenticates its whole fixed path anew."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime import candidate_history as references


class RetainedReferencePathWalkTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name)
        self.root=self.base/'parent/cohort';self.shared=self.root/'shared'
        self.shared.mkdir(parents=True)
        self.source=self.shared/'solana-evidence.sqlite';self.source.write_bytes(b'source-canary')
        self.candidate=self.shared/'solana-candidate-history.sqlite';self.candidate.write_bytes(b'candidate-canary')
        self.cold=self.source.with_suffix('.scoped-cold');self.cold.mkdir()
        self.archive=self.cold/('a'*64+'.zlib');self.archive.write_bytes(b'archive-canary')
        self.legacy=self.base/'legacy'
        self.old_source=self.legacy/'shared/solana-evidence.sqlite'
        self.old_archive=self.old_source.with_suffix('.scoped-cold')/self.archive.name
        self.enterContext(patch.object(references,'RETAINED_REFERENCE_LEGACY_ROOT',self.legacy))
        self.enterContext(patch.object(references,'RETAINED_REFERENCE_AWS_ROOT',self.root))
        self.enterContext(patch.dict(os.environ,MM_MODE='PAPER',MM_PAPER_EPOCH=references.RETAINED_REFERENCE_EPOCH,
            MM_STATE_ROOT=str(self.root),MM_SOLANA_EVIDENCE_PLANE_DB=str(self.source)))

    def read(self,cold=False):
        return references.retained_reference_path(self.old_archive if cold else self.old_source,
            candidate_path=self.candidate,canonical_path=self.source if cold else None,cold=cold)

    def refused(self,cold=False):
        with self.assertRaisesRegex(ValueError,'^candidate_canonical_reference_cohort_unverified$'):
            self.read(cold)

    @contextmanager
    def removed(self,path):
        saved=path.with_name(path.name+'.preserved');path.rename(saved)
        try:yield saved
        finally:
            if path.is_symlink() or path.is_file():path.unlink()
            elif path.is_dir():path.rmdir()
            saved.rename(path)

    def test_one_full_nonsymlink_walk_per_reference_and_no_path_cache(self):
        original=os.lstat;calls=[]
        def inspect(path,*args,**kwargs):
            calls.append(Path(path));return original(path,*args,**kwargs)
        for cold in (False,True):
            expected=[*reversed(self.root.parents),self.root,self.shared]
            if cold:expected.append(self.cold)
            expected.extend([self.candidate,self.source])
            if cold:expected.append(self.archive)
            with self.subTest(cold=cold),patch.object(references.os,'lstat',side_effect=inspect):
                calls.clear()
                self.assertEqual(self.read(cold),self.archive if cold else self.source)
                self.assertEqual(calls,expected)
                self.assertEqual(self.read(cold),self.archive if cold else self.source)
                self.assertEqual(calls,expected+expected)

    def test_missing_symlink_or_wrong_type_at_every_owned_ancestor_and_leaf_refuses(self):
        for cold in (False,True):
            paths=[self.root.parent,self.root,self.shared,self.candidate,self.source]
            if cold:paths.extend([self.cold,self.archive])
            for path in paths:
                with self.subTest(cold=cold,path=path.name),self.removed(path) as saved:
                    self.refused(cold)
                    path.symlink_to(saved,target_is_directory=saved.is_dir())
                    self.refused(cold)
                    path.unlink()
                    if saved.is_dir():path.write_bytes(b'wrong-parent-type')
                    else:path.mkdir()
                    self.refused(cold)
                self.assertEqual(self.read(cold),self.archive if cold else self.source)

    def test_already_successful_reference_rechecks_env_and_every_replaced_path(self):
        self.assertEqual(self.read(),self.source)
        self.assertEqual(self.read(True),self.archive)
        for key,bad in (('MM_MODE','LIVE'),('MM_PAPER_EPOCH','foreign-epoch'),
                ('MM_STATE_ROOT',str(self.base/'foreign')),('MM_SOLANA_EVIDENCE_PLANE_DB',str(self.candidate))):
            with self.subTest(key=key),patch.dict(os.environ,{key:bad}):
                self.refused();self.refused(True)
        # Replacing even an ancestor with a link to the intact original tree
        # must be rejected on the next reference, including warm readers.
        with self.removed(self.root.parent) as saved:
            self.root.parent.symlink_to(saved,target_is_directory=True)
            self.refused();self.refused(True)
        self.assertEqual(self.read(),self.source)

    def test_foreign_current_and_original_locators_keep_original_direct_behavior(self):
        for locator in (self.source,self.archive,self.base/'missing-foreign.sqlite'):
            for cold in (False,True):
                with self.subTest(locator=locator.name,cold=cold),patch.dict(os.environ,MM_MODE='LIVE'):
                    self.assertEqual(references.retained_reference_path(locator,candidate_path=None,cold=cold),locator)
        with patch.dict(os.environ,MM_STATE_ROOT=str(self.legacy),MM_MODE='LIVE'):
            self.assertEqual(references.retained_reference_path(self.old_source,candidate_path=None),self.old_source)
            self.assertEqual(references.retained_reference_path(self.old_archive,candidate_path=None,cold=True),self.old_archive)


if __name__=='__main__':unittest.main()
