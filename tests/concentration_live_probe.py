"""One-mint read-only concentration probe; no scout, policy, or order authority."""
import json
import os
import time

from meme_machine.concentration import ConcentrationReader
from meme_machine.provider import PumpAdapter, RPC, Unavailable

# Naturally nominated Mayhem mint from exact stream run 35168835439.
MINT='DnRCpeTggn8qp5w42Kv82agMTS5tD3p9B1GhNdEApump'


def main():
    url=os.environ.get('MM_SOLANA_RPC_URL','https://api.mainnet-beta.solana.com')
    rpc=RPC(url,limit=40)
    reader=ConcentrationReader(rpc,secondary_url='')
    report=dict(kind='read_only_concentration_probe',mint=MINT,network='solana-mainnet',
                protocol='pump.fun',paper_trades=0,order_authority=False,
                provider_spend_usd=0 if url=='https://api.mainnet-beta.solana.com' else None,
                infrastructure_spend_usd=0)
    try:
        adapter=PumpAdapter(rpc)
        snap=adapter.snapshot(MINT,int(time.time()),priority=True)
        value,meta=reader.read(MINT,snap,priority=True)
        report.update(concentration_bps=value,concentration_source=meta['source'],
                      concentration_slot=meta['slot'],snapshot_slot=snap['slot'],success=True)
    except (Unavailable,ValueError,KeyError,TypeError) as exc:
        report.update(success=False,limitation=str(exc))
    report.update(primary_logical_requests=rpc.calls,
                  primary_transport_requests=rpc.http_requests,
                  primary_failures=rpc.failures,primary_retries=rpc.retries,
                  primary_failure_kinds=rpc.failure_kinds,
                  concentration_retrieval=reader.status())
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    main()
