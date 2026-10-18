"""Metadata-only CI setup and complete original affected-suite partition."""
import ast
import base64
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace
from importlib.metadata import PackagePath

from engineering.ci import native_principals as ci

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = '1e7af8de5654470b83dca11d92e90b37697ff8b2'
ROOT_MODULE = 'tests.test_current_combined_diagnostic'


def native_modules(text):
    start = text.index('      - name: Run affected native isolation and complete copied-main regressions')
    block = text[start:]
    block = block[block.index('          modules = ['):]
    return ast.literal_eval(block[block.index('['):block.index('          print(')].strip())


class NativeCIPrincipalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.prefix = Path(self.temporary.name)/'runtime'
        self.prefix.mkdir(mode=0o755)
        self.prefix.chmod(0o755)
        self.installation = ci._Installation(self.prefix, os.geteuid(), os.getegid(),
            target_uid=os.geteuid(), target_gid=os.getegid())
        self.addCleanup(self.installation.close)

    def file(self, relative='lib/python3.12/owned.py', body=b'actual unchanged runtime bytes\n'):
        path = self.prefix/relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        for directory in (path.parent, *path.parent.parents):
            if directory == self.prefix or self.prefix in directory.parents:
                directory.chmod(0o755)
        path.write_bytes(body)
        path.chmod(0o644)
        return path

    def test_exact_selected_metadata_installation_preserves_content_and_inode(self):
        path = self.file()
        before = path.stat()
        self.installation.selected(path)
        receipt = self.installation.finish()
        self.assertEqual(path.read_bytes(), b'actual unchanged runtime bytes\n')
        self.assertEqual((path.stat().st_dev, path.stat().st_ino), (before.st_dev, before.st_ino))
        self.assertEqual(receipt['files'], 1)
        self.assertTrue(receipt['metadata_only'])
        self.assertEqual(receipt['source_content_sha256'], receipt['destination_content_sha256'])
        self.assertEqual(receipt['records'][0]['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        source = receipt['records'][0]['source_stat']
        destination = receipt['records'][0]['destination_stat']
        self.assertEqual(source[:7], destination[:7])
        self.assertEqual(source[8:], destination[8:])
        self.assertGreaterEqual(destination[7], source[7])  # chown updates ctime
        for descriptor, *_ in self.installation.files.values():
            self.installation.close()
            with self.assertRaises(OSError) as caught: os.fstat(descriptor)
            self.assertEqual(caught.exception.errno, errno.EBADF)

    def test_only_enumerated_directory_modes_change_and_sibling_is_untouched(self):
        path = self.file()
        sibling = path.parent/'unselected.py'
        sibling.write_bytes(b'not selected');sibling.chmod(0o666)
        path.parent.chmod(0o777)
        self.installation.selected(path)
        receipt = self.installation.finish()
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(sibling.stat().st_mode), 0o666)
        self.assertEqual(receipt['files'], 1)
        self.assertFalse(any(row['path'] == str(sibling) for row in receipt['records']))

    def test_actual_empty_regular_stdlib_file_retains_original_zero_inclusive_contract(self):
        from meme_machine.operational import namespace_runtime as runtime
        path=self.file('lib/python3.12/urllib/__init__.py',body=b'')
        before=path.stat()
        self.assertEqual(runtime._read(path,(self.prefix,),owner=os.geteuid()),b'')
        self.assertEqual(self.installation.selected(path),hashlib.sha256(b'').hexdigest())
        result=self.installation.finish()
        self.assertEqual(result['files'],1);self.assertEqual(result['bytes'],0)
        self.assertEqual(path.read_bytes(),b'')
        self.assertEqual(result['records'][0]['sha256'],hashlib.sha256(b'').hexdigest())
        self.assertEqual(ci.content_identity(before),ci.content_identity(path.stat()))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o644)
        self.assertEqual(path.stat().st_uid,os.geteuid())

    def test_group_world_writable_or_unknown_owner_file_never_becomes_trusted(self):
        path = self.file();path.chmod(0o666)
        with self.assertRaisesRegex(ci.Refused, 'file_trust'): self.installation.selected(path)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o666)
        path.chmod(0o644)
        self.installation.owners = (os.geteuid()+10000,)
        with self.assertRaisesRegex(ci.Refused, 'file_trust'): self.installation.selected(path)

    def test_symlink_leaf_or_parent_and_shared_inode_are_refused(self):
        path = self.file()
        link = self.prefix/'alias.py';link.symlink_to(path)
        with self.assertRaises(OSError): self.installation.selected(link)
        alias = self.prefix/'alias';alias.symlink_to(path.parent, target_is_directory=True)
        with self.assertRaises(OSError): self.installation.selected(alias/path.name)
        hard = self.prefix/'hard.py';os.link(path, hard)
        with self.assertRaisesRegex(ci.Refused, 'shared_file'): self.installation.selected(path)

    def test_special_file_is_nonblocking_and_refused(self):
        path = self.prefix/'fifo';os.mkfifo(path, 0o600)
        with self.assertRaisesRegex(ci.Refused, 'regular_bound'): self.installation.selected(path)

    def test_special_privilege_bits_and_root_only_read_modes_are_not_installed(self):
        path = self.file()
        for mode in (0o4644, 0o2644, 0o1644, 0o600):
            path.chmod(mode)
            with self.subTest(mode=mode), self.assertRaisesRegex(ci.Refused, 'file_trust'):
                self.installation.selected(path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)

    def test_complete_file_byte_and_individual_bounds(self):
        path = self.file()
        with patch.object(ci, 'MAX_FILE', 3):
            with self.assertRaisesRegex(ci.Refused, 'regular_bound') as caught:
                self.installation.selected(path)
            result=ci.failure_record(caught.exception)
            self.assertEqual(result['source_stat']['size'],path.stat().st_size)
            self.assertEqual(result['source_stat']['mode'],0o644)
            self.assertEqual(result['source_stat']['uid'],os.geteuid())
            self.assertEqual(result['code'],'ci_runtime_regular_bound')
            self.assertFalse(result['complete'])
        with patch.object(ci, 'MAX_BYTES', 3):
            with self.assertRaisesRegex(ci.Refused, 'byte_bound'): self.installation.selected(path)
        with patch.object(ci, 'MAX_FILES', 0):
            with self.assertRaisesRegex(ci.Refused, 'file_bound'): self.installation.selected(path)

    def test_truncated_actual_read_fails_without_loop_or_completion(self):
        path = self.file()
        with patch.object(ci.os, 'read', return_value=b''):
            with self.assertRaisesRegex(ci.Refused, 'content_changed'): self.installation.selected(path)
        self.assertFalse(self.installation.files)

    def test_final_content_or_path_replacement_refuses_completion(self):
        path = self.file();self.installation.selected(path)
        path.write_bytes(b'changed after original selection')
        with self.assertRaisesRegex(ci.Refused, 'content_changed'): self.installation.finish()

    def test_stable_open_inode_does_not_authorize_replaced_path(self):
        path = self.file();self.installation.selected(path)
        path.rename(path.with_suffix('.retained'))
        self.file(body=b'new file at original selected pathname\n')
        with self.assertRaisesRegex(ci.Refused, 'path_changed|content_changed'):
            self.installation.finish()

    def test_fixed_public_installer_rejects_unknown_runtime_or_principals_before_open(self):
        with patch.object(ci, '_Installation') as installation, patch.dict(os.environ,
                {'CI':'true', 'GITHUB_ACTIONS':'true'}), patch.object(ci.os, 'geteuid', return_value=0):
            for location, uid, gid in (('/tmp/python',1000,1000), (str(ci.PREFIX),0,1000),
                    (str(ci.PREFIX),1000,0), (str(ci.PREFIX),True,1000)):
                with self.assertRaises(ci.Refused): ci.install(location,uid,gid)
            installation.assert_not_called()

    def test_fixed_loader_transitive_dependency_is_included_in_actual_install_plan(self):
        from meme_machine.operational import isolated_native_image as image
        from meme_machine.operational import namespace_runtime as runtime
        selected = []
        installer = Mock()
        installer.finish.return_value = {}
        executable = ci.PREFIX/'bin/python3.12'
        installer.files = {executable:(None,None,SimpleNamespace(st_mode=0o755),None)}
        def read(path):
            selected.append(path.name)
            return (b'python' if path.name == 'python3.12' else
                    b'loader' if path.name == 'ld-linux-x86-64.so.2' else b'dependency')
        installer.read.side_effect = read
        def elf(data):
            return ('/lib64/ld-linux-x86-64.so.2',[]) if data == b'python' else (
                (None,['libfixture.so.1']) if data == b'loader' else (None,[]))
        exists, resolve = Path.exists, Path.resolve
        def fixture_exists(path):
            return True if path.name == 'libfixture.so.1' else exists(path)
        def fixture_resolve(path, **kwargs):
            return path if path == executable or path.name == 'libfixture.so.1' else resolve(path,**kwargs)
        with patch.object(ci,'_Installation',return_value=installer), \
                patch.object(ci.os,'geteuid',return_value=0), \
                patch.dict(os.environ,{'CI':'true','GITHUB_ACTIONS':'true'}), \
                patch.object(ci.sys,'base_prefix',str(ci.PREFIX)), \
                patch.object(ci.sys,'executable',str(executable)), \
                patch.object(ci.sys,'version_info',(3,12,14)), \
                patch.object(ci.platform,'machine',return_value='x86_64'), \
                patch.object(ci.sysconfig,'get_config_var',return_value='.cpython-312-x86_64-linux-gnu.so'), \
                patch.object(runtime,'_sources',return_value=[]), \
                patch.object(runtime,'EXTENSIONS',[]), \
                patch.object(runtime,'_elf',side_effect=elf), \
                patch.object(image,'NATIVE_MODULES',[]), patch.object(image,'NATIVE_PACKAGES',{}), \
                patch.object(image,'DEPENDENCIES',{}), \
                patch.object(Path,'exists',fixture_exists), \
                patch.object(Path,'resolve',fixture_resolve):
            # There are no actual filesystem or ownership operations here;
            # the real fixed coordinator must still traverse the loader edge.
            ci.install(str(ci.PREFIX),1000,1000)
        self.assertEqual(selected,['python3.12','ld-linux-x86-64.so.2','libfixture.so.1'])
        self.assertEqual(installer.directory.call_args_list, [
            unittest.mock.call(Path('/'),install=False),
            unittest.mock.call(Path('/opt'),install=True),
            unittest.mock.call(Path('/opt/hostedtoolcache'),install=True),
            unittest.mock.call(Path('/opt/hostedtoolcache/Python'),install=True),
            unittest.mock.call(ci.PREFIX.parent,install=True),
            unittest.mock.call(ci.PREFIX,install=True)])
        installer.finish.assert_called_once_with()
        installer.close.assert_called_once_with()

    def test_exact_dependency_hash_narrows_write_bits_and_preserves_original_owner_and_private_reads(self):
        from meme_machine.operational import namespace_runtime as runtime
        prepared=[]
        for mode in (0o664,0o600,0o711):
            path=self.file('lib/python3.12/site-packages/pkg/file_'+str(mode)+'.py')
            path.chmod(mode);before=path.stat();digest=hashlib.sha256(path.read_bytes()).hexdigest()
            prepared.append((mode,path,before,digest))
        for mode,path,before,digest in prepared:
            self.assertEqual(self.installation.selected(path,dependency_sha256=digest),digest)
            after=path.stat()
            self.assertEqual(ci.content_identity(before),ci.content_identity(after))
            self.assertEqual((after.st_uid,after.st_gid),(before.st_uid,before.st_gid))
            self.assertEqual(stat.S_IMODE(after.st_mode),mode&~0o022)
            self.assertEqual(runtime._read(path,(self.prefix,),owner=(0,os.geteuid())),path.read_bytes())
        result=self.installation.finish()
        self.assertEqual(result['schema'],'fixed-hosted-ci-runtime-ownership-v2')
        self.assertTrue(all(row['trust_policy']=='original_package_owner' for row in result['records']))
        self.assertTrue(all(row['sha256']==row['record_sha256'] for row in result['records']))

    def test_crossed_dependency_hash_or_nonpackage_path_cannot_narrow_metadata(self):
        path=self.file('lib/python3.12/site-packages/pkg/source.py');path.chmod(0o664)
        with self.assertRaisesRegex(ci.Refused,'record_hash'):
            self.installation.selected(path,dependency_sha256='0'*64)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o664)
        outside=self.file('lib/python3.12/arbitrary.py');outside.chmod(0o664)
        for expected in ('1'*64,True,'invalid'):
            with self.assertRaisesRegex(ci.Refused,'fixed_selection'):
                self.installation.selected(outside,dependency_sha256=expected)
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode),0o664)

    def distribution_fixture(self):
        from meme_machine.operational import isolated_native_image as image
        path=self.file('lib/python3.12/site-packages/pkg/source.py');path.chmod(0o664)
        entry=PackagePath('pkg/source.py')
        entry.hash=SimpleNamespace(mode='sha256',value=base64.urlsafe_b64encode(
            hashlib.sha256(path.read_bytes()).digest()).rstrip(b'=').decode())
        distribution=SimpleNamespace(version='1.0',files=[entry,PackagePath('fixture.dist-info/METADATA')],
            locate_file=lambda relative:path.parents[1]/relative)
        selected=SimpleNamespace(DEPENDENCIES={'fixture':('1.0','f'*64,('pkg/',))},
            importlib=SimpleNamespace(metadata=SimpleNamespace(distribution=Mock(return_value=distribution))),
            _package_file=image._package_file)
        return path,entry,distribution,selected

    def test_complete_original_distribution_path_and_record_selection_authenticates_bytes(self):
        path,entry,distribution,image=self.distribution_fixture()
        summaries,elf=ci._selected_distributions(self.installation,image,None)
        self.assertEqual(elf,[])
        self.assertEqual(summaries['fixture']['selected_files'],1)
        self.assertEqual(summaries['fixture']['version'],'1.0')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o644)
        self.assertEqual(len(self.installation.finish()['records']),1)

    def test_unknown_distribution_version_duplicate_or_crossed_record_cannot_install(self):
        path,entry,distribution,image=self.distribution_fixture()
        distribution.version='2.0'
        with self.assertRaisesRegex(ci.Refused,'dependency_version'):
            ci._selected_distributions(self.installation,image,None)
        distribution.version='1.0';distribution.files=[entry,entry]
        with self.assertRaisesRegex(ci.Refused,'record_bound'):
            ci._selected_distributions(self.installation,image,None)
        distribution.files=[entry];entry.hash.value=base64.urlsafe_b64encode(b'x'*32).decode()
        with self.assertRaisesRegex(ci.Refused,'record_hash'):
            ci._selected_distributions(self.installation,image,None)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o664)

    def test_failed_directory_trust_publishes_actual_numeric_stat_without_private_paths(self):
        self.prefix.chmod(0o777)
        with self.assertRaisesRegex(ci.Refused,'directory_trust') as caught:
            self.installation.directory(self.prefix,install=False)
        result=ci.failure_record(caught.exception)
        self.assertFalse(result['complete'])
        self.assertEqual(result['status'],'FAILED')
        self.assertEqual(result['directory_role'],'selected_runtime_parent')
        self.assertEqual(result['source_stat']['mode'],0o777)
        self.assertEqual(result['source_stat']['uid'],os.geteuid())
        self.assertEqual(result['destination_stat']['mode'],0o777)
        self.assertNotIn(str(self.prefix),ci.encoded(result).decode())
        self.assertNotIn('facts',result)

    def test_failure_projection_filters_untrusted_messages_fields_and_remains_failed(self):
        private='PRIVATE-DO-NOT-PRINT'
        error=ci.Refused(private,facts=dict(directory_role=private,
            source_stat=dict(uid=True,gid=-1,inode=2**65,mode=0o775,raw_path=private),
            private=private))
        result=ci.failure_record(error)
        self.assertEqual(result['status'],'FAILED');self.assertFalse(result['complete'])
        self.assertIsNone(result['code'])
        self.assertEqual(result['source_stat'],dict(mode=0o775))
        self.assertNotIn(private,ci.encoded(result).decode())
        self.assertIsNone(ci.failure_record(ci.Refused([private],facts=dict(directory_role=[private])))['code'])

    def test_failure_json_is_emitted_but_main_reraises_original_refusal(self):
        failure=ci.Refused('ci_runtime_directory_trust',facts=dict(directory_role='opt',
            source_stat=dict(uid=1001,mode=0o775)))
        output=io.StringIO()
        with patch.object(ci.sys,'argv',['native_principals','--python-location',str(ci.PREFIX),
                '--runner-uid','1001','--runner-gid','1001']), \
                patch.object(ci,'install',side_effect=failure), \
                patch.object(ci.sys,'stdout',output):
            with self.assertRaises(ci.Refused) as caught:ci.main()
        self.assertIs(caught.exception,failure)
        result=json.loads(output.getvalue())
        self.assertEqual(result['status'],'FAILED')
        self.assertFalse(result['complete'])
        self.assertEqual(result['directory_role'],'opt')

    def test_current_ci_partitions_all_original_675_cases_without_disabling_assertions(self):
        original = subprocess.check_output(['git','show',ORIGINAL+':.github/workflows/ci.yml'],
            cwd=ROOT, text=True)
        current = (ROOT/'.github/workflows/ci.yml').read_text()
        old, new = native_modules(original), native_modules(current)
        added=['tests.test_isolated_native_live_parent','tests.test_current_provider_history']
        self.assertEqual((len(old),len(new)), (49,50))
        self.assertEqual(new, [name for name in old if name != ROOT_MODULE]+added)
        def count(modules):
            return sum(sum(isinstance(case,(ast.FunctionDef,ast.AsyncFunctionDef)) and
                case.name.startswith('test_') for owner in ast.parse((ROOT/(module.replace('.','/')+'.py')).read_text()).body
                if isinstance(owner,ast.ClassDef) for case in owner.body) for module in modules)
        def names(module,body):
            return {module+'.'+owner.name+'.'+case.name
                for owner in ast.parse(body).body if isinstance(owner,ast.ClassDef)
                for case in owner.body if isinstance(case,(ast.FunctionDef,ast.AsyncFunctionDef))
                and case.name.startswith('test_')}
        original_names=set().union(*(names(module,subprocess.check_output(
            ['git','show',ORIGINAL+':'+module.replace('.','/')+'.py'],cwd=ROOT)) for module in old))
        current_names=set().union(*(names(module,(ROOT/(module.replace('.','/')+'.py')).read_bytes())
            for module in [ROOT_MODULE,*new]))
        self.assertEqual(len(original_names),675,'every original affected test identity is retained')
        self.assertEqual(original_names-current_names,set(),'no original affected case disappears')
        self.assertEqual((count([ROOT_MODULE]),count(new)), (89,627))
        root = current[current.index('      - name: Run affected root service-diagnostic regressions'):]
        root = root[:root.index('      - name: Run affected native isolation')]
        self.assertIn("'tests.test_current_combined_diagnostic', '--verbose'", root)
        self.assertIn('sudo env', root)
        native = current[current.index('      - name: Run affected native isolation'):]
        native = native[:native.index('      - name: Check CI execution-principal')]
        self.assertNotIn('sudo env', native)
        self.assertIn("('CapInh', 'CapPrm', 'CapEff', 'CapAmb')", native)
        self.assertIn('ci_unprivileged_native_principal_required', native)
        self.assertIn('ci_native_capabilities_must_be_empty', native)
        for block in (root,native):
            self.assertIn('max(soft, 4096)', block)
            self.assertIn('steps.trusted_native_runtime.outcome', block)
            self.assertIn("(github.event_name != 'workflow_dispatch' || inputs.validation != 'full')", block)
            self.assertIn('!cancelled()', block)

    def test_ci_helper_is_outside_every_fixed_copied_native_image_input(self):
        from meme_machine.operational.isolated_native_image import _source_file
        self.assertFalse(_source_file('engineering/ci/native_principals.py'))


if __name__ == '__main__':
    unittest.main()
