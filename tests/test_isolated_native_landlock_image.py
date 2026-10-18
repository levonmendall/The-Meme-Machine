"""Exact copied-image/loader inode predicates; no policy syscall or provider."""
import copy
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import struct
import unittest
from unittest.mock import patch

from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational import isolated_native_image as image
from meme_machine.operational import isolated_native_landlock_image as native
from meme_machine.operational.landlock_canary import _fd_snapshot, _PathRule


def elf(interpreter=None,needed=None):
    """Bounded synthetic parser fixture; never execute it as CPython."""
    interpreter=native.HOST_INTERPRETER if interpreter is None else interpreter
    raw=interpreter.encode()+b'\0';count=3 if needed else 2
    start=64+56*count;dynamic=start+len(raw);strings=dynamic+64
    table=b'\0'+needed.encode()+b'\0' if needed else b''
    end=strings+len(table) if needed else dynamic
    header=struct.pack('<16sHHIQQQIHHHHHH',b'\x7fELF\x02\x01\x01'+b'\0'*9,
        2,62,1,0x400000,64,0,0,64,56,count,0,0,0)
    loads=struct.pack('<IIQQQQQQ',1,5,0,0x400000,0,end,end,4096)
    interp=struct.pack('<IIQQQQQQ',3,4,start,0x400000+start,0,len(raw),len(raw),1)
    if not needed:return header+loads+interp+raw
    segment=struct.pack('<IIQQQQQQ',2,4,dynamic,0x400000+dynamic,0,64,64,8)
    entries=b''.join(struct.pack('<QQ',tag,value) for tag,value in
        ((5,0x400000+strings),(10,len(table)),(1,1),(0,0)))
    return header+loads+interp+segment+raw+entries+table


def fixture(scope,*,interpreter=None,loader=None,needed=None):
    requirements=b'fixed offline requirements\n';entry=b'# explicit source fixture\n'
    value=dict(schema='isolated-native-image-v1',source_commit='a'*40,source_tree='b'*40,
        requirements_sha256=hashlib.sha256(requirements).hexdigest(),
        source_files={image.ENTRY:hashlib.sha256(entry).hexdigest()},dependencies={})
    files={'loader':Path(native.HOST_INTERPRETER).read_bytes() if loader is None else loader,
        'runtime/bin/python3.12':elf(interpreter,needed),
        'app/'+image.ENTRY:entry,'app/requirements.txt':requirements}
    for name,(version,wheel,prefixes) in image.DEPENDENCIES.items():
        path=prefixes[0]+'__init__.py' if prefixes[0].endswith('/') else prefixes[0]
        data=b'# explicit dependency fixture\n';files['deps/'+path]=data
        value['dependencies'][name]=dict(version=version,wheel_sha256=wheel,
            files={path:hashlib.sha256(data).hexdigest()})
    retained=copy.deepcopy(value)
    approval=image.NativeImageApproval(value,authenticate=lambda row:row==retained)
    writer=image._ImageWriter(scope/'native-image')
    for name,data in files.items():
        writer.copy(data,name,executable=name in ('loader','runtime/bin/python3.12'))
    manifest=dict(schema='isolated-native-copied-image-v1',source_commit=value['source_commit'],
        source_tree=value['source_tree'],requirements_sha256=value['requirements_sha256'],
        files=list(writer.files),bytes=writer.bytes,financial_authority=False,provider_calls=0,
        actual_service_restrictions_verified=False)
    raw=image.encoded(manifest);writer.copy(raw,'manifest.json')
    return dict(root=writer.root,manifest=manifest,manifest_sha256=hashlib.sha256(raw).hexdigest(),
        approval=approval)


def rewrite(staged,mutate):
    value=copy.deepcopy(staged['manifest']);mutate(value)
    raw=image.encoded(value);path=staged['root']/'manifest.json'
    path.chmod(0o600);path.write_bytes(raw);path.chmod(0o400)
    staged.update(manifest=value,manifest_sha256=hashlib.sha256(raw).hexdigest())


