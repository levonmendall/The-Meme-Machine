"""Read-only attribution of the exact Ramses dynamic-array failure."""
import collections,gzip,hashlib,json,runpy
# Pure Keccak helper copied unchanged from frozen Ramses source 6b7ddd69940f5c9e056b2dca61c443450ca9965e.
"""Minimal Keccak-256 for Ethereum pool IDs (not NIST SHA3-256)."""
MASK = (1 << 64) - 1
RC = (0x1,0x8082,0x800000000000808a,0x8000000080008000,0x808b,0x80000001,
      0x8000000080008081,0x8000000000008009,0x8a,0x88,0x80008009,0x8000000a,
      0x8000808b,0x800000000000008b,0x8000000000008089,0x8000000000008003,
      0x8000000000008002,0x8000000000000080,0x800a,0x800000008000000a,
      0x8000000080008081,0x8000000000008080,0x80000001,0x8000000080008008)
ROT = ((0,36,3,41,18),(1,44,10,45,2),(62,6,43,15,61),(28,55,25,21,56),(27,20,39,8,14))


def rol(value, count):
    return ((value << count) | (value >> (64-count))) & MASK


def keccak256(data):
    rate = 136
    pad = rate - len(data) % rate
    data = data + (b'\x81' if pad == 1 else b'\x01' + b'\x00'*(pad-2) + b'\x80')
    a = [0]*25
    for offset in range(0, len(data), rate):
        for i in range(rate//8):
            a[i] ^= int.from_bytes(data[offset+i*8:offset+i*8+8], 'little')
        for rc in RC:
            c = [a[x]^a[x+5]^a[x+10]^a[x+15]^a[x+20] for x in range(5)]
            d = [c[(x-1)%5]^rol(c[(x+1)%5],1) for x in range(5)]
            b = [0]*25
            for x in range(5):
                for y in range(5):
                    b[y+5*((2*x+3*y)%5)] = rol(a[x+5*y]^d[x],ROT[x][y])
            for x in range(5):
                for y in range(5):
                    a[x+5*y] = b[x+5*y]^((~b[(x+1)%5+5*y]) & b[(x+2)%5+5*y])
            a[0] ^= rc
    return b''.join(x.to_bytes(8, 'little') for x in a)[:32]

assert keccak256(b'').hex()=='c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470'
state=runpy.run_path('certification/frozen_artifact_review.py')
specs=json.loads("[{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"address\",\"name\":\"sender\",\"type\":\"address\"},{\"indexed\":true,\"internalType\":\"address\",\"name\":\"to\",\"type\":\"address\"},{\"indexed\":false,\"internalType\":\"uint256[]\",\"name\":\"ids\",\"type\":\"uint256[]\"},{\"indexed\":false,\"internalType\":\"bytes32[]\",\"name\":\"amounts\",\"type\":\"bytes32[]\"}],\"name\":\"DepositedToBins\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"address\",\"name\":\"sender\",\"type\":\"address\"},{\"indexed\":true,\"internalType\":\"address\",\"name\":\"to\",\"type\":\"address\"},{\"indexed\":false,\"internalType\":\"uint256[]\",\"name\":\"ids\",\"type\":\"uint256[]\"},{\"indexed\":false,\"internalType\":\"bytes32[]\",\"name\":\"amounts\",\"type\":\"bytes32[]\"}],\"name\":\"WithdrawnFromBins\",\"type\":\"event\"}]")
topics={'0x'+keccak256((spec['name']+'('+','.join(item['type'] for item in spec['inputs'])+')').encode()).hex():spec['name'] for spec in specs}
found={};response_shapes=collections.Counter()
def events(value):
    if isinstance(value,dict):
        if all(key in value for key in ('topics','data','blockHash','transactionHash','logIndex')):
            yield value
        else:
            for child in value.values():yield from events(child)
    elif isinstance(value,list):
        for child in value:yield from events(child)
with gzip.open(state['base']/'ramses/rpc-evidence.jsonl.gz','rt') as file:
    for line in file:
        row=json.loads(line);response_shapes[type(row.get('response')).__name__]+=1
        for event in events(row.get('response')):
            if not event['topics'] or event['topics'][0].lower() not in topics:continue
            raw=bytes.fromhex(event['data'][2:])
            if len(raw)<64:continue
            arrays=[]
            for name,pos in (('ids',0),('amounts',32)):
                offset=int.from_bytes(raw[pos:pos+32],'big')
                count=int.from_bytes(raw[offset:offset+32],'big') if offset+32<=len(raw) else None
                arrays.append(dict(name=name,offset=offset,count=count,
                    extent=None if count is None else offset+32*(count+1),
                    aligned=offset%32==0,head_excluded=offset>=64))
            if not any(a['count'] is not None and a['count']>64 for a in arrays):continue
            key=(event['blockHash'],event['transactionHash'],event['logIndex'])
            shape=(len(raw)<=65536 and len(raw)%32==0 and len(event['topics'])==3
                   and all(a['aligned'] and a['head_excluded'] and a['extent'] is not None and a['extent']<=len(raw) for a in arrays)
                   and arrays[0]['count']==arrays[1]['count']
                   and arrays[0]['extent']<=arrays[1]['offset']
                   and arrays[1]['extent']==len(raw))
            found.setdefault(key,dict(event=event,event_name=topics[event['topics'][0].lower()],
                data_bytes=len(raw),data_sha256=hashlib.sha256(raw).hexdigest(),arrays=arrays,
                complete_bounded_abi_shape=shape,observations=[]))['observations'].append(
                {k:row.get(k) for k in ('physical_request_id','observed_at_ns','http_status',
                    'json_rpc_error_codes','retry_count','original_deadline','scope')})
rows=sorted(found.values(),key=lambda r:(int(r['event']['blockNumber'],16),int(r['event']['transactionIndex'],16),int(r['event']['logIndex'],16)))
audit=dict(run=state['RUN'],sha=state['SHA'],artifact=state['artifact']['id'],
    verified_sha256=state['actual'],response_shapes=dict(response_shapes),
    decoder_limit=64,unchanged_event_byte_limit=65536,large_array_events=rows)
(state['OUT']/'ramses-dynamic-array-attribution.json').write_text(json.dumps(audit,indent=2,sort_keys=True))
print('RAMSES_DYNAMIC_ARRAY_AUDIT_BEGIN',flush=True)
print(json.dumps(dict(audit,large_array_events=[
    dict(r,event={k:v for k,v in r['event'].items() if k!='data'}) for r in rows]),sort_keys=True),flush=True)
print('RAMSES_DYNAMIC_ARRAY_AUDIT_END',flush=True)
if rows:
    fixture=dict(source=dict(run=state['RUN'],sha=state['SHA'],artifact=state['artifact']['id'],
        sha256=state['actual']),event=rows[0]['event'],expected_event=rows[0]['event_name'],
        arrays=rows[0]['arrays'],complete_bounded_abi_shape=rows[0]['complete_bounded_abi_shape'])
    (state['OUT']/'ramses-large-liquidity-event.json').write_text(json.dumps(fixture,indent=2,sort_keys=True))
    print('RAMSES_DYNAMIC_EVENT_FIXTURE_BEGIN',flush=True)
    print(json.dumps(fixture,sort_keys=True),flush=True)
    print('RAMSES_DYNAMIC_EVENT_FIXTURE_END',flush=True)
if not rows:raise RuntimeError('no_archived_large_array_event_found')
