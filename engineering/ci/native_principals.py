"""Fixed hosted-CI runtime ownership installation; never an AWS control path.

Only the setup-python 3.12.14 core selected by the original copied-image
builders is sealed. No recursive ownership operation or arbitrary path selector
is exposed. Content identity is checked across each metadata-only installation.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import sys
import sysconfig

PREFIX = Path('/opt/hostedtoolcache/Python/3.12.14/x64')
MAX_FILES = 512
MAX_BYTES = 128 * 1024**2
MAX_FILE = 64 * 1024**2
BLOCK = 128 * 1024


class Refused(RuntimeError):
    def __init__(self, code, *, facts=None):
        super().__init__(code)
        self.facts = facts


def require(value, code, *, facts=None):
    if not value:
        raise Refused(code, facts=facts)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def content_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink)


def _stat_fields(info):
    return dict(device=info.st_dev, inode=info.st_ino, uid=info.st_uid,
                gid=info.st_gid, mode=stat.S_IMODE(info.st_mode), links=info.st_nlink,
                size=info.st_size)


def failure_record(error):
    """Fixed numeric failure projection; never an exception message or path."""
    record = dict(schema='fixed-hosted-ci-runtime-failure-v1', status='FAILED',
                  complete=False, error_class='Refused' if isinstance(error, Refused) else 'OSError')
    codes = {'ci_runtime_directory_owner', 'ci_runtime_directory_search',
             'ci_runtime_directory_trust', 'ci_runtime_directory_changed',
             'ci_runtime_path_changed', 'ci_runtime_file_trust', 'ci_runtime_shared_file',
             'ci_runtime_regular_bound', 'ci_runtime_byte_bound', 'ci_runtime_file_bound',
             'ci_runtime_content_changed', 'ci_runtime_metadata_only', 'ci_runtime_principals',
             'ci_runtime_hosted_only', 'ci_runtime_fixed_selection', 'ci_runtime_executable',
             'ci_runtime_fixed_loader', 'ci_runtime_executable_mode', 'ci_runtime_stdlib_missing',
             'ci_runtime_extension_abi', 'ci_runtime_extension_missing',
             'ci_runtime_library_missing', 'ci_runtime_library_escape', 'ci_runtime_path'}
    code = error.args[0] if isinstance(error, Refused) and error.args else None
    record['code'] = code if type(code) is str and code in codes else None
    number = getattr(error, 'errno', None)
    if type(number) is int and 0 < number < 4096:
        record['errno'] = number
    facts = getattr(error, 'facts', None)
    if type(facts) is dict:
        roles = {'root_anchor', 'opt', 'toolcache', 'python_cache', 'python_version',
                 'python_prefix', 'selected_runtime_parent'}
        role = facts.get('directory_role')
        if type(role) is str and role in roles:
            record['directory_role'] = role
        for phase in ('source_stat', 'destination_stat'):
            value = facts.get(phase)
            if type(value) is dict:
                clean = {key:value[key] for key in ('device','inode','uid','gid','mode','links','size')
                         if type(value.get(key)) is int and 0 <= value[key] <= 2**64-1}
                if clean:
                    record[phase] = clean
    return record


def _open(path, *, directory=False):
    """Open every component without following a directory or final symlink."""
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'ci_runtime_path')
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for index, part in enumerate(path.parts[1:]):
            last = index == len(path.parts) - 2
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            if not last or directory:
                flags |= os.O_DIRECTORY
            following = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _digest(descriptor, expected):
    require(stat.S_ISREG(expected.st_mode) and 0 <= expected.st_size <= MAX_FILE,
            'ci_runtime_regular_bound', facts=dict(source_stat=_stat_fields(expected)))
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    remaining = expected.st_size
    while remaining:
        data = os.read(descriptor, min(BLOCK, remaining))
        require(data and len(data) <= remaining, 'ci_runtime_content_changed')
        digest.update(data)
        remaining -= len(data)
    require(not os.read(descriptor, 1) and identity(os.fstat(descriptor)) == identity(expected),
            'ci_runtime_content_changed')
    return digest.hexdigest()


def _same_path(path, descriptor, *, directory=False):
    other = _open(path, directory=directory)
    try:
        require(identity(os.fstat(other)) == identity(os.fstat(descriptor)),
                'ci_runtime_path_changed')
    finally:
        os.close(other)


class _Installation:
    """Private fixtureable engine; the public installer fixes its path/owners."""
    def __init__(self, prefix, runner_uid, runner_gid, *, target_uid=0, target_gid=0):
        self.prefix = Path(prefix)
        self.owners = (0, runner_uid)
        self.runner_gid = runner_gid
        self.target_uid, self.target_gid = target_uid, target_gid
        self.directories = {}
        self.files = {}
        self.total = 0
        self.stack = ExitStack()

    def _directory_facts(self, path, before, after=None):
        roles = {Path('/'):'root_anchor', Path('/opt'):'opt',
                 Path('/opt/hostedtoolcache'):'toolcache',
                 Path('/opt/hostedtoolcache/Python'):'python_cache',
                 PREFIX.parent:'python_version', PREFIX:'python_prefix'}
        return dict(directory_role=roles.get(path, 'selected_runtime_parent'),
                    source_stat=_stat_fields(before),
                    destination_stat=None if after is None else _stat_fields(after))

    def close(self):
        self.stack.close()

    def directory(self, path, *, install):
        path = Path(path)
        if path in self.directories:
            return
        descriptor = _open(path, directory=True)
        self.stack.callback(os.close, descriptor)
        before = os.fstat(descriptor)
        require(stat.S_ISDIR(before.st_mode) and before.st_uid in self.owners,
                'ci_runtime_directory_owner', facts=self._directory_facts(path,before))
        if install:
            # These are fixed cache ancestors or enumerated selected parents,
            # never a recursive tree operation. Preserve read/search bits.
            require(before.st_mode & 0o111 == 0o111, 'ci_runtime_directory_search',
                    facts=self._directory_facts(path,before))
            os.fchown(descriptor, self.target_uid, self.target_gid)
            os.fchmod(descriptor, stat.S_IMODE(before.st_mode) & ~0o022)
        after = os.fstat(descriptor)
        require(after.st_uid == self.target_uid and not after.st_mode & 0o022,
                'ci_runtime_directory_trust', facts=self._directory_facts(path,before,after))
        _same_path(path, descriptor, directory=True)
        self.directories[path] = (descriptor, before, after)

    def selected(self, path):
        path = Path(path)
        require(path.is_absolute() and '..' not in path.parts, 'ci_runtime_path')
        inside = path.is_relative_to(self.prefix)
        if inside:
            for directory in reversed(path.parent.parents):
                if directory == self.prefix or self.prefix in directory.parents:
                    self.directory(directory, install=True)
            self.directory(path.parent, install=True)
        if path in self.files:
            return self.files[path][3]
        require(len(self.files) < MAX_FILES, 'ci_runtime_file_bound')
        descriptor = _open(path)
        self.stack.callback(os.close, descriptor)
        before = os.fstat(descriptor)
        facts=dict(source_stat=_stat_fields(before))
        require(stat.S_ISREG(before.st_mode), 'ci_runtime_regular_bound', facts=facts)
        require(before.st_uid in (self.owners if inside else (0,))
                and not before.st_mode & 0o7022 and before.st_mode & 0o004,
                'ci_runtime_file_trust', facts=facts)
        require(not inside or before.st_nlink == 1, 'ci_runtime_shared_file', facts=facts)
        require(self.total + before.st_size <= MAX_BYTES, 'ci_runtime_byte_bound', facts=facts)
        digest = _digest(descriptor, before)
        if inside:
            os.fchown(descriptor, self.target_uid, self.target_gid)
        after = os.fstat(descriptor)
        require(content_identity(before) == content_identity(after)
                and stat.S_IMODE(before.st_mode) == stat.S_IMODE(after.st_mode)
                and after.st_uid == self.target_uid and not after.st_mode & 0o022,
                'ci_runtime_metadata_only')
        require(_digest(descriptor, after) == digest, 'ci_runtime_content_changed')
        _same_path(path, descriptor)
        self.total += before.st_size
        self.files[path] = (descriptor, before, after, digest)
        return digest

    def read(self, path):
        self.selected(path)
        descriptor, _, after, _ = self.files[Path(path)]
        os.lseek(descriptor, 0, os.SEEK_SET)
        value = bytearray()
        while len(value) < after.st_size:
            chunk = os.read(descriptor, min(BLOCK, after.st_size-len(value)))
            require(chunk, 'ci_runtime_content_changed')
            value.extend(chunk)
            require(len(value) <= after.st_size, 'ci_runtime_content_changed')
        require(identity(os.fstat(descriptor)) == identity(after), 'ci_runtime_content_changed')
        return bytes(value)

    def finish(self):
        rows = []
        for path, (descriptor, before, after, digest) in sorted(self.files.items()):
            require(identity(os.fstat(descriptor)) == identity(after), 'ci_runtime_content_changed')
            require(_digest(descriptor, after) == digest, 'ci_runtime_content_changed')
            _same_path(path, descriptor)
            rows.append(dict(path=str(path), sha256=digest, bytes=after.st_size,
                source_stat=list(identity(before)), destination_stat=list(identity(after))))
        for path, (descriptor, _, after) in self.directories.items():
            require(identity(os.fstat(descriptor)) == identity(after), 'ci_runtime_directory_changed')
            _same_path(path, descriptor, directory=True)
        content = [dict(path=row['path'], bytes=row['bytes'], sha256=row['sha256']) for row in rows]
        return dict(schema='fixed-hosted-ci-runtime-ownership-v1', metadata_only=True,
            python='3.12.14', files=len(rows), bytes=self.total,
            source_content_sha256=hashlib.sha256(encoded(content)).hexdigest(),
            destination_content_sha256=hashlib.sha256(encoded(content)).hexdigest(),
            records=rows, directories=[dict(path=str(path), source_stat=list(identity(before)),
                destination_stat=list(identity(after))) for path, (_, before, after)
                in sorted(self.directories.items())])


def install(python_location, runner_uid, runner_gid):
    require(os.geteuid() == 0 and type(runner_uid) is int and runner_uid > 0
            and type(runner_gid) is int and runner_gid > 0, 'ci_runtime_principals')
    require(os.environ.get('CI') == 'true' and os.environ.get('GITHUB_ACTIONS') == 'true',
            'ci_runtime_hosted_only')
    require(Path(python_location) == PREFIX and Path(sys.base_prefix) == PREFIX
            and sys.version_info[:3] == (3, 12, 14) and platform.machine() == 'x86_64',
            'ci_runtime_fixed_selection')
    from meme_machine.operational import isolated_native_image as image
    from meme_machine.operational import namespace_runtime as runtime
    installer = _Installation(PREFIX, runner_uid, runner_gid)
    try:
        installer.directory(Path('/'), install=False)
        for path in (Path('/opt'), Path('/opt/hostedtoolcache'), Path('/opt/hostedtoolcache/Python'),
                     PREFIX.parent, PREFIX):
            installer.directory(path, install=True)
        stdlib = PREFIX/'lib/python3.12'
        executable = Path(sys.executable).resolve(strict=True)
        require(executable.parent == PREFIX/'bin' and executable.name == 'python3.12',
                'ci_runtime_executable')
        def dependencies(path):
            interpreter, needed = runtime._elf(installer.read(path))
            require(interpreter in (None, '/lib64/ld-linux-x86-64.so.2'),
                    'ci_runtime_fixed_loader')
            return needed
        pending = list(dependencies(executable))
        require(installer.files[executable][2].st_mode & 0o001, 'ci_runtime_executable_mode')
        names = dict(runtime._sources(stdlib))
        for module in image.NATIVE_MODULES:
            path = stdlib/(module+'.py')
            if path.exists(): names[module+'.py'] = path
            else: require(module in sys.builtin_module_names or module in runtime.EXTENSIONS,
                          'ci_runtime_stdlib_missing')
        for package, entries in image.NATIVE_PACKAGES.items():
            for name in entries.split(): names[package+'/'+name+'.py'] = stdlib/package/(name+'.py')
        for path in names.values(): installer.selected(path)
        suffix = sysconfig.get_config_var('EXT_SUFFIX')
        require(type(suffix) is str and suffix == '.cpython-312-x86_64-linux-gnu.so',
                'ci_runtime_extension_abi')
        for name in runtime.EXTENSIONS:
            path = stdlib/'lib-dynload'/(name+suffix)
            if not path.exists():
                require(name in sys.builtin_module_names or name in ('_asyncio', '_sha512'),
                        'ci_runtime_extension_missing')
                continue
            pending.extend(dependencies(path))
        roots = tuple(dict.fromkeys(path.resolve(strict=True) for path in (PREFIX/'lib',
            Path('/lib/x86_64-linux-gnu'), Path('/usr/lib/x86_64-linux-gnu'), Path('/lib64'),
            Path('/usr/lib64'), Path('/lib'), Path('/usr/lib')) if path.is_dir()))
        pending.extend(dependencies(Path('/lib64/ld-linux-x86-64.so.2').resolve(strict=True)))
        seen = set()
        while pending:
            name = pending.pop()
            if name in seen: continue
            seen.add(name)
            candidates = [root/name for root in roots if (root/name).exists()]
            require(candidates, 'ci_runtime_library_missing')
            path = candidates[0].resolve(strict=True)
            require(any(path == root or root in path.parents for root in roots),
                    'ci_runtime_library_escape')
            pending.extend(dependencies(path))
        return installer.finish()
    finally:
        installer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-location', required=True)
    parser.add_argument('--runner-uid', required=True, type=int)
    parser.add_argument('--runner-gid', required=True, type=int)
    args = parser.parse_args()
    try:
        result = install(args.python_location, args.runner_uid, args.runner_gid)
    except (Refused, OSError) as error:
        print(json.dumps(failure_record(error), sort_keys=True), flush=True)
        raise
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
