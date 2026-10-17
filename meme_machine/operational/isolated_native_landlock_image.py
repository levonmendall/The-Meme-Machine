"""Pin the existing copied image for a future explicit Landlock rule consumer.

No policy syscall, exec, namespace fallback or provider operation exists here.
The protected parent authenticates the original copied-image manifest using its
retained build evidence; its checksum is never its own authenticator. All held
descriptors are CLOEXEC and stay owned until this binding is closed.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import sys

from . import isolated_native_image as image
from . import namespace_runtime as runtime
from meme_machine.runtime.isolated_native_spawn import SHIM_PATH,trampoline

HOST_INTERPRETER='/lib64/ld-linux-x86-64.so.2'
PROFILE='copied-cpython312-x86_64-v1'
READ_FILE=1<<2
READ_DIR=1<<3
EXECUTE=1
_SCHEMA='isolated-native-copied-image-v1'
_IDENTITY=('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size',
           'st_mtime_ns','st_ctime_ns')


def _identity(info):return tuple(getattr(info,key) for key in _IDENTITY)


@dataclass(frozen=True)
class ImagePathRule:
    """Exact O_PATH inode and rights for the future reviewed path-rule consumer.

    The descriptor is borrowed from PinnedNativeImage; do not close or inherit
    it. Call binding.rules() immediately before adding rules, then keep the
    binding alive through installation. No directory rule grants READ_FILE.
    """
    descriptor:int
    access:int
    kind:str
    name:str


def _no_links(path,*,owner,private=False):
    for node in (path,*path.parents):
        info=node.lstat()
        image.require(not stat.S_ISLNK(info.st_mode),'landlock_image_ancestor_link')
    info=path.lstat()
    image.require(stat.S_ISDIR(info.st_mode) and info.st_uid==owner
        and (stat.S_IMODE(info.st_mode)==0o700 if private
             else not stat.S_IMODE(info.st_mode)&0o022),'landlock_image_directory')


def _pin(path,*,owner,directory=False):
    # O_PATH is enough for Landlock and does not retain a readable host file.
    flags=os.O_PATH|os.O_CLOEXEC|os.O_NOFOLLOW
    if directory:flags|=os.O_DIRECTORY
    fd=os.open(path,flags)
    try:
        info=os.fstat(fd)
        image.require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and info.st_uid==owner,'landlock_image_inode')
        image.require(directory or info.st_nlink==1,'landlock_image_hardlink')
        image.require(not os.get_inheritable(fd),'landlock_image_descriptor')
        return fd,info
    except BaseException:os.close(fd);raise


def _read(path,info,*,maximum):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    try:
        image.require(_identity(os.fstat(fd))==_identity(info)
            and 0<=info.st_size<=maximum,'landlock_image_read_identity')
        chunks=[];size=0
        while size<=maximum:
            part=os.read(fd,min(1024*1024,maximum+1-size))
            if not part:break
            chunks.append(part);size+=len(part)
        image.require(size==info.st_size and _identity(os.fstat(fd))==_identity(info),
            'landlock_image_read_changed')
        return b''.join(chunks)
    finally:os.close(fd)


def _host_loader():
    alias=Path(HOST_INTERPRETER)
    # Only the fixed ELF interpreter may use root-owned loader aliases. Never
    # accept a caller-selected host path or a host directory read permission.
    for node in (alias,*alias.parents):
        info=node.lstat()
        image.require(info.st_uid==0 and (stat.S_ISLNK(info.st_mode)
            or not stat.S_IMODE(info.st_mode)&0o022),'landlock_loader_trust')
    canonical=alias.resolve(strict=True)
    for node in (canonical,*canonical.parents):
        info=node.lstat()
        image.require(info.st_uid==0 and not stat.S_ISLNK(info.st_mode)
            and not stat.S_IMODE(info.st_mode)&0o022,'landlock_loader_trust')
    fd,info=_pin(canonical,owner=0)
    try:
        data=_read(canonical,info,maximum=image.MAX_FILE)
        runtime._elf(data)
        return fd,info,canonical,data
    except BaseException:os.close(fd);raise


class PinnedNativeImage:
    """Authenticated existing manifest plus bounded exact-inode rule handles.

    authenticate_manifest is a fixed protected-parent function checking its
    original build result, not a child-supplied predicate or checksum equality.
    This object proves only file binding; rules() neither installs Landlock nor
    supplies the missing seccomp, owned-process, proc-liveness or spawn fences.
    """
    def __init__(self,root,*,manifest_sha256,approval,authenticate_manifest,profile):
        self._held=[];self._rules=[];self._closed=False;self._loader=None
        try:
            image.require(profile==PROFILE and type(profile) is str
                and sys.platform=='linux' and platform.machine()=='x86_64'
                and sys.version_info[:3]==(3,12,14),'landlock_image_profile')
            image.require(type(approval) is image.NativeImageApproval
                and callable(authenticate_manifest),'landlock_image_parent_authentication_required')
            image.require(image._digest(manifest_sha256),'landlock_image_manifest_identity')
            self.root=Path(root)
            image.require(self.root.is_absolute() and '..' not in self.root.parts
                and self.root.name=='native-image','landlock_image_root')
            image.boundary._private(self.root)
            _no_links(self.root,owner=os.geteuid(),private=True)
            manifest=self._file('manifest.json',maximum=512*1024)
            image.require(hashlib.sha256(manifest).hexdigest()==manifest_sha256,
                'landlock_image_manifest_changed')
            value=json.loads(manifest)
            image.require(manifest==image.encoded(value),'landlock_image_manifest_encoding')
            image.require(authenticate_manifest(json.loads(manifest)) is True,
                'landlock_image_parent_authentication_required')
            image.require(type(value) is dict and set(value)=={'schema','source_commit',
                'source_tree','requirements_sha256','files','bytes','financial_authority',
                'provider_calls','actual_service_restrictions_verified'}
                and value['schema']==_SCHEMA and value['financial_authority'] is False
                and type(value['provider_calls']) is int and value['provider_calls']==0
                and value['actual_service_restrictions_verified'] is False,
                'landlock_image_manifest')
            approved=approval.value()
            image.require(all(value[key]==approved[key] for key in
                ('source_commit','source_tree','requirements_sha256')),'landlock_image_source_identity')
            rows=value['files']
            image.require(type(rows) is list and 0<len(rows)<=image.MAX_FILES,
                'landlock_image_file_bound')
            indexed={};total=0
            for row in rows:
                image.require(type(row) is dict and set(row)=={'path','bytes','sha256'},
                    'landlock_image_manifest_file')
                name=row['path'];path=Path(name) if type(name) is str else None
                image.require(path is not None and name==str(path) and not path.is_absolute()
                    and '..' not in path.parts and name!='manifest.json'
                    and name not in indexed and image._digest(row['sha256'])
                    and type(row['bytes']) is int and 0<=row['bytes']<=image.MAX_FILE,
                    'landlock_image_manifest_file')
                indexed[name]=row;total+=row['bytes']
            image.require(type(value['bytes']) is int and value['bytes']==total
                and total<=image.MAX_BYTES,'landlock_image_byte_bound')
            expected={'app/'+name:digest for name,digest in approved['source_files'].items()}
            expected['app/requirements.txt']=approved['requirements_sha256']
            for package in approved['dependencies'].values():
                for name,digest in package['files'].items():
                    key='deps/'+name
                    image.require(key not in expected or expected[key]==digest,'landlock_image_dependency_conflict')
                    expected[key]=digest
            image.require({name for name in indexed if name.startswith(('app/','deps/'))}==expected.keys()
                and all(indexed[name]['sha256']==digest for name,digest in expected.items()),
                'landlock_image_approved_files')
            image.require({'loader','runtime/bin/python3.12'}<=indexed.keys()
                and all(name in ('loader','runtime/bin/python3.12',SHIM_PATH) or name.startswith(
                    ('runtime/lib/','app/','deps/')) for name in indexed),'landlock_image_layout')
            dependencies=[];copied_loader=None
            for name,row in indexed.items():
                data=self._file(name,maximum=image.MAX_FILE)
                image.require(len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'],
                    'landlock_image_file_changed')
                if name=='loader':copied_loader=data
                if name==SHIM_PATH:
                    image.require(data==trampoline(self.root/'runtime/bin/python3.12'),
                        'landlock_image_spawn_shim_changed')
                if data.startswith(b'\x7fELF'):
                    interpreter,needed=runtime._elf(data);dependencies.extend(needed)
                    image.require(interpreter in (None,HOST_INTERPRETER),'landlock_image_elf_interpreter')
                    if name=='runtime/bin/python3.12':
                        image.require(interpreter==HOST_INTERPRETER,'landlock_image_elf_interpreter')
                else:image.require(name not in ('loader','runtime/bin/python3.12'),'landlock_image_elf_required')
            image.require(all('runtime/lib/'+name in indexed for name in dependencies),
                'landlock_image_elf_closure')
            self._directories(indexed)
            fd,info,path,data=_host_loader()
            self._held.append((fd,path,_identity(info)))
            image.require(data==copied_loader,'landlock_loader_copy_mismatch')
            self._loader=(path,_identity(info))
            self._rules.append(ImagePathRule(fd,READ_FILE|EXECUTE,'host_loader',HOST_INTERPRETER))
            self.manifest_sha256=manifest_sha256
            self._manifest=manifest
            self.rules()
        except BaseException as original:
            try:self.close()
            except BaseException as cleanup:raise original from cleanup
            raise

    def _file(self,name,*,maximum):
        path=self.root/name
        image.require(path.resolve(strict=True)==path,'landlock_image_file_link')
        fd,info=_pin(path,owner=os.geteuid())
        self._held.append((fd,path,_identity(info)))
        executable=name in ('loader','runtime/bin/python3.12',SHIM_PATH)
        image.require(stat.S_IMODE(info.st_mode)==(0o500 if executable else 0o400),
            'landlock_image_file_mode')
        data=_read(path,info,maximum=maximum)
        self._rules.append(ImagePathRule(fd,READ_FILE|(EXECUTE if executable else 0),
            'image_file',name))
        return data

    def _directories(self,indexed):
        expected=set(indexed)|{'manifest.json'};discovered=set();directories={self.root}
        for count,node in enumerate(self.root.rglob('*'),1):
            image.require(count<=4096,'landlock_image_entry_bound')
            info=node.lstat()
            if stat.S_ISDIR(info.st_mode):directories.add(node)
            else:
                image.require(stat.S_ISREG(info.st_mode),'landlock_image_special')
                discovered.add(str(node.relative_to(self.root)))
        image.require(discovered==expected,'landlock_image_unlisted')
        for path in sorted(directories):
            _no_links(path,owner=os.geteuid(),private=True)
            fd,info=_pin(path,owner=os.geteuid(),directory=True)
            self._held.append((fd,path,_identity(info)))
            self._rules.append(ImagePathRule(fd,READ_DIR,'image_directory',str(path.relative_to(self.root))))

    def rules(self):
        image.require(not self._closed,'landlock_image_binding_closed')
        for fd,path,identity in self._held:
            image.require(_identity(os.fstat(fd))==identity and _identity(path.lstat())==identity
                and not os.get_inheritable(fd),'landlock_image_binding_changed')
        if self._loader is not None:
            path,identity=self._loader
            image.require(Path(HOST_INTERPRETER).resolve(strict=True)==path
                and _identity(path.lstat())==identity,'landlock_loader_alias_changed')
        return tuple(self._rules)

    def close(self):
        if self._closed:return
        self._closed=True
        failure=None
        for fd,_,_ in reversed(self._held):
            try:os.close(fd)
            except OSError as error:
                if failure is None:failure=error
        self._held.clear();self._rules.clear()
        if failure is not None:raise failure

    def __enter__(self):return self
    def __exit__(self,*error):self.close()
