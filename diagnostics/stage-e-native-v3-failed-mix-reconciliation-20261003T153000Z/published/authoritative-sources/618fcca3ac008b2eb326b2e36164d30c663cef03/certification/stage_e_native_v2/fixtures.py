"""Pure, finite successor fixture construction. No runtime timestamp rewriting.

Only declared event timestamp bytes and synthetic fixture envelope identities
change. All other captured economic bytes remain identical. Signatures are
64-byte base58 fixture identities, not signed chain transactions or market proof.
"""
import base64
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import struct

from .clock import DeterministicClock

HERE = Path(__file__).resolve().parent


def b58(raw):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    prefix = len(raw) - len(raw.lstrip(b'\0'))
    value = int.from_bytes(raw, 'big'); result = ''
    while value:
        value, rem = divmod(value, 58)
        result = alphabet[rem] + result
    return '1' * prefix + result


def signature(label):
    return b58(hashlib.sha512(label.encode()).digest())


def timestamp_offset(raw):
    if raw[:8] in (bytes([103,244,82,31,44,245,119,119]),
                   bytes([62,47,55,10,165,3,220,42])):
        return 8
    if raw[:8] == bytes([189,219,127,211,78,230,97,238]):
        return 89
    if raw[:8] == hashlib.sha256(b'event:CompletePumpAmmMigrationEvent').digest()[:8]:
        return 128
    if raw[:8] == bytes([27,114,169,77,222,235,99,118]):
        offset = 8
        for _ in range(3):
            size = struct.unpack_from('<I', raw, offset)[0]
            offset += 4 + size
        return offset + 128
    return None


def economic_projection(tx):
    tx = deepcopy(tx)
    tx['transaction'].pop('signatures', None)
    tx.pop('blockTime', None); tx.pop('slot', None)
    logs = tx['meta'].get('logMessages') or []
    for index, line in enumerate(logs):
        if not line.startswith('Program data: '):
            continue
        raw = bytearray(base64.b64decode(line[14:], validate=True))
        offset = timestamp_offset(raw)
        if offset is not None:
            raw[offset:offset+8] = b'\0' * 8
            logs[index] = 'Program data: ' + base64.b64encode(raw).decode()
    return tx


def timed_transaction(template, at, label, failed=False):
    tx = deepcopy(template)
    tx['transaction']['signatures'] = [signature(label)]
    if failed:
        tx['meta']['err'] = {'InstructionError': [0, {'Custom': 1}]}
    for index, line in enumerate(tx['meta'].get('logMessages') or []):
        if not line.startswith('Program data: '):
            continue
        raw = bytearray(base64.b64decode(line[14:], validate=True))
        offset = timestamp_offset(raw)
        if offset is not None:
            struct.pack_into('<q', raw, offset, at)
            tx['meta']['logMessages'][index] = 'Program data: ' + base64.b64encode(raw).decode()
    return tx


def spec(run):
    return json.loads((HERE / 'fixtures' / (run + '-v2.json')).read_text())


def templates(run):
    return json.loads(gzip.decompress((HERE / 'fixtures' / (run + '-templates-v2.json.gz')).read_bytes()))


def build_frame(run, number, *, bounded=False, historical_seed=False):
    """Build before clock.begin(); bounded cases have their own distinct identity."""
    s = spec(run)
    if type(number) is not int or not 0 <= number < s['frames']:
        raise ValueError('fixture_frame_index')
    slot = (s.get('setup_start_slot', s['start_slot']) if historical_seed else s['start_slot']) + number
    due = s['clock']['wall_epoch'] + number * s['cadence_us'] / 1_000_000
    at = int(due - (s['prefix_age_seconds'] if historical_seed else 1))
    txs = []
    if run == 'run373':
        from meme_machine.postgrad import PUMPSWAP_PROGRAM
        for i in range(2 if bounded else 80):
            txs.append(dict(transaction=dict(signatures=[signature(f'{run}:{slot}:{i}')],
                message=dict(accountKeys=[PUMPSWAP_PROGRAM])), meta=dict(err=None, logMessages=[])))
        txs.append(dict(transaction=dict(signatures=[signature(f'{run}:{slot}:padding')],
            message=dict(accountKeys=['unrelated'])), meta=dict(err=None,
                logMessages=['x' * (128 if bounded else s['padding_bytes'])])))
    else:
        t = templates(run)
        mix = [('transactions',160)] if run == 'run379' else list(s['transaction_mix'].items())
        for lane, count in mix:
            for i in range(min(count, 2) if bounded else count):
                key = 'pumpswap' if lane == 'failed' else lane
                txs.append(timed_transaction(t[key][i % len(t[key])], at,
                    f'{run}:v2:{slot}:{len(txs)}', failed=lane == 'failed'))
    return json.dumps(dict(method='blockNotification', params=dict(subscription=1,
        result=dict(value=dict(slot=slot, err=None, block=dict(parentSlot=slot-1,
            blockhash='h'+str(slot), previousBlockhash='h'+str(slot-1),
            blockTime=at, transactions=txs))))), separators=(',', ':')).encode()


def construct_bounded(run, numbers=(0,1,2)):
    clock = DeterministicClock()
    before = (clock.time(), clock.monotonic())
    frames = tuple(build_frame(run, n, bounded=True) for n in numbers)
    if before != (clock.time(), clock.monotonic()) or clock.executing:
        raise ValueError('construction_consumed_residence_window')
    return clock, frames
