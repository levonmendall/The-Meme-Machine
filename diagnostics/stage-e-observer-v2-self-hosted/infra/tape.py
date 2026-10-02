"""Finite extension of v2's pure run380 generator; no execution or retiming."""
import gzip
import hashlib
import json
import struct
from pathlib import Path
from core import BASE,COHORT,persist,sha,file_sha

MAGIC=b'MMOBSV2\0'
LENGTH=struct.Struct('>Q')


def extended_frame(number,fixture,spec,templates):
    if type(number) is not int or not 0<=number<4445:
        raise ValueError('finite_full_cohort_frame_index')
    slot=spec['start_slot']+number
    due=spec['clock']['wall_epoch']+number*spec['cadence_us']/1_000_000
    at=int(due-1);txs=[]
    for lane,count in spec['transaction_mix'].items():
        for i in range(count):
            key='pumpswap' if lane=='failed' else lane
            txs.append(fixture.timed_transaction(templates[key][i%len(templates[key])],at,
                f'run380:v2:{slot}:{len(txs)}',failed=lane=='failed'))
    return json.dumps(dict(method='blockNotification',params=dict(subscription=1,
        result=dict(value=dict(slot=slot,err=None,block=dict(parentSlot=slot-1,
            blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),
            blockTime=at,transactions=txs))))),separators=(',',':')).encode()


def generate(output):
    from certification.stage_e_native_v2 import fixtures
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    target=BASE/'tape';target.mkdir(exist_ok=False)
    path=target/'full-cohort-v2.tape'
    spec=fixtures.spec('run380');templates=fixtures.templates('run380')
    assert spec['frames']==240 and spec['cadence_us']==270000
    assert spec['clock']['wall_epoch']==1800000000
    assert sum(spec['transaction_mix'].values())==512
    encoded=hashlib.sha256(MAGIC);decoded=hashlib.sha256(MAGIC)
    frame_hashes=[];checkpoints={};equivalence=[]
    with path.open('xb') as f:
        f.write(MAGIC)
        for number in range(4445):
            raw=extended_frame(number,fixtures,spec,templates)
            if number<spec['frames']:
                native=fixtures.build_frame('run380',number)
                if raw!=native:raise ValueError('v2_generator_equivalence:'+str(number))
                equivalence.append(sha(native))
            compressed=gzip.compress(raw,compresslevel=6,mtime=0)
            record=LENGTH.pack(len(compressed))+compressed
            f.write(record);encoded.update(record)
            decoded.update(LENGTH.pack(len(raw)));decoded.update(raw)
            frame_hashes.append(dict(number=number,slot=spec['start_slot']+number,
                payload_bytes=len(raw),payload_sha256=sha(raw),encoded_bytes=len(record)))
            count=number+1
            if count in (2223,4445):
                checkpoints[str(count)]=dict(frames=count,encoded_prefix_bytes=f.tell(),
                    encoded_prefix_sha256=encoded.hexdigest(),
                    decoded_canonical_sha256=decoded.hexdigest())
            if count%100==0:print(json.dumps(dict(phase='tape_generation',frames=count,started_trials=0)),flush=True)
        f.flush();__import__('os').fsync(f.fileno())
    assert file_sha(path)==encoded.hexdigest()
    path.chmod(0o444)
    inventory_sha=persist(target/'FRAMES.json',frame_hashes)
    row=dict(version='immutable-equal-byte-full-cohort-tape-v1',
        workload_identity='native-full-cohort-pressure-v2',tape=str(path),
        physical_sha256=encoded.hexdigest(),physical_bytes=path.stat().st_size,
        format='MMOBSV2 NUL; repeated uint64 big-endian gzip byte length and deterministic gzip member',
        member_selection='fixed prefix count; no live timestamp replacement',
        decoded_format='MMOBSV2 NUL; repeated uint64 big-endian payload length and exact v2 JSON bytes',
        members=[dict(id=name,**checkpoints[str(count)]) for name,count in COHORT],
        frame_inventory_sha256=inventory_sha,frames_file=str(target/'FRAMES.json'),
        wall_epoch=1800000000,monotonic_epoch=100,cadence_us=270000,
        transaction_mix=spec['transaction_mix'],generated_before_any_source_release=True)
    tape_sha=persist(target/'TAPE.json',row)
    proof=dict(version='v2-fixture-generator-equivalence-v1',passed=True,
        checked_all_declared_native_frames=240,native_frame_hashes=equivalence,
        extension_bounds=[0,4444],native_bounds=[0,239],
        extension_change='Only finite frame index bound extended to 4445. All formulas and native timestamp/signature helpers unchanged.',
        economic_bytes='Native timed_transaction copies templates and changes only fixture signatures, failed filler err, and declared event timestamp offsets.',
        immutable_native_files_changed=False,native_build_frame_sha256=file_sha(Path(fixtures.__file__)),
        external_generator_sha256=file_sha(Path(__file__)),tape_manifest_sha256=tape_sha,
        started_trials=0,started_members=0)
    persist(output/'GENERATOR_EQUIVALENCE.json',proof)
    persist(output/'TAPE.json',row)
    persist(output/'TAPE_HASH.json',dict(manifest_sha256=tape_sha))
    for p in target.iterdir():p.chmod(0o444)
    target.chmod(0o555)


class Reader:
    def __init__(self,frames):
        meta=__import__('core').read(BASE/'tape/TAPE.json')
        self.expected=next(x for x in meta['members'] if x['frames']==frames)
        self.file=Path(meta['tape']).open('rb');self.frames=frames;self.count=0
        if self.file.read(len(MAGIC))!=MAGIC:raise ValueError('tape_magic')
        self.encoded=hashlib.sha256(MAGIC);self.decoded=hashlib.sha256(MAGIC)
    def next(self):
        if self.count>=self.frames:raise ValueError('source_frame_count')
        header=self.file.read(8)
        if len(header)!=8:raise ValueError('tape_truncated')
        size=LENGTH.unpack(header)[0]
        if not 0<size<16*1024**2:raise ValueError('tape_record_bound')
        compressed=self.file.read(size)
        if len(compressed)!=size:raise ValueError('tape_truncated')
        self.encoded.update(header);self.encoded.update(compressed)
        raw=gzip.decompress(compressed)
        self.decoded.update(LENGTH.pack(len(raw)));self.decoded.update(raw)
        self.count+=1
        return raw
    def close(self,strict=True):
        consumed=self.file.tell();self.file.close()
        row=dict(frames=self.count,encoded_prefix_bytes=consumed,
            encoded_prefix_sha256=self.encoded.hexdigest(),
            decoded_canonical_sha256=self.decoded.hexdigest())
        valid=row=={k:self.expected[k] for k in row}
        row['valid']=valid
        if strict and not valid:raise ValueError('consumed_tape_mismatch')
        return row
