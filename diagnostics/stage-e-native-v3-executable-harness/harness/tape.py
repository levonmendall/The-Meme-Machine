"""Validate existing immutable bytes; deliberately no generator or retimer."""
import hashlib
import json
import os
from pathlib import Path
import struct
import zlib

from core import MAGIC, canonical, file_sha, read, require, sha, workload

LENGTH = struct.Struct('>Q')
MAX_RECORD = 16 * 1024**2


def decompress(compressed):
    decoder = zlib.decompressobj(31)
    raw = decoder.decompress(compressed, MAX_RECORD + 1)
    require(len(raw) <= MAX_RECORD and not decoder.unconsumed_tail, 'decoded_frame_bound')
    require(decoder.eof and not decoder.unused_data, 'gzip_truncated_or_extra_member')
    return raw


class Reader:
    def __init__(self, path, expected, *, immutable=True):
        self.path = Path(path)
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        self.file = os.fdopen(fd, 'rb')
        self.stat = os.fstat(fd)
        try:
            require(not immutable or not self.stat.st_mode & 0o222, 'tape_not_immutable')
            require(self.file.read(len(MAGIC)) == MAGIC, 'tape_magic')
        except BaseException:
            self.file.close()
            raise
        self.expected = expected
        self.count = 0
        self.encoded = hashlib.sha256(MAGIC)
        self.decoded = hashlib.sha256(MAGIC)

    def next(self):
        require(self.count < self.expected['frames'], 'source_frame_count')
        header = self.file.read(8)
        require(len(header) == 8, 'tape_truncated')
        size = LENGTH.unpack(header)[0]
        require(0 < size <= MAX_RECORD, 'encoded_record_bound')
        compressed = self.file.read(size)
        require(len(compressed) == size, 'tape_truncated')
        raw = decompress(compressed)
        self.encoded.update(header)
        self.encoded.update(compressed)
        self.decoded.update(LENGTH.pack(len(raw)))
        self.decoded.update(raw)
        row = dict(number=self.count, slot=1000+self.count, payload_bytes=len(raw),
                   payload_sha256=sha(raw), encoded_bytes=8+size)
        self.count += 1
        return raw, row

    def receipt(self):
        return dict(frames=self.count, encoded_prefix_bytes=self.file.tell(),
                    encoded_prefix_sha256=self.encoded.hexdigest(),
                    decoded_canonical_sha256=self.decoded.hexdigest())

    def close(self, *, strict=True, full=False):
        row = self.receipt()
        after = os.fstat(self.file.fileno())
        unchanged = (self.stat.st_dev, self.stat.st_ino, self.stat.st_size, self.stat.st_mtime_ns,
                     self.stat.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                                              after.st_mtime_ns, after.st_ctime_ns)
        eof = self.file.read(1) == b'' if full else None
        self.file.close()
        valid = unchanged and all(row[k] == self.expected[k] for k in row) and (not full or eof)
        row.update(valid=valid, immutable_file_unchanged=unchanged)
        require(not strict or valid, 'consumed_tape_mismatch')
        return row


def validate_existing(path, frame_inventory, *, kind='A'):
    binding = workload(kind)['tape_binding']
    require(Path(path).stat().st_size == binding['physical_bytes'], 'physical_tape_bytes')
    require(file_sha(frame_inventory) == binding['frame_inventory_sha256'], 'frame_inventory_hash')
    frames = read(frame_inventory)
    require(type(frames) is list and len(frames) == 4445, 'full_frame_inventory')
    expected = binding['members'][-1]
    reader = Reader(path, expected)
    checkpoints = {}
    try:
        for number, frame in enumerate(frames):
            raw, actual = reader.next()
            require(actual == frame and number == frame['number'], 'frame_inventory_bytes')
            body = json.loads(raw)['params']['result']['value']
            block = body['block']
            require(body['slot'] == 1000+number and block['parentSlot'] == 999+number
                    and block['blockhash'] == f'h{1000+number}'
                    and block['previousBlockhash'] == f'h{999+number}'
                    and block['blockTime'] == (1800000000*1000000+number*270000)//1000000-1
                    and len(block['transactions']) == 512, 'immutable_event_clock_or_shape')
            # Approved native population: 256 failed filler + 28 captured Meteora failures.
            require(sum(tx['meta']['err'] is not None for tx in block['transactions']) == 284, 'failed_transaction_mix')
            if reader.count in (2223, 4445):
                checkpoints[str(reader.count)] = reader.receipt()
                prefix = next(m for m in binding['members'] if m['frames'] == reader.count)
                require(all(checkpoints[str(reader.count)][k] == prefix[k] for k in checkpoints[str(reader.count)]),
                        'tape_prefix_binding')
        receipt = reader.close(full=True)
    except BaseException:
        if not reader.file.closed:
            reader.file.close()
        raise
    require(receipt['encoded_prefix_sha256'] == binding['physical_sha256'], 'physical_tape_sha256')
    return dict(version='v3-existing-tape-validation', binding_sha256=sha(canonical(binding)),
                path=str(Path(path).resolve()), physical_sha256=binding['physical_sha256'],
                frame_inventory_sha256=binding['frame_inventory_sha256'], checkpoints=checkpoints,
                frames_validated=4445, native_prefix_frames=240, no_regeneration=True,
                source_frames_released=0, valid=True)
