"""Explicit copied-image paths from the fixed protected native setup.

This is a source-owned launch description, not self-authentication or an
environment-selected fallback. The setup authenticates the image and sends
these exact values to the fixed entry after installing its reviewed boundary.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re

from . import namespace_canary as boundary

PROFILE='native-landlock-abi6-x86_64-v1'


class NativeLayoutRefused(RuntimeError):pass


def require(value,code):
    if not value:raise NativeLayoutRefused(code)


@dataclass(frozen=True)
class NativeChildLayout:
    profile:str
    image_root:str
    work_root:str
    parent_pid:int
    manifest_sha256:str

    def __post_init__(self):
        require(type(self.profile) is str and self.profile==PROFILE,'native_layout_profile')
        require(type(self.parent_pid) is int and 1<self.parent_pid<2**31,'native_layout_parent')
        require(type(self.manifest_sha256) is str
            and re.fullmatch('[0-9a-f]{64}',self.manifest_sha256),'native_layout_manifest')
        for value in (self.image_root,self.work_root):
            require(type(value) is str and 0<len(value)<=4096,'native_layout_path')
            path=Path(value)
            require(path.is_absolute() and '..' not in path.parts and str(path)==value,
                'native_layout_path')
        image,work=Path(self.image_root),Path(self.work_root)
        require(image.name=='native-image' and work.name=='native-work'
            and image.parent==work.parent,'native_layout_geometry')
        boundary._private(image);boundary._private(work)

    @property
    def manifest(self):return Path(self.image_root)/'manifest.json'

    @property
    def executable(self):return Path(self.image_root)/'runtime/bin/python3.12'

    @property
    def native_directory(self):return Path(self.work_root)/'native'

    @property
    def temporary_directory(self):return Path(self.work_root)/'tmp'

    @property
    def state_directory(self):return self.native_directory/'state'

    def environment(self):
        # The ELF shim reexecs the same copied interpreter. Its dependencies
        # must resolve inside the exact image on every exec, including tracker.
        return dict(LANG='C',PATH='/nonexistent',TMPDIR=str(self.temporary_directory),
            PYTHONDONTWRITEBYTECODE='1',LD_LIBRARY_PATH=str(Path(self.image_root)/'runtime/lib'))

    def value(self):
        return {key:getattr(self,key) for key in
            ('profile','image_root','work_root','parent_pid','manifest_sha256')}

    @classmethod
    def from_value(cls,value):
        require(type(value) is dict and set(value)=={'profile','image_root','work_root',
            'parent_pid','manifest_sha256'},'native_layout_shape')
        return cls(**value)

    def require_entry(self):
        require(type(self) is NativeChildLayout and os.getppid()==self.parent_pid,
            'native_layout_parent_changed')
        require(Path.cwd()==self.native_directory,'native_layout_entry_directory')
        # Revalidate after the fixed setup's exec; no root/parent path alias may
        # redirect image, work or owned state to another tree.
        boundary._private(self.image_root);boundary._private(self.work_root)
        boundary._private(self.native_directory)
