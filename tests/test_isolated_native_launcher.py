"""Offline strict image/descriptor/source/lifetime regressions; no providers."""
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import unittest
from unittest.mock import Mock,patch

from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational import isolated_native_image as image
from meme_machine.operational import isolated_native_launcher as launcher


def receipt():
    dependencies={}
    for name,(version,wheel,prefixes) in image.DEPENDENCIES.items():
        path=prefixes[0]+'__init__.py' if prefixes[0].endswith('/') else prefixes[0]
        dependencies[name]=dict(version=version,wheel_sha256=wheel,files={path:'b'*64})
    return dict(schema='isolated-native-image-v1',source_commit='a'*40,source_tree='b'*40,
        source_files={image.ENTRY:'d'*64},
        requirements_sha256=hashlib.sha256(b'fixed requirements\n').hexdigest(),dependencies=dependencies)


def approval(value=None):
    value=receipt() if value is None else value
    exact=copy.deepcopy(value)
    return image.NativeImageApproval(value,authenticate=lambda row:row==exact)


def fixture_image(scope):
    writer=image._ImageWriter(scope/'native-image')
    writer.copy(b'fixed synthetic loader','loader',executable=True)
    writer.copy(b'fixed synthetic interpreter','runtime/bin/python3.12',executable=True)
    writer.copy(b'# fixed synthetic entry\n','app/'+image.ENTRY)
    manifest=dict(schema='isolated-native-copied-image-v1',source_commit='a'*40,source_tree='b'*40,
        requirements_sha256='c'*64,files=list(writer.files),bytes=writer.bytes,
        financial_authority=False,provider_calls=0,actual_service_restrictions_verified=False)
    raw=image.encoded(manifest);writer.copy(raw,'manifest.json')
    return dict(root=writer.root,manifest=manifest,manifest_sha256=hashlib.sha256(raw).hexdigest())


def offline_software_approval():
    """Exact detached local software fixture, never a live source approval."""
    root=Path(image.__file__).resolve().parents[2]
    def git(*args):return image._git(root,*args)
    rows=git('ls-tree','-r','-z','HEAD','--','meme_machine','engineering/solana_capacity',
             'engineering/__init__.py','operational/forward-survivor/NEXT_PROOF.json').split(b'\0')
    source_files={}
    for raw in rows:
        if not raw:continue
        header,name=raw.split(b'\t',1);name=name.decode()
        if image._source_file(name):
            source_files[name]=hashlib.sha256(git('cat-file','blob',header.decode().split()[2])).hexdigest()
    dependencies={}
    for name,(version,wheel,prefixes) in image.DEPENDENCIES.items():
        package=importlib.metadata.distribution(name)
        files={str(path):hashlib.sha256(package.locate_file(path).read_bytes()).hexdigest()
            for path in package.files or () if image._package_file(str(path),prefixes)}
        dependencies[name]=dict(version=version,wheel_sha256=wheel,files=files)
    row=dict(schema='isolated-native-image-v1',source_commit=git('rev-parse','HEAD').decode().strip(),
        source_tree=git('rev-parse','HEAD^{tree}').decode().strip(),source_files=source_files,
        requirements_sha256=hashlib.sha256((root/'requirements.txt').read_bytes()).hexdigest(),
        dependencies=dependencies)
    # Explicit known offline fixture authenticator only; no application default.
    return approval(row)


