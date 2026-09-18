"""One bounded GitHub-only read proof; no recurrent job or allocation authority."""
import hashlib
import json
import os
from pathlib import Path
import time

from . import BoundaryError
from .provider import Rpc


def run(endpoint):
    report = dict(kind='natural_mainnet_read_probe', status='blocked',
                  natural_candidates=0, paper_lifecycles=0, dlmm_observations=0,
                  protocol_identity_verified=False, started_at=int(time.time()))
    rpc = None
    try:
        rpc = Rpc(endpoint, limit=80, per_scope=40, retries=0)
        report['chain_id'] = rpc.verify_chain()
        latest = rpc.call('eth_getBlockByNumber', ['latest', False])
        finalized = rpc.call('eth_getBlockByNumber', ['finalized', False])
        now = int(time.time())
        if not 0 <= now - int(latest['timestamp'], 16) <= 120:
            raise BoundaryError('stale_or_future_latest_block')
        end = int(finalized['number'], 16)
        if end > int(latest['number'], 16):
            raise BoundaryError('invalid_finalized_frontier')
        report['latest'] = {k: latest[k] for k in ('number', 'hash', 'timestamp')}
        report['finalized'] = {k: finalized[k] for k in ('number', 'hash', 'timestamp')}
        registry = json.loads(Path(__file__).with_name('registry.json').read_text())
        report['code_presence'] = {}
        for name, address in registry['contracts'].items():
            code = rpc.call('eth_getCode', [address, hex(end)], scope='discovery')
            report['code_presence'][name] = dict(address=address, present=code != '0x',
                bytecode_sha256=hashlib.sha256(bytes.fromhex(code[2:])).hexdigest())
        start = max(0, end - 9)
        logs = rpc.call('eth_getLogs', [dict(fromBlock=hex(start), toBlock=hex(end),
            address=list(registry['contracts'].values()))], scope='discovery')
        if not isinstance(logs, list) or len(logs) > 1000:
            raise BoundaryError('log_response_capacity_or_shape')
        report['log_window'] = dict(start=start, end=end, count=len(logs))
        # Capture only this bounded batch. Empty logs prove API response, not completeness.
        report['logs'] = logs
        report['receipts_verified'] = 0
        for tx in list(dict.fromkeys(x['transactionHash'] for x in logs))[:3]:
            receipt = rpc.call('eth_getTransactionReceipt', [tx], scope='discovery')
            expected = [x for x in logs if x['transactionHash'] == tx]
            for event in expected:
                if receipt['blockHash'] != event['blockHash'] or event not in receipt['logs']:
                    raise BoundaryError('receipt_log_mismatch')
            report['receipts_verified'] += 1
        # If factory window is empty, use a finalized block transaction for receipt capability.
        if not report['receipts_verified'] and finalized.get('transactions'):
            tx = finalized['transactions'][0]
            receipt = rpc.call('eth_getTransactionReceipt', [tx], scope='connectivity')
            if receipt['blockHash'] != finalized['hash']:
                raise BoundaryError('receipt_block_mismatch')
            report['receipts_verified'] = 1
        historic = max(0, end - 100)
        address = registry['contracts']['pons_v2_factory']
        report['historical_code_available'] = rpc.call(
            'eth_getCode', [address, hex(historic)], scope='history') != '0x'
        # Historical eth_call capability on a known standard token method; not a curve quote.
        weth = '0x0bd7d308f8e1639fab988df18a8011f41eacad73'
        decimals = rpc.call('eth_call', [dict(to=weth, data='0x313ce567'), hex(historic)], scope='history')
        report['historical_eth_call'] = int(decimals, 16) == 18
        report['status'] = 'read_capabilities_observed'
        report['next_boundary'] = 'verify_protocol_ABIs_and_decode_natural_launch_lineage'
    except (BoundaryError, ValueError, KeyError, TypeError) as exc:
        report['boundary'] = str(exc) if isinstance(exc, BoundaryError) else 'malformed_provider_evidence'
    finally:
        report['provider'] = rpc.telemetry() if rpc else {'requests': 0}
        report['ended_at'] = int(time.time())
    return report


if __name__ == '__main__':
    report = run(os.environ.get('MM_ROBINHOOD_READ_RPC_URL', ''))
    Path('robinhood-live-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'logs'}, sort_keys=True))
    raise SystemExit(0 if report['status'] == 'read_capabilities_observed' else 2)
