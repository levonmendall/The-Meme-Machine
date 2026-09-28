"""The identity generator cannot bless arbitrary code or strategy changes."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from certification.build_consistency import reviewed_delta,indexed_files


class BuildConsistencyTests(unittest.TestCase):
    def test_only_reviewed_operational_delta_is_accepted(self):
        before={'strategy.py':('100644','a'),'storage.py':('100644','b')}
        after=dict(before,**{'storage.py':('100644','c')})
        self.assertEqual(reviewed_delta(before,after,{'storage.py'}),['storage.py'])
        after['strategy.py']=('100644','d')
        with self.assertRaisesRegex(ValueError,'build_unreviewed_native_delta'):
            reviewed_delta(before,after,{'storage.py'})

    def test_removal_and_symlink_cannot_be_hash_rebound(self):
        before={'storage.py':('100644','a')}
        for after in ({},{'storage.py':('120000','b')}):
            with self.assertRaisesRegex(ValueError,'build_invalid_native_file'):
                reviewed_delta(before,after,{'storage.py'})

    def test_real_git_index_rejects_unstaged_and_ignored_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            subprocess.run(['git','init','-q',td],check=True)
            (root/'storage.py').write_text('a=1\n')
            subprocess.run(['git','add','storage.py'],cwd=td,check=True)
            self.assertIn('storage.py',indexed_files(root))
            (root/'storage.py').write_text('a=2\n')
            with self.assertRaisesRegex(ValueError,'build_unstaged_native_source'):indexed_files(root)
            subprocess.run(['git','add','storage.py'],cwd=td,check=True)
            (root/'.gitignore').write_text('shadow.py\n')
            (root/'shadow.py').write_text('malicious=True\n')
            with self.assertRaisesRegex(ValueError,'build_untracked_native_source'):indexed_files(root)


if __name__=='__main__':unittest.main()
