import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational import managed_capacity_evidence as evidence


class ManagedEvidence(unittest.TestCase):
    def test_failure_site_preserves_real_code_without_exception_data(self):
        from meme_machine.operational.managed_native_pump import FinalizedHeadObserver
        class Offline:
            def call_delivered(self, *args, **kwargs):
                return 'secret-provider-credential', {}
        try:
            FinalizedHeadObserver().sample(Offline())
        except ValueError as error:
            site = evidence.failure_site(error)
        self.assertEqual(site['module'], 'meme_machine.operational.managed_native_pump')
        self.assertEqual(site['function'], 'sample')
        self.assertGreater(site['line'], 0)
        self.assertNotIn('secret-provider-credential', json.dumps(site))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.generation = 'a' * 32

    def capture(self):
        stream = evidence.Evidence(self.root, self.generation)
        for n in range(3):
            stream.append('sample', dict(pump=n, pons=n * 2))
        stream.close()
        return stream

    def test_sealed_chain_verified_but_cannot_self_authenticate(self):
        self.capture()
        row = evidence.verify(self.root, self.generation)
        self.assertEqual(row['rows'], 3)
        self.assertTrue(row['integrity_verified'])
        self.assertFalse(row['provenance_authenticated'])
        with self.assertRaisesRegex(ValueError, 'capacity_manifest_identity'):
            evidence.verify(self.root, 'b' * 32)

    def test_modified_native_counter_refused(self):
        self.capture()
        part = self.root / 'evidence-0000.jsonl'
        part.write_bytes(part.read_bytes().replace(b'"pump":1', b'"pump":9'))
        with self.assertRaisesRegex(ValueError, 'capacity_row_integrity'):
            evidence.verify(self.root, self.generation)

    def test_missing_and_unlisted_parts_refused(self):
        self.capture()
        part = self.root / 'evidence-0000.jsonl'
        extra = self.root / 'evidence-0001.jsonl'
        extra.write_bytes(part.read_bytes())
        with self.assertRaisesRegex(ValueError, 'capacity_unlisted_part'):
            evidence.verify(self.root, self.generation)
        part.unlink()
        with self.assertRaises(FileNotFoundError):
            evidence.verify(self.root, self.generation)

    def test_no_manifest_means_interrupted_never_sealed(self):
        stream = evidence.Evidence(self.root, self.generation)
        stream.append('sample', dict(pump=1, pons=1))
        try:
            with self.assertRaises(FileNotFoundError):
                evidence.verify(self.root, self.generation)
        finally:
            stream.close()

    def test_short_writes_fully_written(self):
        original = os.write
        def short(fd, raw):
            return original(fd, raw[:7])
        with patch.object(evidence.os, 'write', short):
            self.capture()
        self.assertEqual(evidence.verify(self.root, self.generation)['rows'], 3)

    def test_rollover_global_budget_and_no_silent_truncation(self):
        with patch.object(evidence, 'MAX_PART', 750):
            self.capture()
            self.assertGreater(len(list(self.root.glob('*.jsonl'))), 1)
            self.assertTrue(evidence.verify(self.root, self.generation)['integrity_verified'])
        other = self.root / 'bound'
        other.mkdir(mode=0o700)
        with patch.object(evidence, 'MAX_TOTAL', 8):
            stream = evidence.Evidence(other, self.generation)
            with self.assertRaisesRegex(ValueError, 'capacity_evidence_bound'):
                stream.append('sample', {'counter': 1})
            stream.close()
            self.assertEqual(stream.sequence, 0)

    def test_symlink_private_root_and_invalid_generation_refused(self):
        for generation in ('', 'x' * 32, '1' * 31):
            with self.assertRaisesRegex(ValueError, 'capacity_generation_identity'):
                evidence.Evidence(self.root, generation)
        link = self.root / 'alias'
        link.symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, 'capacity_directory_link'):
            evidence.private_directory(link)
        self.root.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'capacity_private_directory_required'):
            evidence.private_directory(self.root)

    def test_host_sample_contains_counters_without_process_credentials(self):
        row = evidence.host_sample((os.getpid(),))
        self.assertGreater(row['memory_bytes']['MemTotal'], 0)
        self.assertGreaterEqual(row['processes'][str(os.getpid())]['rss_bytes'], 0)
        raw = json.dumps(row)
        self.assertNotIn('environ', raw)
        self.assertNotIn('cmdline', raw)

    def test_process_io_permission_denial_preserves_readable_counters(self):
        original = Path.read_text
        target = Path('/proc') / str(os.getpid()) / 'io'
        def denied(path, *args, **kwargs):
            if path == target:
                raise PermissionError('secret-counter-error-never-output')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', denied):
            sample = evidence.host_sample((os.getpid(),))
        row = sample['processes'][str(os.getpid())]
        self.assertGreater(row['start_ticks'], 0)
        self.assertGreaterEqual(row['rss_bytes'], 0)
        self.assertIsNone(row['io'])
        self.assertFalse(row['io_available'])
        self.assertEqual(row['io_reason_code'], 'permission_denied')
        self.assertNotIn('exited', row)
        self.assertGreater(sample['memory_bytes']['MemTotal'], 0)
        self.assertNotIn('secret-counter-error', json.dumps(sample))

    def test_process_stat_permission_denial_is_unavailable_not_exited(self):
        original = Path.read_text
        target = Path('/proc') / str(os.getpid()) / 'stat'
        def denied(path, *args, **kwargs):
            if path == target:
                raise PermissionError('secret-counter-error-never-output')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', denied):
            sample = evidence.host_sample((os.getpid(),))
        self.assertEqual(sample['processes'][str(os.getpid())],
            dict(available=False, reason_code='process_stat_permission_denied'))
        self.assertGreater(sample['memory_bytes']['MemTotal'], 0)
        self.assertNotIn('secret-counter-error', json.dumps(sample))

    def test_global_permission_denial_and_unexpected_process_io_errors_remain_fatal(self):
        original = Path.read_text
        for target, error in ((Path('/proc/stat'), PermissionError('global-denial')),
                (Path('/proc') / str(os.getpid()) / 'io', OSError(5, 'io-failure'))):
            def denied(path, *args, **kwargs):
                if path == target:
                    raise error
                return original(path, *args, **kwargs)
            with self.subTest(target=str(target)), patch.object(Path, 'read_text', denied):
                with self.assertRaises(type(error)):
                    evidence.host_sample((os.getpid(),))

    @unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'WNOWAIT'),
                         'requires Linux same-UID zombie proc counters')
    def test_actual_unprivileged_unreaped_child_io_is_explicitly_unavailable(self):
        # Execute the exact stdlib-only production module bytes through stdin.
        # This also works when the repository itself is private to root: only
        # this disposable fixture drops UID, with no source permission changes.
        program = '''
import json, os, pathlib, subprocess, sys
module = {'__name__': 'offline_managed_capacity_evidence'}
exec(compile(sys.stdin.buffer.read(), '<managed-capacity-evidence>', 'exec'), module)
child = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'raise SystemExit(17)'],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)
    proc = pathlib.Path('/proc') / str(child.pid)
    state = (proc / 'stat').read_text().rpartition(')')[2].split()[0]
    denied = False
    try:
        (proc / 'io').read_text()
    except PermissionError:
        denied = True
    sample = module['host_sample']((child.pid,))
    print(json.dumps(dict(uid=os.geteuid(), state=state, io_denied=denied,
        returncode_before_poll=child.returncode, process=sample['processes'][str(child.pid)])))
finally:
    child.wait(timeout=5)
'''
        identity = dict(user=65534, group=65534, extra_groups=()) if os.geteuid() == 0 else {}
        result = subprocess.run([sys.executable, '-I', '-B', '-c', program],
            input=Path(evidence.__file__).read_bytes(), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd='/', timeout=10, check=False,
            env=dict(PATH='/usr/bin:/bin', LANG='C'), **identity)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        row = json.loads(result.stdout)
        self.assertNotEqual(row['uid'], 0)
        self.assertEqual(row['state'], 'Z')
        self.assertTrue(row['io_denied'])
        self.assertIsNone(row['returncode_before_poll'])
        self.assertGreater(row['process']['start_ticks'], 0)
        self.assertIsNone(row['process']['io'])
        self.assertFalse(row['process']['io_available'])
        self.assertEqual(row['process']['io_reason_code'], 'permission_denied')
        self.assertNotIn('exited', row['process'])