class ImageAdmissionTests(unittest.TestCase):
    def test_approval_requires_detached_parent_authentication_and_exact_pins(self):
        value=receipt()
        with self.assertRaisesRegex(image.Refused,'authentication_required'):
            image.NativeImageApproval(value,authenticate=lambda _:False)
        pinned=approval(value);value['dependencies']['grpcio']['files'].clear()
        self.assertTrue(pinned.value()['dependencies']['grpcio']['files'])
        with self.assertRaises(AttributeError):pinned._encoded=b'changed'
        for change in (dict(command='anything'),dict(source_commit='main'),dict(dependencies={})):
            with self.subTest(change=change),self.assertRaises(image.Refused):approval(dict(receipt(),**change))
        for name in image.DEPENDENCIES:
            changed=receipt();changed['dependencies'][name]['wheel_sha256']='d'*64
            with self.assertRaisesRegex(image.Refused,'dependency_identity'):approval(changed)

    def test_package_manifest_refuses_paths_sites_metadata_and_unreviewed_files(self):
        for name in ('/etc/private','../private','grpc/__pycache__/bad.pyc','grpc/bad.pth',
                     'grpc/bad.dist-info/METADATA','unreviewed/code.py','grpc/private.sock'):
            changed=receipt();changed['dependencies']['grpcio']['files']={name:'b'*64}
            with self.subTest(name=name),self.assertRaisesRegex(image.Refused,'dependency_file'):
                approval(changed)

    def test_authenticated_source_reads_use_immutable_commit_tree_after_HEAD_moves(self):
        calls=[];pinned=approval();value=pinned.value()
        def git(root,*args):
            calls.append(args)
            if args==('rev-parse','HEAD'):return (value['source_commit']+'\n').encode()
            if args==('rev-parse','HEAD^{tree}'):return (value['source_tree']+'\n').encode()
            if args[0]=='status':return b''
            if args[0]=='show':
                self.assertEqual(args[1],value['source_commit']+':requirements.txt')
                return b'fixed requirements\n'
            if args[0]=='ls-tree':
                self.assertEqual(args[3],value['source_tree'])
                return ('100644 blob '+'c'*40+'\t'+image.ENTRY+'\0').encode()
            self.fail('unreviewed source read '+repr(args))
        with patch.object(image,'_git',side_effect=git):
            root,requirements,objects=image.source_objects(pinned)
        self.assertEqual(objects,[(image.ENTRY,'c'*40)])
        self.assertFalse(any('HEAD:' in str(call) for call in calls))

    def test_wrong_dirty_or_missing_entry_source_fails_before_copy(self):
        pinned=approval();value=pinned.value()
        def valid(root,*args):
            if args==('rev-parse','HEAD'):return value['source_commit'].encode()
            if args==('rev-parse','HEAD^{tree}'):return value['source_tree'].encode()
            if args[0]=='show':return b'fixed requirements\n'
            return b''
        with patch.object(image,'_git',side_effect=valid):
            with self.assertRaisesRegex(image.Refused,'fixed_entry_missing'):image.source_objects(pinned)
        with patch.object(image,'_git',return_value=b'not the approved source'):
            with self.assertRaisesRegex(image.Refused,'source_mismatch'):image.source_objects(pinned)
        def dirty(root,*args):return b'?? unreviewed.py\n' if args[0]=='status' else valid(root,*args)
        with patch.object(image,'_git',side_effect=dirty):
            with self.assertRaisesRegex(image.Refused,'source_dirty'):image.source_objects(pinned)

    def test_writer_bounds_and_manifest_identity_are_checked_without_host_install_dependency(self):
        with Scratch() as scope:
            staged=fixture_image(scope.path)
            self.assertEqual(launcher._verify_image(staged['root'],staged['manifest_sha256']),staged['manifest'])
            self.assertEqual(len(staged['manifest']['files']),3) # Excludes its own envelope, no mutable alias.
            source=staged['root']/'app'/image.ENTRY
            self.assertTrue(stat.S_ISREG(source.lstat().st_mode))
            source.chmod(0o600);source.write_bytes(b'changed')
            with self.assertRaisesRegex(image.Refused,'image_regular|image_changed'):
                launcher._verify_image(staged['root'],staged['manifest_sha256'])
            scope.check();scope.success=True
        with Scratch() as scope:
            writer=image._ImageWriter(scope.path/'bounded')
            with patch.object(image,'MAX_BYTES',3):
                with self.assertRaisesRegex(image.Refused,'size_bound'):writer.copy(b'four','x')
            self.assertFalse((writer.root/'x').exists())
            scope.check();scope.success=True

    def test_link_special_or_unlisted_image_member_cannot_enter_namespace(self):
        for kind in ('link','fifo','unlisted'):
            with self.subTest(kind=kind),Scratch() as scope:
                staged=fixture_image(scope.path)
                extra=staged['root']/'unlisted'
                if kind=='link':extra.symlink_to('/etc/passwd')
                elif kind=='fifo':os.mkfifo(extra,0o600)
                else:extra.write_bytes(b'fixture')
                with self.assertRaisesRegex(image.Refused,'image_special|image_unlisted'):
                    launcher._verify_image(staged['root'],staged['manifest_sha256'])
                scope.check();scope.success=True