def bind(staged,**changes):
    expected=copy.deepcopy(staged['manifest'])
    options=dict(manifest_sha256=staged['manifest_sha256'],approval=staged['approval'],
        authenticate_manifest=lambda row:row==expected,profile=native.PROFILE)
    options.update(changes)
    return native.PinnedNativeImage(staged['root'],**options)


class NativeLandlockImageTests(unittest.TestCase):
    def refused(self,staged,code,**changes):
        before=_fd_snapshot()
        with self.assertRaisesRegex(image.Refused,code):bind(staged,**changes)
        self.assertEqual(_fd_snapshot(),before)

    def test_fixed_profile_and_detached_parent_authentication_are_required(self):
        with Scratch() as scope:
            staged=fixture(scope.path)
            for profile in ('namespace','copied-cpython311-x86_64-v1',None):
                self.refused(staged,'image_profile',profile=profile)
            self.refused(staged,'parent_authentication_required',authenticate_manifest=None)
            self.refused(staged,'parent_authentication_required',authenticate_manifest=lambda _:False)
            self.refused(staged,'parent_authentication_required',approval=object())
            self.refused(staged,'manifest_changed',manifest_sha256='c'*64)
            scope.check();scope.success=True

    def test_rules_pin_exact_readonly_files_and_directories_for_existing_path_rule_consumer(self):
        with Scratch() as scope:
            staged=fixture(scope.path);before=_fd_snapshot();fds=[]
            original=native._read;reads=[]
            def read(path,*args,**kwargs):
                reads.append(path);return original(path,*args,**kwargs)
            with patch.object(native,'_read',side_effect=read):
                with bind(staged) as pinned:
                    rules=pinned.rules();self.assertEqual(pinned.rules(),rules)
                    files=[rule for rule in rules if rule.kind=='image_file']
                    directories=[rule for rule in rules if rule.kind=='image_directory']
                    host=[rule for rule in rules if rule.kind=='host_loader']
                    self.assertEqual(len(host),1)
                    self.assertEqual(host[0].name,native.HOST_INTERPRETER)
                    self.assertEqual({rule.name for rule in files},
                        {row['path'] for row in staged['manifest']['files']}|{'manifest.json'})
                    self.assertTrue(directories)
                    for rule in rules:
                        info=os.fstat(rule.descriptor);fds.append(rule.descriptor)
                        self.assertFalse(os.get_inheritable(rule.descriptor))
                        self.assertTrue(fcntl.fcntl(rule.descriptor,fcntl.F_GETFL)&os.O_PATH)
                        # The actual path-rule struct accepts these borrowed
                        # handles/rights; no Kernel/add_rule syscall is called.
                        row=_PathRule(rule.access,rule.descriptor)
                        self.assertEqual((row.access,row.fd),(rule.access,rule.descriptor))
                        if rule.kind=='image_directory':
                            self.assertTrue(stat.S_ISDIR(info.st_mode))
                            self.assertEqual(rule.access,native.READ_DIR)
                        else:
                            self.assertTrue(stat.S_ISREG(info.st_mode))
                            executable=(rule.kind=='host_loader' or rule.name in
                                ('loader','runtime/bin/python3.12'))
                            self.assertEqual(rule.access,native.READ_FILE|(native.EXECUTE if executable else 0))
                        with self.assertRaises(OSError):os.read(rule.descriptor,1)
                    self.assertEqual(len(reads),len(set(reads)))
            self.assertEqual(_fd_snapshot(),before)
            for descriptor in fds:
                with self.assertRaises(OSError):os.fstat(descriptor)
            with self.assertRaisesRegex(image.Refused,'binding_closed'):pinned.rules()
            pinned.close()
            scope.check();scope.success=True

    def test_manifest_source_and_all_approved_dependency_files_must_match(self):
        for key in ('source_commit','source_tree','requirements_sha256'):
            with self.subTest(key=key),Scratch() as scope:
                staged=fixture(scope.path)
                rewrite(staged,lambda row:row.update({key:'c'*(64 if key=='requirements_sha256' else 40)}))
                self.refused(staged,'source_identity')
                scope.check();scope.success=True
        with Scratch() as scope:
            staged=fixture(scope.path)
            rewrite(staged,lambda row:row['files'][-1].update(sha256='c'*64))
            self.refused(staged,'approved_files')
            scope.check();scope.success=True

    def test_manifest_entry_single_file_and_total_byte_bounds_fail_before_opening_members(self):
        changes=(lambda row:row['files'][0].update(bytes=image.MAX_FILE+1),
            lambda row:row['files'][0].update(path='../outside'),
            lambda row:row['files'][0].update(path='/etc/private'),
            lambda row:row['files'].append(dict(row['files'][0])),
            lambda row:row.update(bytes=True),lambda row:row.update(financial_authority=True))
        for mutate in changes:
            with self.subTest(mutate=mutate),Scratch() as scope:
                staged=fixture(scope.path);rewrite(staged,mutate)
                self.refused(staged,'manifest|byte_bound')
                scope.check();scope.success=True
        for name,value in (('MAX_FILES',1),('MAX_BYTES',1)):
            with self.subTest(bound=name),Scratch() as scope:
                staged=fixture(scope.path)
                with patch.object(image,name,value):self.refused(staged,'file_bound|byte_bound')
                scope.check();scope.success=True

    def test_copied_symlink_hardlink_special_and_unlisted_files_are_refused_and_closed(self):
        for kind in ('symlink','hardlink','fifo','unlisted'):
            with self.subTest(kind=kind),Scratch() as scope:
                staged=fixture(scope.path);path=staged['root']/'app'/image.ENTRY
                if kind=='symlink':
                    target=scope.path/'foreign';target.write_bytes(path.read_bytes())
                    path.unlink();path.symlink_to(target)
                elif kind=='hardlink':os.link(path,scope.path/'foreign-hardlink')
                elif kind=='fifo':os.mkfifo(staged['root']/'unexpected-fifo',0o600)
                else:(staged['root']/'unexpected-file').write_bytes(b'fixture')
                self.refused(staged,'file_link|hardlink|special|unlisted')
                scope.check();scope.success=True

    def test_replacement_inherited_handle_and_mode_changes_invalidate_a_live_binding(self):
        for kind in ('replace','inherit','mode'):
            with self.subTest(kind=kind),Scratch() as scope:
                staged=fixture(scope.path);before=_fd_snapshot()
                with bind(staged) as pinned:
                    rule=next(rule for rule in pinned.rules() if rule.name=='app/'+image.ENTRY)
                    path=staged['root']/rule.name
                    if kind=='replace':
                        data=path.read_bytes();path.unlink();path.write_bytes(data);path.chmod(0o400)
                    elif kind=='inherit':os.set_inheritable(rule.descriptor,True)
                    else:path.chmod(0o600)
                    with self.assertRaisesRegex(image.Refused,'binding_changed'):pinned.rules()
                self.assertEqual(_fd_snapshot(),before)
                scope.check();scope.success=True

    def test_foreign_interpreter_missing_elf_closure_and_loader_mismatch_are_refused(self):
        for options,code in ((dict(interpreter='/foreign/loader'),'elf_interpreter'),
                (dict(needed='libmissing.so.1'),'elf_closure'),
                (dict(loader=elf()),'loader_copy_mismatch')):
            with self.subTest(options=options),Scratch() as scope:
                staged=fixture(scope.path,**options);self.refused(staged,code)
                scope.check();scope.success=True

    def test_changed_host_loader_alias_refuses_without_mutating_any_host_file(self):
        with Scratch() as scope:
            staged=fixture(scope.path);alternate=scope.path/'other-loader'
            alternate.write_bytes(Path(native.HOST_INTERPRETER).read_bytes())
            with bind(staged) as pinned,patch.object(native,'HOST_INTERPRETER',str(alternate)):
                with self.assertRaisesRegex(image.Refused,'loader_alias_changed'):pinned.rules()
            scope.check();scope.success=True

    def test_partial_read_host_pin_and_open_failures_close_all_previously_owned_handles(self):
        for failure in ('read','host','open'):
            with self.subTest(failure=failure),Scratch() as scope:
                staged=fixture(scope.path);before=_fd_snapshot()
                if failure=='read':
                    original=native._read
                    def fail(path,*args,**kwargs):
                        if path.name=='python3.12':raise OSError(errno.EIO,'fixed read failure')
                        return original(path,*args,**kwargs)
                    context=patch.object(native,'_read',side_effect=fail)
                elif failure=='host':context=patch.object(native,'_host_loader',side_effect=OSError(errno.EMFILE,'fixed host failure'))
                else:
                    original=native.os.open
                    def fail(path,*args,**kwargs):
                        if Path(path).name=='python3.12':raise OSError(errno.EMFILE,'fixed open failure')
                        return original(path,*args,**kwargs)
                    context=patch.object(native.os,'open',side_effect=fail)
                with context,self.assertRaises(OSError):bind(staged)
                self.assertEqual(_fd_snapshot(),before)
                scope.check();scope.success=True

    def test_partial_pin_failure_and_close_error_still_release_all_owned_handles(self):
        with Scratch() as scope:
            staged=fixture(scope.path);before=_fd_snapshot()
            with patch.object(native.os,'get_inheritable',side_effect=OSError(errno.EIO,'fixed pin failure')):
                with self.assertRaises(OSError):bind(staged)
            self.assertEqual(_fd_snapshot(),before)
            pinned=bind(staged);first=pinned.rules()[0].descriptor;original=native.os.close
            def close(fd):
                original(fd)
                if fd==first:raise OSError(errno.EIO,'fixed post-close failure')
            with patch.object(native.os,'close',side_effect=close),self.assertRaises(OSError):pinned.close()
            self.assertEqual(_fd_snapshot(),before)
            pinned.close()
            scope.check();scope.success=True

    def test_existing_financial_ancestor_and_directory_symlink_guards_remain_required(self):
        for kind in ('financial','symlink'):
            with self.subTest(kind=kind),Scratch() as scope:
                staged=fixture(scope.path);before=_fd_snapshot()
                if kind=='financial':(scope.path/'portfolio.sqlite').touch()
                else:
                    actual=scope.path/'actual-image';staged['root'].rename(actual)
                    staged['root'].symlink_to(actual,target_is_directory=True)
                with self.assertRaises(image.boundary.Blocked):bind(staged)
                self.assertEqual(_fd_snapshot(),before)
                scope.check();scope.success=True


