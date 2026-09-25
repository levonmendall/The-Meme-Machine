"""Bounded official-public-RPC log-shape diagnostic; no trading or credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--worktrees', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    lane = Path(a.worktrees).resolve() / 'ramses'
    sys.path.insert(0, str(lane))
    from robinhood_research.ramses_capture import BoundedMultiRpc
    from robinhood_research.ramses_universe import FACTORY_SEED
    from robinhood_research.abi import topic
    inventory = json.loads(FACTORY_SEED.read_text())
    addresses = inventory['addresses']
    rpc = BoundedMultiRpc('', max_sessions=1, batch_size=1, batch_pause=0,
                          rate_retries=0, adaptive_batch_floor=1,
                          provider_role='public_observation')
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    result = dict(paper_only=True, trade_authority=False, provider='official_robinhood_public',
                  address_count=len(addresses), observed_at=time.time())
    try:
        rpc.verify_chain()
        frontier = rpc.call('eth_getBlockByNumber', ['finalized', False], scope='shape_probe')
        result['frontier'] = frontier
        end = int(frontier['number'], 16)
        topics = [topic(x) for x in (
            'Swap(address,address,uint24,bytes32,bytes32,uint24,bytes32,bytes32)',
            'DepositedToBins(address,address,uint256[],bytes32[])',
            'WithdrawnFromBins(address,address,uint256[],bytes32[])')]
        for span in (10, 100, 1000):
            query = dict(fromBlock=hex(end-span+1), toBlock=hex(end),
                         address=addresses, topics=[topics])
            row = dict(span_blocks=span, request=query)
            try:
                logs = rpc.call('eth_getLogs', [query], scope='shape_probe')
                if not isinstance(logs, list):
                    raise ValueError('logs_shape')
                row.update(supported=True, log_count=len(logs), logs=logs)
            except Exception as exc:
                message = str(exc)
                row.update(supported=False, boundary=message if message.replace('_', '').isalnum()
                           and len(message) < 160 else type(exc).__name__)
            rows.append(row)
            (out/'probe.json').write_text(json.dumps(dict(result, probes=rows), sort_keys=True, indent=2)+'\n')
    finally:
        result.update(probes=rows, telemetry=rpc.telemetry())
        raw = json.dumps(result, sort_keys=True, indent=2)+'\n'
        (out/'probe.json').write_text(raw)
        print(json.dumps(dict(sha256=hashlib.sha256(raw.encode()).hexdigest(),
            probes=[{k:v for k,v in row.items() if k not in ('logs','request')} for row in rows]), sort_keys=True))


if __name__ == '__main__':
    main()
