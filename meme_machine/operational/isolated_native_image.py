"""Fixed native image contract; authenticated bytes, no original directory binds.

The embedding protected parent must authenticate the detached approval against
its original exact-source/dependency installation evidence. Neither a wheel
RECORD nor this image's checksum authenticates itself. No default authenticator,
arbitrary source root, package selector or child entrypoint is provided.
"""
import base64
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import sysconfig

from . import namespace_runtime as runtime
from . import namespace_canary as boundary

MAX_FILES=2048
MAX_BYTES=256*1024**2
MAX_FILE=64*1024**2
ENTRY='meme_machine/operational/isolated_native_entry.py'
DEPENDENCIES={
    'based58':('0.1.1','14b01d91ac250300ca7f634e5bf70fb2b1b9aaa90cc14357943c7da525a35aff',('based58/',)),
    'grpcio':('1.84.0','b44f0a0fc7bc6677d38cc80bca1a32814ce6c8f200fb8b3c1a61c9d77eaefbf3',('grpc/',)),
    'protobuf':('7.36.2','89f23aa53c24553a2416fd4fd1ec06f74fa42b14b546d8883128813f775bbfd2',('google/protobuf/','google/_upb/')),
    'pysimdjson':('7.0.2','a1de838fc7aa473db24ddacc0b285928bd74d5830755f8471b17c34e78e94840',('simdjson/','csimdjson.abi3.so')),
    'typing_extensions':('4.16.0','481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8',('typing_extensions.py',)),
    'websockets':('17.1','0c863507ada5805517ca6dff1c524dcd42942efe6304dacf06700878398d21a6',('websockets/',)),
}
NATIVE_MODULES='''configparser mimetypes nturl2path shlex socketserver ssl stringprep
unicodedata'''.split()
NATIVE_PACKAGES={
    'encodings':'raw_unicode_escape unicode_escape',
    'asyncio':'''__init__ base_events base_futures base_subprocess base_tasks constants coroutines
        events exceptions format_helpers futures locks log mixins protocols queues runners
        selector_events sslproto staggered streams subprocess taskgroups tasks threads
        timeouts transports trsock unix_events''',
    'email':'''__init__ _encoded_words _header_value_parser _parseaddr _policybase
        base64mime charset contentmanager encoders errors feedparser generator header
        headerregistry iterators message parser policy quoprimime utils''',
    'http':'__init__ client cookiejar cookies',
    'urllib':'error request response robotparser',
    'importlib':'abc readers',
    'importlib/metadata':'__init__ _adapters _collections _functools _itertools _meta _text',
    'importlib/resources':'__init__ _adapters _common _itertools _legacy abc readers simple',
    'zipfile':'__init__ _path/__init__ _path/glob',
}


class Refused(RuntimeError):pass