class ActualCopiedImageTests(unittest.TestCase):
    def test_actual_existing_build_manifest_and_copied_runtime_can_be_pinned_without_exec(self):
        # Uses the actual source/runtime/dependency builder once on a frozen
        # tree. This local detached software fixture grants no live approval.
        from tests.test_isolated_native_launcher import offline_software_approval
        with Scratch() as scope:
            approval=offline_software_approval();staged=image.build(scope.path,approval)
            expected=copy.deepcopy(staged['manifest']);before=_fd_snapshot()
            with native.PinnedNativeImage(staged['root'],manifest_sha256=staged['manifest_sha256'],
                    approval=approval,authenticate_manifest=lambda row:row==expected,
                    profile=native.PROFILE) as pinned:
                rules=pinned.rules()
                self.assertEqual(len([rule for rule in rules if rule.kind=='image_file']),
                    len(staged['manifest']['files'])+1)
                self.assertEqual(len([rule for rule in rules if rule.kind=='host_loader']),1)
                self.assertTrue(all(not os.get_inheritable(rule.descriptor) for rule in rules))
                self.assertEqual(pinned.manifest_sha256,staged['manifest_sha256'])
            self.assertEqual(_fd_snapshot(),before)
            scope.check();scope.success=True


if __name__=='__main__':unittest.main()
