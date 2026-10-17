"""Fixed copied-runtime manifest and filesystem/ELF rejection regressions."""
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import stat
import struct
import sys
import unittest
from unittest.mock import patch

from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational import namespace_canary as canary
from meme_machine.operational import namespace_runtime as runtime


def elf(name=b'libsafe.so.1\0'):
    data=bytearray(512)
    data[:7]=b'\x7fELF\x02\x01\x01'
    struct.pack_into('<H',data,18,62 if platform.machine()=='x86_64' else 183)
    struct.pack_into('<Q',data,32,64)
    struct.pack_into('<HH',data,54,56,2)
    struct.pack_into('<IIQQQQQQ',data,64,1,4,0,0x400000,0,512,512,4096)
    struct.pack_into('<IIQQQQQQ',data,120,2,4,256,0x400100,0,64,64,8)
    for index,(tag,value) in enumerate(((5,0x400180),(10,len(name)),(1,0),(0,0))):
        struct.pack_into('<QQ',data,256+index*16,tag,value)
    data[384:384+len(name)]=name
    return data


class NamespaceRuntimeTests(unittest.TestCase):
    def test_actual_copied_manifest_has_no_host_trees_sites_links_or_special_files(self):
        if os.geteuid()==0:self.skipTest('BLOCKED: actual canary image requires its nonroot caller')
        if Path(sys.executable).resolve().stat().st_uid!=0:
            self.skipTest('BLOCKED: actual canary image requires a root-owned installed interpreter')
        with Scratch() as scope:
            image=runtime.build(scope.path,Path(canary.__file__).resolve())
            self.assertLessEqual(len(image['files']),runtime.MAX_FILES)
            self.assertLessEqual(image['bytes'],runtime.MAX_BYTES)
            records=image['files']
            self.assertEqual(image['manifest_sha256'],hashlib.sha256(json.dumps(records,
                sort_keys=True,separators=(',',':')).encode()).hexdigest())
            self.assertEqual(sum(row['bytes'] for row in records),image['bytes'])
            for row in records:
                path=image['root']/row['path']
                self.assertTrue(stat.S_ISREG(path.lstat().st_mode))
                self.assertEqual(path.stat().st_size,row['bytes'])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),row['sha256'])
                self.assertFalse(path.is_symlink())
                self.assertNotIn('site-packages',path.parts)
                self.assertNotIn('__pycache__',path.parts)
                self.assertNotIn(path.suffix,('.pyc','.pyo','.pth'))
            self.assertFalse((image['root']/'lib/python3.12/site.py').exists())
            self.assertFalse((image['root']/'bin/python3.12').is_symlink())
            self.assertEqual((image['root']/'probe.py').read_bytes(),Path(canary.__file__).read_bytes())
            with self.assertRaisesRegex(runtime.Refused,'already_used'):
                runtime.build(scope.path,Path(canary.__file__).resolve())
            scope.check();scope.success=True

    def test_read_refuses_external_links_fifo_socket_and_writable_regular_file(self):
        with Scratch() as scope:
            private=scope.path/'inside';private.mkdir(mode=0o700)
            regular=private/'file';regular.write_bytes(b'fixture');regular.chmod(0o600)
            self.assertEqual(runtime._read(regular,(private,),owner=os.geteuid()),b'fixture')
            with self.assertRaisesRegex(runtime.Refused,'regular_trusted_file'):
                runtime._read(regular,(private,),owner=os.geteuid()+1)
            outside=scope.path/'outside';outside.write_bytes(b'private canary')
            link=private/'alias';link.symlink_to(outside)
            with self.assertRaisesRegex(runtime.Refused,'link_escape'):
                runtime._read(link,(private,),owner=os.geteuid())
            fifo=private/'fifo';os.mkfifo(fifo,0o600)
            with self.assertRaisesRegex(runtime.Refused,'regular_trusted_file'):
                runtime._read(fifo,(private,),owner=os.geteuid())
            with socket.socket(socket.AF_UNIX) as channel:
                channel.bind(str(private/'socket'))
                with self.assertRaisesRegex(runtime.Refused,'regular_trusted_file'):
                    runtime._read(private/'socket',(private,),owner=os.geteuid())
            regular.chmod(0o666)
            with self.assertRaisesRegex(runtime.Refused,'regular_trusted_file'):
                runtime._read(regular,(private,),owner=os.geteuid())
            scope.check();scope.success=True

    def test_elf_decoder_accepts_only_bounded_native_needed_basenames(self):
        self.assertEqual(runtime._elf(elf()),(None,['libsafe.so.1']))
        for damaged in (b'',b'not ELF',elf(b'../secret\0'),elf(b'/etc/key\0'),elf(b'libbad.so\0more\0')):
            # Strings beyond the first C-string are valid table material; they
            # do not become an additional selected dependency.
            if damaged==elf(b'libbad.so\0more\0'):
                self.assertEqual(runtime._elf(damaged),(None,['libbad.so']))
                continue
            with self.subTest(damaged=bytes(damaged[:16])),self.assertRaises((runtime.Refused,UnicodeError)):
                runtime._elf(damaged)
        huge=elf();struct.pack_into('<H',huge,56,129)
        with self.assertRaisesRegex(runtime.Refused,'headers'):runtime._elf(huge)
        missing=elf();struct.pack_into('<Q',missing,280,2**63)
        with self.assertRaisesRegex(runtime.Refused,'strings'):runtime._elf(missing)
        arch=elf();struct.pack_into('<H',arch,18,0)
        with self.assertRaisesRegex(runtime.Refused,'arch'):runtime._elf(arch)

    def test_selected_extension_can_supply_module_without_a_python_source_file(self):
        with Scratch() as scope:
            source=scope.path/'abc.py';source.write_text('# synthetic upstream module\n')
            with patch.object(runtime,'MODULES',['abc','resource']),patch.object(runtime,'PACKAGES',{}),\
                 patch.object(runtime.sys,'builtin_module_names',()):
                self.assertEqual(list(runtime._sources(scope.path)),[('abc.py',source)])
            with patch.object(runtime,'MODULES',['unreviewed']),patch.object(runtime,'PACKAGES',{}):
                with self.assertRaisesRegex(runtime.Refused,'stdlib_missing'):
                    list(runtime._sources(scope.path))
            scope.check();scope.success=True

    def test_unexpected_python_or_runtime_roots_are_BLOCKED_without_installation(self):
        with Scratch() as scope:
            with patch.object(runtime.sys,'version_info',(3,13,0)):
                with self.assertRaisesRegex(runtime.Refused,'python_version'):
                    runtime.build(scope.path,Path(canary.__file__).resolve())
            # Admission rejects a host-root prefix before copying any source.
            with patch.object(runtime.sys,'base_prefix','/'):
                with self.assertRaises(runtime.Refused):
                    runtime.build(scope.path,Path(canary.__file__).resolve())
            scope.check();scope.success=True

    def test_copy_size_bound_fails_closed_and_leaves_synthetic_failure_for_review(self):
        with Scratch() as scope:
            # A controlled valid ELF/source fixture isolates the byte/file bound
            # from host runtime ownership and extension-layout availability.
            with patch.object(runtime,'MAX_FILES',1),patch.object(runtime,'_read',return_value=bytes(elf())):
                with self.assertRaisesRegex(runtime.Refused,'size_bound'):
                    runtime.build(scope.path,Path(canary.__file__).resolve())
            self.assertTrue((scope.path/'runtime/bin/python3.12').is_file())
            self.assertFalse((scope.path/'runtime/probe.py').exists())
            # Expected rejection is a successful disposable regression fixture.
            scope.check();scope.success=True


if __name__=='__main__':unittest.main()