def require(value,code):
    if not value:raise Refused(code)


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _digest(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None


def _package_file(name,prefixes):
    path=Path(name)
    return (type(name) is str and not path.is_absolute() and '..' not in path.parts
        and '__pycache__' not in path.parts and path.suffix not in ('.pyc','.pyo','.pth')
        and '.dist-info' not in name and (path.suffix in ('.py','.so','.json','.pem','.typed')
            or path.name=='py.typed')
        and any(name.startswith(prefix) if prefix.endswith('/') else name==prefix for prefix in prefixes))


class NativeImageApproval:
    """Detached immutable parent approval; no self-authentication fallback."""
    __slots__=('_encoded',)

    def __init__(self,value,*,authenticate):
        raw=encoded(value)
        require(len(raw)<=512*1024 and callable(authenticate)
            and authenticate(json.loads(raw)) is True,'native_image_authentication_required')
        row=json.loads(raw)
        require(type(row) is dict and set(row)=={'schema','source_commit','source_tree',
            'source_files','requirements_sha256','dependencies'},'native_image_approval_shape')
        require(row['schema']=='isolated-native-image-v1','native_image_approval_schema')
        for field in ('source_commit','source_tree'):
            require(type(row[field]) is str and re.fullmatch('[0-9a-f]{40}',row[field]),
                    'native_image_source_identity')
        require(type(row['source_files']) is dict and 0<len(row['source_files'])<=1024
            and ENTRY in row['source_files'] and all(_source_file(name) and _digest(digest)
                for name,digest in row['source_files'].items()),'native_image_source_manifest')
        require(_digest(row['requirements_sha256']) and type(row['dependencies']) is dict
            and row['dependencies'].keys()==DEPENDENCIES.keys(),'native_image_dependencies')
        total=0
        for name,(version,wheel,prefixes) in DEPENDENCIES.items():
            package=row['dependencies'][name]
            require(type(package) is dict and set(package)=={'version','wheel_sha256','files'}
                and package['version']==version and package['wheel_sha256']==wheel
                and type(package['files']) is dict and 0<len(package['files'])<=512,
                'native_image_dependency_identity')
            for path,digest in package['files'].items():
                require(_package_file(path,prefixes) and _digest(digest),'native_image_dependency_file')
                total+=1
        require(total<=1024,'native_image_dependency_bound')
        object.__setattr__(self,'_encoded',raw)

    def __setattr__(self,*args):raise AttributeError('immutable_native_image_approval')

    def value(self):return json.loads(self._encoded)


def _git(root,*args):
    return subprocess.check_output(['/usr/bin/git','--no-optional-locks','--no-pager',
        '-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null',
        '-c','protocol.allow=never','-c','safe.directory='+str(root),'-C',str(root),*args],
        stdin=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15,
        env={'PATH':'/usr/bin:/bin','LANG':'C','GIT_CONFIG_GLOBAL':'/dev/null',
             'GIT_CONFIG_NOSYSTEM':'1','GIT_OPTIONAL_LOCKS':'0','GIT_NO_LAZY_FETCH':'1'})


def _source_file(name):
    path=Path(name)
    return (not path.is_absolute() and '..' not in path.parts and
        ((name.startswith('meme_machine/') and path.suffix in ('.py','.json','.proto'))
         or (name.startswith('engineering/solana_capacity/') and path.suffix=='.py')
         or name in ('engineering/__init__.py','operational/forward-survivor/NEXT_PROOF.json')))


def source_objects(approval):
    require(type(approval) is NativeImageApproval,'native_image_approval_required')
    value=approval.value();root=Path(__file__).resolve().parents[2]
    require(_git(root,'rev-parse','HEAD').decode().strip()==value['source_commit']
        and _git(root,'rev-parse','HEAD^{tree}').decode().strip()==value['source_tree'],
        'native_image_source_mismatch')
    require(not _git(root,'status','--porcelain','--untracked-files=normal').strip(),
            'native_image_source_dirty')
    requirements=_git(root,'show',value['source_commit']+':requirements.txt')
    require(hashlib.sha256(requirements).hexdigest()==value['requirements_sha256'],
            'native_image_requirements_mismatch')
    rows=_git(root,'ls-tree','-r','-z',value['source_tree'],'--','meme_machine',
        'engineering/solana_capacity','engineering/__init__.py',
        'operational/forward-survivor/NEXT_PROOF.json').split(b'\0')
    selected=[]
    for raw in rows:
        if not raw:continue
        header,name=raw.split(b'\t',1);name=name.decode('utf8')
        mode,kind,blob=header.decode('ascii').split()
        if not _source_file(name):continue
        require(mode in ('100644','100755') and kind=='blob','native_image_source_not_regular')
        require(len(selected)<1024,'native_image_source_bound')
        selected.append((name,blob))
    require(ENTRY in {name for name,blob in selected},'native_image_fixed_entry_missing')
    require({name for name,blob in selected}==value['source_files'].keys(),
            'native_image_source_manifest_mismatch')
    return root,requirements,selected


class _ImageWriter:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(mode=0o700)
        self.files=[];self.bytes=0

    def copy(self,data,path,*,executable=False):
        path=Path(path)
        require(type(data) is bytes and len(data)<=MAX_FILE and not path.is_absolute()
            and '..' not in path.parts,'native_image_copy')
        require(len(self.files)<MAX_FILES and self.bytes+len(data)<=MAX_BYTES,'native_image_size_bound')
        target=self.root/path
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o500 if executable else 0o400)
        with os.fdopen(descriptor,'wb') as output:output.write(data)
        digest=hashlib.sha256(data).hexdigest()
        require(hashlib.sha256(target.read_bytes()).hexdigest()==digest,'native_image_copy_changed')
        self.files.append(dict(path=str(path),bytes=len(data),sha256=digest))
        self.bytes+=len(data)


def _runtime(writer):
    require(sys.version_info[:3]==(3,12,14) and platform.machine()=='x86_64',
            'native_image_runtime_identity')
    prefix=Path(sys.base_prefix).resolve(strict=True);stdlib=prefix/'lib/python3.12'
    roots=tuple(dict.fromkeys(path.resolve(strict=True) for path in (prefix/'lib',
        Path('/lib/x86_64-linux-gnu'),Path('/usr/lib/x86_64-linux-gnu'),Path('/lib64'),
        Path('/usr/lib64'),Path('/lib'),Path('/usr/lib')) if path.is_dir()))
    for path in (prefix,*roots):
        require(path!=Path('/') and not any(path==Path(denied) or Path(denied) in path.parents
            for denied in ('/srv','/etc','/home','/root','/var/lib','/workspace')),
            'native_image_runtime_root')
    dependencies=[]
    def elf(data,path,executable=False):
        writer.copy(data,'runtime/'+path,executable=executable)
        dependencies.append(runtime._elf(data))
    elf(runtime._read(Path(sys.executable).resolve(strict=True),(prefix,)),'bin/python3.12',True)
    names=dict(runtime._sources(stdlib))
    for module in NATIVE_MODULES:
        path=stdlib/(module+'.py')
        if path.exists():names[module+'.py']=path
        else:require(module in sys.builtin_module_names or module in runtime.EXTENSIONS,
                     'native_image_stdlib_missing')
    for package,entries in NATIVE_PACKAGES.items():
        for name in entries.split():names[package+'/'+name+'.py']=stdlib/package/(name+'.py')
    for name,path in names.items():
        require(path.resolve()==path,'native_image_stdlib_link')
        writer.copy(runtime._read(path,(stdlib,)),'runtime/lib/python3.12/'+name)
    suffix=sysconfig.get_config_var('EXT_SUFFIX')
    require(type(suffix) is str and re.fullmatch(r'\.cpython-312-[A-Za-z0-9_-]+\.so',suffix),
            'native_image_extension_abi')
    (writer.root/'runtime/lib/python3.12/lib-dynload').mkdir(mode=0o700,parents=True,exist_ok=True)
    for name in runtime.EXTENSIONS:
        path=stdlib/'lib-dynload'/(name+suffix)
        if not path.exists():
            require(name in sys.builtin_module_names or name in ('_asyncio','_sha512'),
                    'native_image_extension_missing')
            continue
        require(path.resolve()==path,'native_image_extension_link')
        elf(runtime._read(path,(stdlib,)),'lib/python3.12/lib-dynload/'+path.name)
    return roots,dependencies,elf


