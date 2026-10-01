"""Bind actual worker/crash children and account for every provider attempt."""
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import urllib.request
from unittest.mock import patch

from certification.stage_e_native_v2.binding import verify_assembly
from certification.stage_e_native_v2.contract import canonical


class Guard:
    def __init__(self, declaration, manifest, source, external):
        self.declaration = declaration
        self.manifest = manifest
        self.source = source
        self.external = external
        self.children = {}
        self.attempts = []
        self.active_test = None
        self.listeners = set()
        self.loopback_connections = []
        self.child_started = False
        self.child_finished = False
        self.bootstrap = str(source / 'certification/stage_e_integration/bootstrap.py')
        self.child_directory = Path(declaration['output']) / 'children'
        self.child_directory.mkdir(exist_ok=True)

    def verify(self):
        verify_assembly(self.declaration['assembly'], self.declaration['assembly_digest'])

    def origins(self):
        rows = []
        for name, module in sorted(sys.modules.items()):
            raw = getattr(module, '__file__', None)
            if not raw:
                continue
            path = Path(raw).resolve()
            if path.is_relative_to(self.source):
                expected = self.manifest['files'].get(path.relative_to(self.source).as_posix(), {}).get('sha256')
                category = 'assembled'
            else:
                expected = self.external.get(str(path))
                category = 'approved_tooling_or_environment'
            if expected is None or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('integration_runtime_origin:' + name + ':' + str(path))
            rows.append(dict(module=name, origin=str(path), sha256=expected, category=category))
        if not any(r['origin'] == self.bootstrap for r in rows):
            raise ValueError('integration_entrypoint_origin_missing')
        return rows

    def attempt(self, kind):
        self.attempts.append(kind)
        row = canonical(dict(pid=os.getpid(), kind=kind)) + b'\n'
        with (self.child_directory / (str(os.getpid()) + '.providers.jsonl')).open('ab') as handle:
            handle.write(row)
            handle.flush()
        raise PermissionError('integration_provider_attempt_forbidden:' + kind)

    def child_begin(self, kind):
        if self.child_started:
            return
        self.child_started = True
        os.environ['MM_INTEGRATION_CHILD'] = '1'
        self.verify()
        import importlib.util
        foreign = self.child_directory / (str(os.getpid()) + '.foreign-probe.py')
        foreign.write_text("raise AssertionError('foreign child code executed')\n")
        spec = importlib.util.spec_from_file_location('integration_foreign_probe', foreign)
        try:
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        except PermissionError as exc:
            if 'unapproved_integration_executable_origin' not in str(exc):
                raise
        else:
            raise AssertionError('foreign_child_origin_not_rejected')
        self.child_row = dict(pid=os.getpid(), kind=kind,
            candidate_sha=self.declaration['candidate_sha'], candidate_tree=self.declaration['candidate_tree'],
            assembly_digest=self.declaration['assembly_digest'], assembly_before=self.declaration['assembly_digest'],
            assembly_after=None, origins_before=self.origins(), origins_after=[], provider_attempts=[],
            foreign_dynamic_origin_rejected=True, non_certified=True)
        (self.child_directory / (str(os.getpid()) + '.before.json')).write_bytes(canonical(self.child_row))

    def child_finish(self, exit_code=0):
        if not self.child_started or self.child_finished:
            return
        self.verify()
        self.child_row.update(assembly_after=self.declaration['assembly_digest'], origins_after=self.origins(),
            provider_attempts=list(self.attempts), exit_code=exit_code)
        (self.child_directory / (str(os.getpid()) + '.after.json')).write_bytes(canonical(self.child_row))
        self.child_finished = True

    def register(self, pid, kind, **extras):
        self.children.setdefault(pid, dict(pid=pid, kind=kind)).update(extras)

    @contextmanager
    def controls(self):
        import multiprocessing.process
        import multiprocessing.spawn
        import multiprocessing.util
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_listen = socket.socket.listen
        original_popen = subprocess.Popen
        original_spawn = multiprocessing.util.spawnv_passfds
        original_start = multiprocessing.process.BaseProcess.start
        original_bootstrap = multiprocessing.process.BaseProcess._bootstrap
        original_kill = multiprocessing.process.BaseProcess.kill
        original_exit = os._exit

        loopback_test = 'tests.test_run379_transport_backpressure.TransportBackpressureTests.test_real_protocol_queue_backpressure_drains_without_ping_disconnect'

        def listen(sock, backlog=0):
            result = original_listen(sock, backlog)
            if self.active_test == loopback_test and sock.family in (socket.AF_INET, socket.AF_INET6):
                address = sock.getsockname()
                if address[0] in ('127.0.0.1', '::1'):
                    self.listeners.add((sock.family, address[0], address[1]))
            return result

        def local(sock, address):
            if (self.active_test == loopback_test and isinstance(address, tuple) and
                    (sock.family, address[0], address[1]) in self.listeners):
                self.loopback_connections.append(dict(test=self.active_test, family=int(sock.family),
                    host=address[0], port=address[1], registered_listener=True))
                return True
            return False

        def connect(sock, address):
            if sock.family == socket.AF_UNIX or local(sock, address):
                return original_connect(sock, address)
            return self.attempt('socket.connect')

        def connect_ex(sock, address):
            if sock.family == socket.AF_UNIX or local(sock, address):
                return original_connect_ex(sock, address)
            return self.attempt('socket.connect_ex')

        def command_line(**kwargs):
            return [sys.executable, '-I', '-S', self.bootstrap, '--worker', json.dumps(kwargs, sort_keys=True)]

        def spawn(path, args, passfds):
            args = [os.fsdecode(a) for a in args]
            kind = 'spawn_worker'
            if '-c' in args:
                code = args[args.index('-c') + 1]
                match = re.fullmatch(r'from multiprocessing.resource_tracker import main;main\((\d+)\)', code)
                if not match:
                    raise PermissionError('unbound_multiprocessing_child')
                args = [sys.executable, '-I', '-S', self.bootstrap, '--resource-tracker', match[1]]
                kind = 'resource_tracker'
            if args[:4] != [sys.executable, '-I', '-S', self.bootstrap]:
                raise PermissionError('unbound_worker_bootstrap')
            pid = original_spawn(os.fsencode(sys.executable), [os.fsencode(a) for a in args], passfds)
            self.register(pid, kind)
            return pid

        def process_start(process):
            target = str(process._target)
            result = original_start(process)
            self.register(process.pid, 'multiprocessing', target=target)
            return result

        def process_bootstrap(process, *args, **kwargs):
            self.child_begin('multiprocessing_' + str(process._start_method))
            code = 1
            try:
                code = original_bootstrap(process, *args, **kwargs)
                return code
            finally:
                self.child_finish(code)

        def process_kill(process):
            self.register(process.pid, 'multiprocessing', expected_signal=int(signal.SIGKILL))
            return original_kill(process)

        def exit_child(code):
            self.child_finish(code)
            return original_exit(code)

        def popen(args, *positional, **kwargs):
            command = list(args) if isinstance(args, (list, tuple)) else []
            if command and Path(os.fsdecode(command[0])).name == 'git':
                if any(a in command for a in ('clone', 'fetch', 'push', 'pull', 'ls-remote')):
                    raise PermissionError('integration_git_network_not_authorized')
                return original_popen(args, *positional, **kwargs)
            if command == [sys.executable, '-I', '-S', self.bootstrap, '--resource']:
                kwargs['env'] = dict(os.environ)
                process = original_popen(command, *positional, **kwargs)
                self.register(process.pid, 'bounded_resource', expected_exit=0)
                return process
            if (len(command) == 5 and command[:2] == [sys.executable, '-c'] and
                    hashlib.sha256(command[2].encode()).hexdigest() == self.declaration['crash_literal_sha256'] and
                    command[4] in ('before_commit', 'after_commit')):
                command = [sys.executable, '-I', '-S', self.bootstrap, '--crash', *command[3:]]
                kwargs['env'] = dict(os.environ)
                process = original_popen(command, *positional, **kwargs)
                self.register(process.pid, 'crash_before_after_commit', expected_exit=77, stage=command[-1])
                return process
            raise PermissionError('unbound_integration_subprocess')

        def denied(kind):
            return lambda *args, **kwargs: self.attempt(kind)

        with ExitStack() as stack:
            for obj, name, value in (
                (socket.socket, 'connect', connect), (socket.socket, 'connect_ex', connect_ex),
                (socket.socket, 'listen', listen),
                (socket, 'create_connection', denied('socket.create_connection')),
                (socket, 'getaddrinfo', denied('socket.getaddrinfo')),
                (urllib.request, 'urlopen', denied('urllib.request.urlopen')),
                (subprocess, 'Popen', popen),
                (multiprocessing.spawn, 'get_command_line', command_line),
                (multiprocessing.util, 'spawnv_passfds', spawn),
                (multiprocessing.process.BaseProcess, 'start', process_start),
                (multiprocessing.process.BaseProcess, '_bootstrap', process_bootstrap),
                (multiprocessing.process.BaseProcess, 'kill', process_kill),
                (os, '_exit', exit_child)):
                stack.enter_context(patch.object(obj, name, value))
            yield
