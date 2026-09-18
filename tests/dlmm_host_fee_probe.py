"""One-shot read-only proof for the captured JUP-SOL host-fee interval."""
from __future__ import annotations
import json, os, struct
from pathlib import Path

from meme_machine import dlmm, pump
from meme_machine.dlmm_tape import (
    EVENT_CPI, SWAP, SWAP2, EXACT_IN, EXACT_IN_NAME,
    _keys, _ordered_instructions, _un58_data,
)
from meme_machine.postgrad import PoolScanRPC
from tests import dlmm_alchemy_provider as alchemy_provider


class HistoricalProbeRPC(PoolScanRPC):
    # Probe-only exact-slot lookup. Production/live RPC allowlists are unchanged.
    ALLOWED = PoolScanRPC.ALLOWED | {'getBlock'}
from meme_machine.provider import Unavailable

POOL='C8Gr6AUuq9hEdSYJzoEpNcdjpojPZwqG5MtQbeouNNwg'
START_SLOT=447920201
END_SLOT=447920212
OUT=Path('dlmm-host-fee-probe.json')
HOST_FEE_BPS=2000


def _event(raw,pool):
    if raw[:8]==SWAP:
        if len(raw)!=137 or pump.b58(raw[8:40])!=pool:
            raise ValueError('host_probe_legacy_event_identity')
        start,end,amount,output,direction,fee,protocol=struct.unpack_from('<iiQQ?QQ',raw,72)
        host=int.from_bytes(raw[129:137],'little')
        return dict(kind='swap',start=start,end=end,amount_in=amount,amount_out=output,
                    swap_for_y=bool(direction),fee=fee,protocol_fee=protocol,host_fee=host)
    if raw[:8]==SWAP2:
        if len(raw)!=155 or pump.b58(raw[8:40])!=pool:
            raise ValueError('host_probe_swap2_event_identity')
        start,end=struct.unpack_from('<ii',raw,72)
        amount,left,output,mm_fee,protocol,limit_fee,host=struct.unpack_from('<QQQQQQQ',raw,97)
        return dict(kind='swap2',start=start,end=end,amount_in=amount,amount_left=left,
                    amount_out=output,mm_fee=mm_fee,protocol_fee=protocol,
                    limit_order_fee=limit_fee,host_fee=host,
                    fees_on_input=bool(raw[153]),fees_on_token_x=bool(raw[154]))
    return None


def _token_balances(meta):
    def rows(name):
        result={}
        for row in meta.get(name) or []:
            idx=row.get('accountIndex')
            amount=((row.get('uiTokenAmount') or {}).get('amount'))
            if type(idx) is int and amount is not None:
                result[idx]=dict(mint=row.get('mint'),owner=row.get('owner'),amount=int(amount))
        return result
    pre,post=rows('preTokenBalances'),rows('postTokenBalances')
    out={}
    for idx in sorted(set(pre)|set(post)):
        a=pre.get(idx);b=post.get(idx)
        out[idx]=dict(
            mint=(b or a or {}).get('mint'),owner=(b or a or {}).get('owner'),
            pre=None if a is None else a['amount'],
            post=None if b is None else b['amount'],
            delta=None if a is None or b is None else b['amount']-a['amount'])
    return out


