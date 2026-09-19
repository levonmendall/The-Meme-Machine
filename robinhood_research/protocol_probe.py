"""Bounded protocol reconnaissance, never candidate or allocation authority.

Public chain evidence is also emitted in compressed chunks so a failed artifact
download cannot turn raw-log certification into a summary-only fixture again.
"""
import base64
import json
import os
from pathlib import Path
import time
import zlib

from . import BoundaryError
from .abi import calldata, decode_event, topic, words
from .identity import ROOT, authenticate, load
from .provider_topology import configured_rpc


def run(endpoint):
    report = dict(kind='natural_mainnet_protocol_capture', started_at=int(time.time()),
                  candidates=0, paper_lifecycles=0, allocation_authority=False,
                  identities={}, reads=[], lanes={}, failures={})
    rpc = configured_rpc(endpoint, limit=200, per_scope=130, retries=0)

    def call(address, sig, args=(), *, block, scope):
        data = calldata(sig, *args)
        value = rpc.call('eth_call', [dict(to=address, data=data), block], scope=scope)
        report['reads'].append(dict(address=address, signature=sig, args=list(args),
                                    block=block, value=value, observed_at=time.time()))
        return value

    def logs(address, start, end, scope, topics=None):
        query = dict(fromBlock=hex(start), toBlock=hex(end))
        if address:
            query['address'] = address
        if topics:
            query['topics'] = topics
        result = []
        # This endpoint's larger-range queries returned HTTP 400. Ten-block
        # slices are already proven; do not retry invalid larger requests.
        for first in range(start, end + 1, 10):
            query.update(fromBlock=hex(first), toBlock=hex(min(end, first+9)))
            result.extend(rpc.call('eth_getLogs', [query], scope=scope))
            if len(result) > 500:
                raise BoundaryError('protocol_log_capacity')
        return result

    def receipts(events, scope):
        unique = {x['transactionHash']: x['blockHash'] for x in events}
        out = []
        for tx, bh in list(unique.items())[:4]:
            r = rpc.receipt(tx, bh, scope=scope)
            if int(r['status'], 16) != 1:
                raise BoundaryError('failed_transaction')
            for event in (e for e in events if e['transactionHash'] == tx):
                if event not in r['logs']:
                    raise BoundaryError('receipt_log_disagreement')
            out.append(r)
        return out

    try:
        rpc.verify_chain()
        for tag in ('latest', 'finalized'):
            header = rpc.call('eth_getBlockByNumber', [tag, False])
            report[tag] = {k: header[k] for k in ('number', 'hash', 'timestamp', 'parentHash')}
        latest, end = int(report['latest']['number'], 16), int(report['finalized']['number'], 16)
        for path in sorted(ROOT.glob('*.json')):
            role = path.stem
            pin = load(role)
            code = rpc.call('eth_getCode', [pin['address'], hex(end)], scope='identity')
            try:
                report['identities'][role] = authenticate(role, pin['address'], code)
            except BoundaryError as exc:
                report['identities'][role] = dict(boundary=str(exc))
        for lane in ('pons', 'ramses'):
            lane_data = report['lanes'][lane] = {}
            try:
                if lane == 'pons':
                    factory, hook = (load(r)['address'] for r in ('pons_v2_factory', 'pons_v2_hook'))
                    for role in ('pons_v2_factory', 'pons_v2_hook'):
                        if 'boundary' in report['identities'][role]:
                            raise BoundaryError('pons_deployment_identity_failed')
                    lane_data['wiring'] = {sig: call(factory, sig, block=hex(end), scope=lane)
                        for sig in ('memeHook()', 'poolManager()', 'graduationExecutor()', 'launchDeployer()')}
                    lane_data['factory_logs'] = logs(factory, end-99, end, lane)
                    lane_data['hook_logs'] = logs(hook, end-99, end, lane,
                        [topic('PoolRegistered(bytes32,address,address,address)')])
                    lane_data['decoded_factory'] = [decode_event(load('pons_v2_factory')['abi'], e)
                        for e in lane_data['factory_logs']]
                    # Active curves can be found without pretending every matching topic is Pons.
                    activity = logs(None, latest-99, latest, lane,
                        [[topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)'),
                          topic('CurveSell(address,address,uint256,uint256,uint256,uint256)')]])
                    lane_data['unverified_curve_activity'] = activity
                    lane_data['receipts'] = receipts(lane_data['factory_logs'] + activity, lane)
                    lane_data['curves'] = []
                    for address in list(dict.fromkeys(e['address'] for e in activity))[:2]:
                        entry = dict(address=address, block=hex(latest), values={})
                        lane_data['curves'].append(entry)
                        entry['code'] = rpc.call('eth_getCode', [address, hex(latest)], scope=lane)
                        for sig in ('factory()', 'token()', 'pairToken()', 'getReserves()', 'realQuoteReserve()',
                                    'feeBps()', 'creatorTaxBps()', 'reservedTokens()', 'graduated()',
                                    'snipeTaxStartBps()', 'snipeTaxSeconds()', 'launchedAt()'):
                            try:
                                entry['values'][sig] = call(address, sig, block=hex(latest), scope=lane)
                            except BoundaryError as exc:
                                entry['values'][sig] = dict(boundary=str(exc))
                        token = entry['values']['token()']
                        if isinstance(token, str):
                            entry['factory_record'] = call(factory, 'getLaunchedToken(address)',
                                ('0x'+token[-40:],), block=hex(latest), scope=lane)
                else:
                    factory = load('ramses_factory')['address']
                    if 'boundary' in report['identities']['ramses_factory']:
                        raise BoundaryError('ramses_deployment_identity_failed')
                    lane_data['wiring'] = {sig: call(factory, sig, block=hex(end), scope=lane)
                        for sig in ('getLBPairImplementation()', 'feeCollector()', 'voter()', 'getNumberOfLBPairs()')}
                    count = int(lane_data['wiring']['getNumberOfLBPairs()'], 16)
                    lane_data['pools'] = []
                    # Deterministic bounded head/tail sample, not an activity-ranking study.
                    for index in sorted(set([0, max(0, count-2), max(0, count-1)])) if count else []:
                        raw = call(factory, 'getLBPairAtIndex(uint256)', (index,), block=hex(end), scope=lane)
                        address = '0x' + raw[-40:]
                        pool = dict(address=address, index=index)
                        lane_data['pools'].append(pool)
                        pool['code'] = rpc.call('eth_getCode', [address, hex(end)], scope=lane)
                        pool['is_pool'] = call(factory, 'isPool(address)', (address,), block=hex(end), scope=lane)
                        pool['logs'] = logs(address, end-9, end, lane)
                    selected = next((p for p in lane_data['pools'] if p['logs']), lane_data['pools'][0] if lane_data['pools'] else None)
                    if selected is None:
                        raise BoundaryError('no_factory_pools')
                    selected['logs'] = logs(selected['address'], end-599, end-10, lane) + selected['logs']
                    lane_data['selected_pool'] = selected['address']
                    lane_data['receipts'] = receipts(selected['logs'], lane)
                    abi = load('ramses_pool_implementation')['abi']
                    decoded = []
                    for event in selected['logs']:
                        try:
                            decoded.append(decode_event(abi, event))
                        except BoundaryError as exc:
                            decoded.append(dict(boundary=str(exc)))
                    selected['decoded'] = decoded
                    bins = sorted(set(x['args']['id'] for x in decoded if x.get('name') == 'Swap'))
                    if len(bins) > 8:
                        raise BoundaryError('touched_bin_capacity')
                    selected['states'] = {}
                    for height in (end-600, end):
                        header = rpc.call('eth_getBlockByNumber', [hex(height), False], scope=lane)
                        state = dict(header={k: header[k] for k in ('number','hash','timestamp','parentHash')}, values={}, bins={})
                        selected['states'][str(height)] = state
                        for sig in ('getTokenX()', 'getTokenY()', 'getBinStep()', 'getActiveId()', 'getReserves()',
                                    'getProtocolFees()', 'getStaticFeeParameters()', 'getVariableFeeParameters()',
                                    'getLBHooksParameters()', 'implementation()', 'getFactory()'):
                            state['values'][sig] = call(selected['address'], sig, block=hex(height), scope=lane)
                        for bin_id in bins:
                            state['bins'][str(bin_id)] = {sig: call(selected['address'], sig, (bin_id,),
                                block=hex(height), scope=lane) for sig in ('getBin(uint24)', 'totalSupply(uint256)')}
            except BoundaryError as exc:
                lane_data['boundary'] = str(exc)
    except BoundaryError as exc:
        report['failures']['session'] = str(exc)
    finally:
        report['provider'] = rpc.telemetry()
        report['ended_at'] = time.time()
    return report


if __name__ == '__main__':
    result = run(os.environ.get('MM_ROBINHOOD_READ_RPC_URL', ''))
    raw = json.dumps(result, sort_keys=True, separators=(',', ':')).encode()
    if len(raw) > 2_000_000:
        raise BoundaryError('report_capacity')
    Path('robinhood-protocol-report.json').write_bytes(raw)
    print(json.dumps(dict(provider=result['provider'], identities=result['identities'],
        boundaries={k:v.get('boundary') for k,v in result['lanes'].items()})))
    encoded = base64.b64encode(zlib.compress(raw, 9)).decode()
    for i in range(0, len(encoded), 6000):
        print('PUBLIC_EVIDENCE_CHUNK ' + str(i//6000) + ' ' + encoded[i:i+6000])