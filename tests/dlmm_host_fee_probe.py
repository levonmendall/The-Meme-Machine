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
    url=os.environ.get('MM_SOLANA_READ_RPC_URL','').strip()
    if not url: raise SystemExit('MM_SOLANA_READ_RPC_URL missing')
    rpc=PoolScanRPC(url,limit=80)
    if rpc.call('getGenesisHash',priority=True)!=pump.MAINNET:
        raise Unavailable('host_probe_wrong_network')
    # Historical diagnostic only: use Solana's 1000-signature page size so this
    # already-known interval can be recovered cheaply without changing the live
    # verifier's 16x64 census. Four pages / 4000 rows is a hard probe-only cap.
    telemetry=dict(pages=[],rows=0)
    selected=[];before=None;boundary_seen=False;seen=set()
    for page_index in range(4):
        cfg=dict(limit=1000,commitment='finalized')
        if before is not None:
            cfg['before']=before
            rpc.sleep(1.0)
        page=rpc.call('getSignaturesForAddress',[POOL,cfg],True)
        if not isinstance(page,list) or len(page)>1000:
            raise Unavailable('host_probe_signature_shape')
        ids=[x.get('signature') for x in page]
        if any(not isinstance(x,str) or not x for x in ids) or seen.intersection(ids):
            raise Unavailable('host_probe_signature_duplicate')
        seen.update(ids);telemetry['rows']+=len(page)
        telemetry['pages'].append(dict(page=page_index+1,count=len(page),
            newest_slot=None if not page else page[0].get('slot'),
            oldest_slot=None if not page else page[-1].get('slot')))
        selected.extend(s for s in page if START_SLOT<s.get('slot',-1)<=END_SLOT and not s.get('err'))
        if any(isinstance(s.get('slot'),int) and s['slot']<=START_SLOT for s in page):
            boundary_seen=True;break
        if not page or len(page)<1000:break
        before=page[-1]['signature']
    if not boundary_seen:
        raise Unavailable('host_probe_historical_page_bound')
    if len(selected)!=2:
        raise Unavailable('host_probe_expected_exact_two_transactions')
    proof=selected
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
