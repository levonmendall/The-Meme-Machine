"""Read-only attribution of the exact Ramses dynamic-array failure."""
import collections,gzip,hashlib,json,runpy
from robinhood_research.abi import signature,topic
state=runpy.run_path('certification/frozen_artifact_review.py')
specs=json.loads("[{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"address\",\"name\":\"sender\",\"type\":\"address\"},{\"indexed\":true,\"internalType\":\"address\",\"name\":\"to\",\"type\":\"address\"},{\"indexed\":false,\"internalType\":\"uint256[]\",\"name\":\"ids\",\"type\":\"uint256[]\"},{\"indexed\":false,\"internalType\":\"bytes32[]\",\"name\":\"amounts\",\"type\":\"bytes32[]\"}],\"name\":\"DepositedToBins\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"address\",\"name\":\"sender\",\"type\":\"address\"},{\"indexed\":true,\"internalType\":\"address\",\"name\":\"to\",\"type\":\"address\"},{\"indexed\":false,\"internalType\":\"uint256[]\",\"name\":\"ids\",\"type\":\"uint256[]\"},{\"indexed\":false,\"internalType\":\"bytes32[]\",\"name\":\"amounts\",\"type\":\"bytes32[]\"}],\"name\":\"WithdrawnFromBins\",\"type\":\"event\"}]")
topics={topic(signature(spec)):spec['name'] for spec in specs}
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
