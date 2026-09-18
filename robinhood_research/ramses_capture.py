"""Factory-validated active pool discovery and bounded finalized replay capture."""
import base64
import json
import os
from pathlib import Path
import time
import zlib

from . import BoundaryError
from .abi import calldata, decode_event, topic
from .identity import authenticate, load
from .provider import Rpc


def run(endpoint):
    rpc = Rpc(endpoint, limit=200, per_scope=160, retries=0)
    result = dict(kind='captured_finalized_ramses', started_at=time.time(), reads=[],
                  allocation_authority=False, prospective_range=False)
    factory = load('ramses_factory')['address']
    abi = load('ramses_pool_implementation')['abi']

    def read(address, sig, args=(), block=None, scope='pool'):
        val = rpc.call('eth_call', [dict(to=address, data=calldata(sig, *args)), hex(block)], scope=scope)
        result['reads'].append(dict(address=address, signature=sig, args=list(args), block=block,
                                    value=val, observed_at=time.time()))
        return val

    def logs(start, end, address=None, topics=None):
        found = []
        for first in range(start, end+1, 10):
            q = dict(fromBlock=hex(first), toBlock=hex(min(end, first+9)))
            if address:
                q['address'] = address
            if topics:
                q['topics'] = topics
            found += rpc.call('eth_getLogs', [q], scope='pool' if address else 'discovery')
            if len(found) > 300:
                raise BoundaryError('capture_log_capacity')
        return found

    try:
        rpc.verify_chain()
        frontier = rpc.call('eth_getBlockByNumber', ['finalized', False])
        end = int(frontier['number'], 16)
        result['frontier'] = {k:frontier[k] for k in ('hash','number','timestamp','parentHash')}
        result['identities'] = {}
        for role in ('ramses_factory', 'ramses_pool_implementation'):
            pin = load(role)
            code = rpc.call('eth_getCode', [pin['address'], hex(end)], scope='discovery')
            result['identities'][role] = authenticate(role,pin['address'],code)
        activity = logs(end-99, end, topics=[topic('Swap(address,address,uint24,bytes32,bytes32,uint24,bytes32,bytes32)')])
        result['discovery_logs'] = activity
        candidates = sorted(set(e['address'] for e in activity))
        result['factory_checks'] = {}
        address = None
        for candidate in candidates[:5]:
            check = read(factory,'isPool(address)',(candidate,),end,'discovery')
            result['factory_checks'][candidate] = check
            if int(check,16) == 1:
                address = candidate
                break
        if address is None:
            raise BoundaryError('no_factory_validated_activity_in_100_block_window')
        result['pool'] = address
        result['pool_code'] = rpc.call('eth_getCode',[address,hex(end)],scope='pool')
        events = logs(end-599,end,address=address)
        result['logs'] = events
        result['decoded'] = []
        for event in events:
            try:
                result['decoded'].append(decode_event(abi,event))
            except BoundaryError as exc:
                result['decoded'].append(dict(boundary=str(exc),topic=event['topics'][0]))
        txs = {e['transactionHash']:e['blockHash'] for e in events}
        if len(txs) > 20:
            raise BoundaryError('capture_receipt_capacity')
        result['receipts'] = [rpc.receipt(tx,bh,scope='pool') for tx,bh in txs.items()]
        heights = sorted(set([end-600,end]+[int(e['blockNumber'],16) for e in events]))
        if len(heights) > 24:
            raise BoundaryError('capture_header_capacity')
        result['headers'] = {}
        for h in heights:
            header = rpc.call('eth_getBlockByNumber',[hex(h),False],scope='pool')
            result['headers'][str(h)] = {k:header[k] for k in ('number','hash','timestamp','parentHash')}
        bins = sorted(set(x['args']['id'] for x in result['decoded'] if x.get('name')=='Swap'))
        if len(bins)>8:
            raise BoundaryError('capture_bin_capacity')
        result['states'] = {}
        for h in (end-600,end):
            state = dict(values={},bins={})
            result['states'][str(h)] = state
            for sig in ('getTokenX()', 'getTokenY()', 'getBinStep()', 'getActiveId()', 'getReserves()',
                        'getProtocolFees()', 'getStaticFeeParameters()', 'getVariableFeeParameters()',
                        'getLBHooksParameters()', 'implementation()', 'getFactory()'):
                state['values'][sig] = read(address,sig,block=h)
            for b in bins:
                state['bins'][str(b)] = {sig:read(address,sig,(b,),h) for sig in
                    ('getBin(uint24)','totalSupply(uint256)','getPriceFromId(uint24)')}
        # Re-read canonical terminal hash after the acquisition; no unfinalized tape.
        check=rpc.call('eth_getBlockByNumber',[hex(end),False],scope='pool')
        if check['hash'] != frontier['hash']:
            raise BoundaryError('finalized_chain_disagreement')
    except BoundaryError as exc:
        result['boundary'] = str(exc)
    result['provider'] = rpc.telemetry()
    result['ended_at'] = time.time()
    return result


if __name__ == '__main__':
    result=run(os.environ.get('MM_ROBINHOOD_READ_RPC_URL',''))
    raw=json.dumps(result,sort_keys=True,separators=(',',':')).encode()
    if len(raw)>2_000_000:
        raise BoundaryError('report_capacity')
    Path('robinhood-ramses-report.json').write_bytes(raw)
    print(json.dumps(dict(boundary=result.get('boundary'),pool=result.get('pool'),provider=result['provider'])))
    data=base64.b64encode(zlib.compress(raw,9)).decode()
    for i in range(0,len(data),6000):
        print('PUBLIC_EVIDENCE_CHUNK '+str(i//6000)+' '+data[i:i+6000])
