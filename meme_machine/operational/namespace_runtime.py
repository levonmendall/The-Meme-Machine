"""Fixed CPython3.12 canary image: copied regular files, no host directory binds.

This supports namespace_canary only. It cannot select an application, command,
provider, site package or arbitrary filesystem tree. All source-library roots
are trusted root-owned installations; the canary source is separately pinned.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import struct
import sys
import sysconfig


class Refused(RuntimeError):
    pass


def require(value, code):
    if not value:raise Refused(code)


# Explicit upstream stdlib names, not a recursive copy or discovered *.py glob.
MODULES = '''__future__ _collections_abc _compat_pickle _compression _pydatetime
_pydecimal _pyio _pylong _strptime _threading_local _weakrefset abc argparse ast
base64 bisect bz2 calendar codecs contextlib contextvars copy copyreg csv
dataclasses datetime decimal difflib dis enum fnmatch fractions functools
genericpath getopt gettext glob gzip hashlib heapq hmac inspect io ipaddress
keyword linecache locale lzma ntpath numbers opcode operator os pathlib pickle
pkgutil platform pprint queue quopri random reprlib resource runpy secrets
selectors shutil signal socket stat statistics string struct subprocess tarfile
tempfile textwrap threading token tokenize traceback types typing uuid warnings
weakref zipimport'''.split()
PACKAGES = {
    'collections': '__init__ abc',
    'concurrent': '__init__ futures/__init__ futures/_base futures/process futures/thread',
    'ctypes': '__init__ _endian util',
    'encodings': '__init__ aliases ascii latin_1 utf_8',
    'importlib': '__init__ _abc machinery util',
    'json': '__init__ decoder encoder scanner',
    'logging': '__init__',
    'multiprocessing': '''__init__ connection context forkserver heap managers pool
        popen_fork popen_forkserver popen_spawn_posix popen_spawn_win32 process
        queues reduction resource_sharer resource_tracker shared_memory sharedctypes
        spawn synchronize util dummy/__init__ dummy/connection''',
    're': '__init__ _casefix _compiler _constants _parser',
    'sqlite3': '__init__ dbapi2 dump',
    'urllib': '__init__ parse',
}
EXTENSIONS = '''_asyncio _bisect _blake2 _bz2 _contextvars _ctypes _datetime
_decimal _hashlib _heapq _json _lzma _md5 _multiprocessing _opcode _pickle
_posixshmem _posixsubprocess _random _sha1 _sha2 _sha3 _sha512 _socket _sqlite3
_ssl _struct _typing _uuid _csv _queue array binascii fcntl math mmap resource select
unicodedata zlib'''.split()
MAX_FILES, MAX_BYTES, MAX_FILE = 512, 128*1024**2, 64*1024**2


def _read(path, roots, *, owner=0):
    path = Path(path)
    resolved = path.resolve(strict=True)
    require(any(resolved == root or root in resolved.parents for root in roots),
            'canary_runtime_link_escape')
    require(stat.S_ISREG(resolved.lstat().st_mode),'canary_runtime_regular_trusted_file')
    # Only library SONAME/loader aliases may resolve within the trusted roots.
    descriptor = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        owners=(owner,) if type(owner) is int else owner
        require(stat.S_ISREG(info.st_mode) and info.st_uid in owners
            and not stat.S_IMODE(info.st_mode)&0o022 and 0 <= info.st_size <= MAX_FILE,
            'canary_runtime_regular_trusted_file')
        with os.fdopen(descriptor,'rb',closefd=False) as stream:data=stream.read(MAX_FILE+1)
        after=os.fstat(descriptor)
        identity=lambda row:(row.st_dev,row.st_ino,row.st_mode,row.st_uid,row.st_gid,
                            row.st_size,row.st_mtime_ns,row.st_ctime_ns)
        require(len(data)==info.st_size and identity(info)==identity(after),'canary_runtime_file_changed')
        return data
    finally:os.close(descriptor)


def _elf(data):
    """Bounded ELF64 LE PT_INTERP/DT_NEEDED reader; never executes ldd/readelf."""
    require(len(data)>=64 and data[:7]==b'\x7fELF\x02\x01\x01','canary_runtime_elf')
    machine=62 if platform.machine()=='x86_64' else 183
    require(struct.unpack_from('<H',data,18)[0]==machine,'canary_runtime_elf_arch')
    offset=struct.unpack_from('<Q',data,32)[0]
    size,count=struct.unpack_from('<HH',data,54)
    require(size==56 and 0<count<=128 and offset+size*count<=len(data),'canary_runtime_elf_headers')
    segments=[struct.unpack_from('<IIQQQQQQ',data,offset+index*size) for index in range(count)]
    interpreter=None;dynamic=[]
    for kind,flags,start,address,physical,length,memory,alignment in segments:
        require(start+length<=len(data),'canary_runtime_elf_segment')
        if kind==3:
            require(interpreter is None and 1<length<=256,'canary_runtime_elf_interpreter')
            raw=data[start:start+length]
            require(raw[-1:]==b'\0' and b'\0' not in raw[:-1],'canary_runtime_elf_interpreter')
            interpreter=raw[:-1].decode('ascii')
        if kind==2:
            require(length%16==0 and length//16<=4096,'canary_runtime_elf_dynamic')
            for entry in range(start,start+length,16):
                tag,value=struct.unpack_from('<QQ',data,entry)
                if tag==0:break
                dynamic.append((tag,value))
    strings=[value for tag,value in dynamic if tag==5]
    sizes=[value for tag,value in dynamic if tag==10]
    needs=[value for tag,value in dynamic if tag==1]
    require(len(needs)<=64,'canary_runtime_elf_dependencies')
    if not needs:return interpreter,[]
    require(len(strings)==len(sizes)==1 and 0<sizes[0]<=1024**2,'canary_runtime_elf_strings')
    loads=sorted((address,address+length,start-address) for kind,flags,start,address,physical,
                  length,memory,alignment in segments if kind==1)
    offsets=[strings[0]+delta for start,end,delta in loads if start<=strings[0]<end]
    require(len(offsets)==1,'canary_runtime_elf_strings')
    # Linkers may split one contiguous string table across adjoining LOADs.
    cursor=strings[0];finish=cursor+sizes[0];delta=offsets[0]-cursor
    for start,end,mapping in loads:
        if start<=cursor<end and mapping==delta:cursor=min(end,finish)
    require(cursor==finish and offsets[0]+sizes[0]<=len(data),'canary_runtime_elf_strings')
    table=data[offsets[0]:offsets[0]+sizes[0]];names=[]
    for value in needs:
        require(value<len(table),'canary_runtime_elf_dependency')
        end=table.find(b'\0',value)
        require(end>=0,'canary_runtime_elf_dependency')
        name=table[value:end].decode('ascii')
        require(re.fullmatch(r'(?:lib|ld-)[A-Za-z0-9_.+-]{1,96}\.so(?:\.[A-Za-z0-9_.+-]+)?',name),
                'canary_runtime_elf_dependency')
        names.append(name)
    return interpreter,names


def build(scope, source):
    """Build the only supported canary image below its newly admitted Scratch."""
    require(sys.version_info[:3]==(3,12,14),'canary_runtime_python_version')
    require(platform.machine() in ('x86_64','aarch64'),'canary_runtime_arch')
    scope=Path(scope);root=scope/'runtime'
    require(not root.exists(),'canary_runtime_already_used')
    root.mkdir(mode=0o700)
    prefix=Path(sys.base_prefix).resolve(strict=True)
    stdlib=prefix/'lib/python3.12'
    require(stdlib.is_dir() and not stdlib.is_symlink(),'canary_runtime_stdlib')
    machine='x86_64-linux-gnu' if platform.machine()=='x86_64' else 'aarch64-linux-gnu'
    library_roots=tuple(dict.fromkeys(path.resolve(strict=True) for path in
        (prefix/'lib',Path('/lib')/machine,Path('/usr/lib')/machine,Path('/lib64'),
         Path('/usr/lib64'),Path('/lib'),Path('/usr/lib')) if path.is_dir()))
    # A source/runtime installation under a real secret/control root is refused.
    for path in (prefix,*library_roots):
        require(path!=Path('/') and not any(path==Path(denied) or Path(denied) in path.parents
            for denied in ('/srv','/etc','/home','/root','/var/lib','/workspace')),
            'canary_runtime_root_refused')
    records=[];total=0;dependencies=[]
    def copy(data,destination,*,executable=False):
        nonlocal total
        total+=len(data)
        require(len(records)<MAX_FILES and total<=MAX_BYTES,'canary_runtime_size_bound')
        target=root/destination
        require(not target.exists() and '..' not in Path(destination).parts,'canary_runtime_destination')
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o500 if executable else 0o400)
        with os.fdopen(descriptor,'wb') as stream:stream.write(data)
        digest=hashlib.sha256(data).hexdigest()
        require(hashlib.sha256(target.read_bytes()).hexdigest()==digest,'canary_runtime_copy_changed')
        records.append(dict(path=str(destination),bytes=len(data),sha256=digest))
    executable=Path(sys.executable).resolve(strict=True)
    copy(_read(executable,(prefix,)), 'bin/python3.12', executable=True)
    dependencies.append(_elf(_read(executable,(prefix,))))
    names=[name+'.py' for name in MODULES]
    names.extend(package+'/'+name+'.py' for package,entries in PACKAGES.items() for name in entries.split())
    for name in names:
        path=stdlib/name
        if not path.exists():
            require(name[:-3] in sys.builtin_module_names,'canary_runtime_stdlib_missing')
            continue
        require(path.resolve()==path,'canary_runtime_source_link')
        copy(_read(path,(stdlib,)),'lib/python3.12/'+name)
    suffix=sysconfig.get_config_var('EXT_SUFFIX')
    require(type(suffix) is str and re.fullmatch(r'\.cpython-312-[A-Za-z0-9_-]+\.so',suffix),
            'canary_runtime_extension_abi')
    # getpath needs this landmark even when all selected extensions are built in.
    (root/'lib/python3.12/lib-dynload').mkdir(mode=0o700,parents=True,exist_ok=True)
    for name in EXTENSIONS:
        path=stdlib/'lib-dynload'/(name+suffix)
        if not path.exists():
            require(name in sys.builtin_module_names or name in ('_asyncio','_sha512'),
                    'canary_runtime_extension_missing')
            continue
        require(path.resolve()==path,'canary_runtime_source_link')
        data=_read(path,(stdlib,));copy(data,'lib/python3.12/lib-dynload/'+path.name)
        dependencies.append(_elf(data))
    pending=[];loader=None;seen=set()
    for interpreter,needed in dependencies:
        if interpreter:
            require(loader in (None,interpreter),'canary_runtime_multiple_loaders')
            loader=interpreter
        pending.extend(needed)
    require(loader in ('/lib64/ld-linux-x86-64.so.2','/lib/ld-linux-aarch64.so.1'),
            'canary_runtime_loader')
    data=_read(loader,library_roots)
    copy(data,'loader',executable=True)
    pending.extend(_elf(data)[1])
    while pending:
        name=pending.pop()
        if name in seen:continue
        seen.add(name)
        candidates=[path/name for path in library_roots if (path/name).exists()]
        require(candidates,'canary_runtime_library_missing')
        data=_read(candidates[0],library_roots)
        copy(data,'lib/'+name)
        interpreter,needed=_elf(data)
        require(interpreter in (None,loader),'canary_runtime_multiple_loaders')
        pending.extend(needed)
    source=Path(source)
    require(source.name=='namespace_canary.py' and source.resolve()==source,
            'canary_runtime_canary_source')
    data=_read(source,(source.parent,),owner=(0,os.geteuid()))
    require(len(data)<=65536,'canary_runtime_canary_bound')
    copy(data,'probe.py')
    return dict(root=root,loader=loader,files=records,bytes=total,
                manifest_sha256=hashlib.sha256(json.dumps(records,sort_keys=True,
                    separators=(',',':')).encode()).hexdigest())