class DescriptorAndLifetimeTests(unittest.TestCase):
    def test_actual_fixed_image_imports_spawn_SQLite_and_graceful_TERM_cleanup(self):
        if os.geteuid()==0:self.skipTest('BLOCKED: actual image proof requires nonroot caller')
        if Path(sys.executable).resolve().stat().st_uid!=0:
            self.skipTest('BLOCKED: actual image proof requires root-owned core runtime')
        with Scratch() as scope:
            result=launcher.prove_image(scope.path,offline_software_approval())
            if result['status']=='BLOCKED' and result.get('code') in (
                    'namespace_unshare_refused','namespace_mount_refused','native_launcher_pivot_refused'):
                self.assertIn(result.get('error_number'),(1,13,22,38,95),result)
                scope.check();scope.success=True
                self.skipTest('BLOCKED: actual kernel/LSM namespace capability unavailable')
            self.assertEqual(result['status'],'ISOLATED_NATIVE_IMAGE_PROVEN',result)
            self.assertEqual(result['child_exit'],0,result)
            self.assertTrue(all(result['checks'].values()),result)
            self.assertTrue(result['parent_namespaces_unchanged'])
            self.assertTrue(result['parent_cwd_unchanged'])
            self.assertFalse(result['native_runners_started'])
            self.assertFalse(result['native_source_started'])
            self.assertFalse(result['economic_preparation_exercised'])
            self.assertFalse(result['financial_authority'])
            self.assertFalse(result['production_equivalent'])
            self.assertFalse(result['native_resource_profile_verified'])
            self.assertEqual(result['proof_nofile_limit'],4096)
            self.assertEqual(result['provider_calls'],0)
            import sqlite3
            database=sqlite3.connect(scope.path/'native-work/native/image-proof.sqlite')
            self.assertEqual(database.execute('PRAGMA integrity_check').fetchone(),('ok',))
            self.assertEqual(database.execute('SELECT value FROM proof ORDER BY value').fetchall(),[(42,),(43,)])
            database.close()
            scope.check();scope.success=True

    def test_only_unnamed_stream_and_readonly_anonymous_facts_pipe_are_admitted(self):
        read,write=os.pipe2(os.O_CLOEXEC)
        try:
            parent,child=socket.socketpair()
            with parent,child:
                launcher._channel_descriptors(child.fileno(),read)
                with self.assertRaisesRegex(image.Refused,'facts_descriptor'):
                    launcher._channel_descriptors(child.fileno(),write)
            parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
            with parent,child,self.assertRaisesRegex(image.Refused,'transport_descriptor'):
                launcher._channel_descriptors(child.fileno(),read)
        finally:os.close(read);os.close(write)

    def test_fixed_launch_has_scrubbed_environment_exact_passfds_and_no_preexec(self):
        with Scratch() as scope:
            staged=fixture_image(scope.path);read,write=os.pipe2(os.O_CLOEXEC)
            parent,child=socket.socketpair()
            transport_fd=child.fileno()
            try:
                with parent,child,patch.object(launcher.subprocess,'Popen',return_value=Mock(pid=123456)) as popen,\
                        patch.object(launcher,'NativeChild',return_value='owned'):
                    self.assertEqual(launcher._start(scope.path,staged,child,read,mode='native'),'owned')
                args=popen.call_args
                self.assertEqual(args.kwargs['env'],{})
                self.assertTrue(args.kwargs['close_fds'])
                self.assertTrue(args.kwargs['start_new_session'])
                self.assertEqual(args.kwargs['pass_fds'],(transport_fd,read))
                self.assertNotIn('preexec_fn',args.kwargs)
                self.assertIn('-S',args.args[0])
            finally:os.close(read);os.close(write)
            scope.check();scope.success=True

    def test_nonzero_exit_never_keeps_a_success_receipt(self):
        with Scratch() as scope:
            code='import json;print(json.dumps({"status":"PASS","financial_authority":False}));raise SystemExit(1)'
            process=subprocess.Popen([sys.executable,'-I','-B','-S','-c',code],env={},
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
            owner=launcher.NativeChild(process,launcher.time.monotonic(),wall=2)
            result=owner.wait(seconds=2)
            self.assertEqual(result['status'],'BLOCKED')
            self.assertEqual(result['code'],'native_launcher_child_failed')
            self.assertEqual(result['child_exit'],1)
            scope.check();scope.success=True

    def test_output_is_bounded_before_append_and_only_own_group_is_killed(self):
        with Scratch() as scope:
            code='import os;os.write(1,b"x"*80000)'
            process=subprocess.Popen([sys.executable,'-I','-B','-S','-c',code],env={},
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
            owner=launcher.NativeChild(process,launcher.time.monotonic(),wall=2)
            result=owner.wait(seconds=2)
            self.assertEqual(result['status'],'BLOCKED')
            self.assertEqual(result['code'],'native_launcher_output_bound')
            self.assertLessEqual(len(owner.output['stdout']),launcher.OUTPUT_BOUND)
            self.assertIsNotNone(process.returncode)
            scope.check();scope.success=True

    def test_root_setup_and_unknown_target_are_refused_without_kernel_changes(self):
        with Scratch() as scope:
            value=dict(root=str(scope.path/'native-rootfs'),work=str(scope.path/'native-work'),
                image=str(scope.path/'native-image'),manifest_sha256='a'*64,parent_pid=os.getpid(),
                transport_fd=3,facts_fd=4,mode='native')
            with patch.object(launcher.boundary,'Kernel') as kernel,patch.object(launcher.os,'geteuid',return_value=0):
                with self.assertRaisesRegex(image.Refused,'nonroot_required'):launcher._setup(value)
            kernel.return_value.unshare.assert_not_called()
            for changed in (dict(mode='arbitrary'),dict(command='anything'),dict(facts_fd=3),dict(work='/srv/private')):
                with self.assertRaises(image.Refused):launcher._spec(dict(value,**changed))
            scope.check();scope.success=True


if __name__=='__main__':unittest.main()