def _packages(approval,writer,dependencies):
    """Compare installed RECORD and bytes to independently authenticated hashes."""
    value=approval.value()
    for name,(_,_,prefixes) in DEPENDENCIES.items():
        record=value['dependencies'][name]
        package=importlib.metadata.distribution(name)
        require(package.version==record['version'],'native_image_installed_version')
        base=Path(package.locate_file('')).resolve(strict=True)
        require(base.name=='site-packages','native_image_installed_root')
        indexed={str(path):path for path in package.files or () if _package_file(str(path),prefixes)}
        require(indexed.keys()==record['files'].keys(),'native_image_installed_manifest')
        for name,path in indexed.items():
            checksum=path.hash
            require(checksum is not None and checksum.mode=='sha256','native_image_record_hash')
            raw_hash=base64.urlsafe_b64decode(checksum.value+'='*((-len(checksum.value))%4))
            require(raw_hash.hex()==record['files'][name],'native_image_record_digest')
            target=base/path
            require(target.resolve()==target,'native_image_package_link')
            # Actual approval authenticates exact bytes even in an owned offline
            # fixture; live parent must use its original root installation proof.
            data=runtime._read(target,(base,),owner=(0,os.geteuid()))
            require(hashlib.sha256(data).hexdigest()==record['files'][name],
                    'native_image_package_digest')
            writer.copy(data,'deps/'+name)
            if target.suffix=='.so':dependencies.append(runtime._elf(data))


def build(scope,approval,*,profile=None):
    """Stage only the fixed authenticated application/dependency/native image."""
    if profile is not None:
        from .isolated_native_layout import PROFILE
        require(type(profile) is str and profile==PROFILE,'native_image_profile')
    scope=boundary._scratch(scope,os.getpid())
    root,requirements,objects=source_objects(approval)
    writer=_ImageWriter(scope/'native-image')
    roots,dependencies,_=_runtime(writer)
    if profile is not None:
        from meme_machine.runtime.isolated_native_spawn import SHIM_PATH,trampoline
        writer.copy(trampoline(writer.root/'runtime/bin/python3.12'),SHIM_PATH,executable=True)
    source_files=approval.value()['source_files']
    for name,blob in objects:
        size=_git(root,'cat-file','-s',blob).strip()
        require(size.isdigit() and int(size)<=MAX_FILE,'native_image_source_file_bound')
        data=_git(root,'cat-file','blob',blob)
        require(len(data)==int(size) and hashlib.sha256(data).hexdigest()==source_files[name],
                'native_image_source_file_digest')
        writer.copy(data,'app/'+name)
    writer.copy(requirements,'app/requirements.txt')
    _packages(approval,writer,dependencies)
    pending=[];loader=None;seen=set()
    for interpreter,needed in dependencies:
        if interpreter:
            require(loader in (None,interpreter),'native_image_multiple_loaders');loader=interpreter
        pending.extend(needed)
    require(loader=='/lib64/ld-linux-x86-64.so.2','native_image_loader')
    data=runtime._read(loader,roots);writer.copy(data,'loader',executable=True)
    pending.extend(runtime._elf(data)[1])
    while pending:
        name=pending.pop()
        if name in seen:continue
        seen.add(name)
        candidates=[path/name for path in roots if (path/name).exists()]
        require(candidates,'native_image_library_missing')
        data=runtime._read(candidates[0],roots);writer.copy(data,'runtime/lib/'+name)
        interpreter,needed=runtime._elf(data)
        require(interpreter in (None,loader),'native_image_multiple_loaders')
        pending.extend(needed)
    manifest=dict(schema='isolated-native-copied-image-v1',source_commit=approval.value()['source_commit'],
        source_tree=approval.value()['source_tree'],requirements_sha256=approval.value()['requirements_sha256'],
        files=list(writer.files),bytes=writer.bytes,financial_authority=False,provider_calls=0,
        actual_service_restrictions_verified=False)
    writer.copy(encoded(manifest),'manifest.json')
    return dict(root=writer.root,manifest=manifest,manifest_sha256=hashlib.sha256(encoded(manifest)).hexdigest())
