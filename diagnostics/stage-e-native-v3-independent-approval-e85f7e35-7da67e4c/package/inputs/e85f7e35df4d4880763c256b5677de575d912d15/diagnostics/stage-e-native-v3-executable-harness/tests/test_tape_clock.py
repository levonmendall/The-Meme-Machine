"""Tiny opaque records and mocked clocks only; no material fixture construction."""
import asyncio
import gzip
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'harness'))
from core import MAGIC
from tape import Reader, decompress
from bound_runtime import ProjectedClock
import bound_runtime
from production import TapeWire


class TapeClockTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def opaque_tape(self):
        raw=[b'opaque unit record 0',b'opaque unit record 1']
        physical=MAGIC+b''.join(struct.pack('>Q',len(gzip.compress(r,mtime=0)))+gzip.compress(r,mtime=0) for r in raw)
        decoded=MAGIC+b''.join(struct.pack('>Q',len(r))+r for r in raw)
        path=self.root/'opaque.tape';path.write_bytes(physical);path.chmod(0o444)
        expected=dict(frames=2,encoded_prefix_bytes=len(physical),encoded_prefix_sha256=hashlib.sha256(physical).hexdigest(),
                      decoded_canonical_sha256=hashlib.sha256(decoded).hexdigest())
        return path,expected

    def test_exact_encoded_and_decoded_receipts(self):
        path,expected=self.opaque_tape();reader=Reader(path,expected)
        self.assertEqual(reader.next()[0],b'opaque unit record 0');reader.next()
        self.assertTrue(reader.close(full=True)['valid'])

    def test_incomplete_prefix_fails(self):
        path,expected=self.opaque_tape();reader=Reader(path,expected);reader.next()
        with self.assertRaises(ValueError):reader.close()

    def test_wrong_hash_fails(self):
        path,expected=self.opaque_tape();expected['decoded_canonical_sha256']='0'*64
        reader=Reader(path,expected);reader.next();reader.next()
        with self.assertRaises(ValueError):reader.close()

    def test_extra_trailing_bytes_fails(self):
        path,expected=self.opaque_tape();path.chmod(0o644);path.write_bytes(path.read_bytes()+b'junk');path.chmod(0o444)
        reader=Reader(path,expected);reader.next();reader.next()
        with self.assertRaises(ValueError):reader.close(full=True)

    def test_truncated_record_fails(self):
        path,expected=self.opaque_tape();path.chmod(0o644);path.write_bytes(path.read_bytes()[:-1]);path.chmod(0o444)
        reader=Reader(path,expected);reader.next()
        with self.assertRaises(ValueError):reader.next()
        reader.file.close()

    def test_writable_tape_refused(self):
        path,expected=self.opaque_tape();path.chmod(0o644)
        with self.assertRaises(ValueError):Reader(path,expected)

    def test_concatenated_gzip_and_decompression_bomb_refused(self):
        with self.assertRaises(ValueError):decompress(gzip.compress(b'x')+gzip.compress(b'y'))
        with patch('tape.MAX_RECORD',64):
            with self.assertRaises(ValueError):decompress(gzip.compress(b'x'*65))

    def test_clock_frozen_then_advances_once_and_cannot_reanchor(self):
        path=self.root/'anchor';path.write_bytes(b'\0'*8)
        clock=ProjectedClock(path)
        self.addCleanup(clock.file.close);self.addCleanup(clock.shared.close)
        self.assertEqual(clock.time(),1800000000);self.assertEqual(clock.monotonic(),100)
        with patch('bound_runtime.REAL_NS',side_effect=[1000000000,1250000000,1500000000]):
            self.assertEqual(clock.activate(),1000000000)
            self.assertEqual(clock.time(),1800000000.25)
            self.assertEqual(clock.monotonic(),100.5)
        with self.assertRaises(ValueError):clock.activate()

    def test_preview_source_release_guard_denies_even_opaque_record(self):
        wire=TapeWire(dict(frames=1,prebuilt=(b'opaque unit record',),cadence_us=270000))
        with self.assertRaisesRegex(ValueError,'source_release_not_authorized'):
            asyncio.run(wire.recv())
        self.assertEqual(wire.sent,0)
        self.assertIsNone(wire.first_release)

    def test_subscription_ACK_does_not_anchor_or_release_data(self):
        wire=TapeWire(dict(frames=1,prebuilt=(b'opaque unit record',),cadence_us=270000))
        async def check():
            await wire.send(b'{"id":1}')
            self.assertEqual(await wire.recv(),b'{"id":1,"result":1}')
        asyncio.run(check());self.assertEqual(wire.sent,0)
        self.assertIsNone(wire.first_release)
