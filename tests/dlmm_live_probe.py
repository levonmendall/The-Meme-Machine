"""Opt-in public read-only capture. Never creates a Store, position or transaction.

python -m tests.dlmm_live_probe --pool <address> --output <capture.json>
Without --pool, inspect up to four fresh addresses in one bin-step partition.
"""
import argparse
import json
import time
from pathlib import Path
from meme_machine import dlmm
from meme_machine.dlmm_tape import reconstruct,MAX_TRANSACTIONS
from meme_machine.postgrad import PoolScanRPC
from meme_machine.provider import Unavailable
from meme_machine.store import encode


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pool');parser.add_argument('--bin-step',type=int,default=25)
    parser.add_argument('--wait-seconds',type=int,default=0)
    parser.add_argument('--output',required=True);args=parser.parse_args()
    if not 0<=args.wait_seconds<=60:parser.error('--wait-seconds must be 0..60')
    rpc=PoolScanRPC('https://api.mainnet-beta.solana.com',limit=80);adapter=dlmm.Adapter(rpc)
    capture=dict(kind='real_finalized_rpc_capture',allocation_enabled=False,transactions={})
    report=dict(allocation_enabled=False,signing=False,real_swap_count=0,verified_interval=False)
    try:
        addresses=[args.pool] if args.pool else adapter.pool_addresses(args.bin_step,int(time.time()))
        rejected=[]
        for address in addresses:
            try:
                capture['start']=adapter.snapshot(address,int(time.time()),True);break
            except (ValueError,Unavailable) as exc:rejected.append(dict(pool=address,reason=str(exc)))
        report['discovery_rejections']=rejected
        if 'start' not in capture:raise Unavailable('dlmm_no_validated_pool_in_bounded_partition')
        # The next account read naturally advances through public RPC latency.
        # No trade is generated and no qualifying economic outcome is required.
        if args.wait_seconds:time.sleep(args.wait_seconds)
        rpc.cache.clear();rpc.cache_bytes=0
        capture['end']=adapter.snapshot(capture['start']['pool'],int(time.time()),True)
        start=dlmm.validate(capture['start'],capture['start']['available_time'],'real')
        end=capture['end'];now=int(time.time())
        sigs=rpc.call('getSignaturesForAddress',[start['pool'],dict(limit=64,commitment='finalized')],True)
        capture['signatures']=sigs
        selected=[s for s in sigs if start['slot']<s['slot']<=end['slot'] and not s.get('err')]
        if len(selected)>MAX_TRANSACTIONS:raise Unavailable('dlmm_transaction_bound')
        for sig in selected:
            capture['transactions'][sig['signature']]=rpc.call('getTransaction',[sig['signature'],
                dict(encoding='json',commitment='finalized',maxSupportedTransactionVersion=0)],True)
            if len(encode(capture))>2_000_000:raise Unavailable('dlmm_capture_size_bound')
        now=int(time.time());capture['validated_at']=now
        tape=reconstruct(start,end,sigs,capture['transactions'],now,[start['slot'],2**31-1,2**31-1])
        report.update(verified_interval=True,real_swap_count=len(tape.events),lineage=tape.lineage,
                      executable_evidence_fresh=now-end['market_time']<=dlmm.MAX_AGE)
    except (ValueError,Unavailable,KeyError,TypeError) as exc:
        report['unresolved']=str(exc)
    report.update(rpc_calls=rpc.calls,provider_failure_kinds=rpc.failure_kinds)
    capture['report']=report
    Path(args.output).write_text(json.dumps(capture,sort_keys=True,indent=2)+'\n')
    print(json.dumps(report,sort_keys=True))

if __name__=='__main__':main()