def run():
    # Historical proof uses the same canonical Alchemy Solana Mainnet route as all
    # other DLMM acquisition. Provider fallback is intentionally forbidden.
    url=alchemy_provider.rpc_url()
    # Exact-slot historical diagnostic only. Accounts-only blocks expose signatures
    # and all resolved account keys without heavyweight instructions/logs. This avoids
    # walking the pool's very high-volume signature history. Production/live census is
    # unchanged.
    rpc=HistoricalProbeRPC(url,limit=80)
    if rpc.call('getGenesisHash',priority=True)!=pump.MAINNET:
        raise Unavailable('host_probe_wrong_network')
    selected=[]
    block_telemetry=[]
    for slot in range(START_SLOT+1,END_SLOT+1):
        if slot>START_SLOT+1: rpc.sleep(1.0)
        block=rpc.call('getBlock',[slot,dict(commitment='finalized',encoding='json',
            transactionDetails='accounts',maxSupportedTransactionVersion=0,rewards=False)],True)
        if block is None:
            raise Unavailable('host_probe_missing_finalized_block')
        matches=0
        for transaction_index,row in enumerate(block.get('transactions') or []):
            tx=row.get('transaction') or {}
            keys=[]
            for item in tx.get('accountKeys') or []:
                key=item.get('pubkey') if isinstance(item,dict) else item
                if isinstance(key,str): keys.append(key)
            if POOL not in keys or (row.get('meta') or {}).get('err'):
                continue
            signatures=tx.get('signatures') or []
            if not signatures or not isinstance(signatures[0],str):
                raise Unavailable('host_probe_block_signature_shape')
            selected.append(dict(signature=signatures[0],slot=slot,
                                 transactionIndex=transaction_index,err=None,
                                 confirmationStatus='finalized'))
            matches+=1
        block_telemetry.append(dict(slot=slot,matching_successful_transactions=matches,
                                    transaction_rows=len(block.get('transactions') or [])))
    if len(selected)!=2:
        OUT.write_text(json.dumps(dict(kind='dlmm_jup_host_fee_probe_partial',
            pool=POOL,start_slot=START_SLOT,end_slot=END_SLOT,
            block_scan=block_telemetry,
            selected=[dict(signature=s.get('signature'),slot=s.get('slot'),
                           transactionIndex=s.get('transactionIndex')) for s in selected],
            rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,
            rpc_failures=rpc.failures,rpc_retries=rpc.retries),indent=2,sort_keys=True)+'\\n')
        raise Unavailable('host_probe_expected_exact_two_transactions')
    telemetry=dict(method='finalized_getBlock_accounts_exact_slots',
                   slots_scanned=END_SLOT-START_SLOT,blocks=block_telemetry)
    params=[[s['signature'],dict(encoding='json',commitment='finalized',
                                maxSupportedTransactionVersion=0)] for s in selected]
    txs=rpc.call_many('getTransaction',params,True,batch_size=2)
    evidence=[]
    for sig,tx in zip(selected,txs):
        if not tx or not tx.get('meta') or tx['meta'].get('err'):
            raise Unavailable('host_probe_missing_transaction')
        meta=tx['meta'];message=tx['transaction']['message'];keys=_keys(meta,message)
        balances=_token_balances(meta);calls=[];events=[]
        current=None
        for outer,inner,ix in _ordered_instructions(meta,message):
            if keys[ix['programIdIndex']]!=dlmm.PROGRAM: continue
            raw=_un58_data(ix['data'])
            if raw[:8] in EXACT_IN:
                accounts=ix.get('accounts') or []
                if not accounts or keys[accounts[0]]!=POOL: current=None;continue
                resolved=[keys[i] for i in accounts]
                current=dict(
                    instruction=EXACT_IN_NAME[raw[:8]],outer=outer,inner=inner,
                    account_count=len(accounts),accounts=resolved,
                    host_fee_account=(resolved[9] if len(resolved)>9 else None),
                    reserve_x=(resolved[2] if len(resolved)>2 else None),
                    reserve_y=(resolved[3] if len(resolved)>3 else None),
                    user_token_in=(resolved[4] if len(resolved)>4 else None),
                    user_token_out=(resolved[5] if len(resolved)>5 else None),
                    token_x_mint=(resolved[6] if len(resolved)>6 else None),
                    token_y_mint=(resolved[7] if len(resolved)>7 else None),
                )
                calls.append(current)
            elif raw[:8]==EVENT_CPI and raw[8:16] in (SWAP,SWAP2):
                event=_event(raw[8:],POOL)
                if event is not None:
                    events.append(event)
                    if current is not None:
                        current.setdefault('events',[]).append(event)
        for call in calls:
            ev=(call.get('events') or [None])[0]
            if not ev: continue
            input_is_x=bool(ev['swap_for_y'])
            reserve=call['reserve_x'] if input_is_x else call['reserve_y']
            input_mint=call['token_x_mint'] if input_is_x else call['token_y_mint']
            host=call['host_fee_account']
            def key_index(address):
                try:return keys.index(address)
                except ValueError:return None
            ri,hi,ui=key_index(reserve),key_index(host),key_index(call['user_token_in'])
            host_amt=int(ev.get('host_fee') or 0);protocol=int(ev.get('protocol_fee') or 0)
            call['input_mint']=input_mint
            call['reserve_input_index']=ri
            call['host_fee_index']=hi
            call['user_input_index']=ui
            call['reserve_input_balance']=balances.get(ri)
            call['host_fee_balance']=balances.get(hi)
            call['user_input_balance']=balances.get(ui)
            call['host_matches_total_protocol_floor_20pct']=(host_amt==protocol*HOST_FEE_BPS//10000)
            call['host_matches_protocol_plus_host_floor_20pct']=(host_amt==(protocol+host_amt)*HOST_FEE_BPS//10000)
            if hi is not None and balances.get(hi):
                call['host_token_matches_input']=balances[hi]['mint']==input_mint
                call['host_balance_delta_matches_event']=balances[hi]['delta']==host_amt
            if ri is not None and balances.get(ri):
                call['reserve_input_delta']=balances[ri]['delta']
                call['reserve_delta_matches_amount_minus_host']=balances[ri]['delta']==ev['amount_in']-host_amt
        evidence.append(dict(signature=sig['signature'],slot=sig['slot'],
                             transactionIndex=sig.get('transactionIndex'),blockTime=tx.get('blockTime'),
                             calls=calls,events=events,token_balances=balances))
    report=dict(kind='dlmm_jup_host_fee_probe_v1',allocation_authority=False,
                pool=POOL,start_slot=START_SLOT,end_slot=END_SLOT,
                signature_census=telemetry,transactions=evidence,
                rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,
                rpc_failures=rpc.failures,rpc_retries=rpc.retries,
                provider_failure_kinds=rpc.failure_kinds)
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(transactions=len(evidence),rpc_calls=rpc.calls,
                          rpc_failures=rpc.failures,
                          host_events=sum(1 for t in evidence for e in t['events'] if e.get('host_fee'))),
                     sort_keys=True))
    return report

if __name__=='__main__': run()
