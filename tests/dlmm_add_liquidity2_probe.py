"""Read-only probe for the exact MET-SOL addLiquidity2 interval from run 35383813365."""
from __future__ import annotations
import json, struct, time, urllib.request
from pathlib import Path

from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import _keys,_ordered_instructions,_un58_data,EVENT_CPI
from tests import dlmm_alchemy_provider as alchemy_provider
from tests.dlmm_boundary_acquisition import _fetch_transaction_bodies

POOL="FzA8Fji7xdr9jfN7Y2YCUGLYwBzqP1eicKA4dX4m8BJg"
START_SLOT=448176914
END_SLOT=448176933
ADD_LIQUIDITY2=bytes.fromhex("e4a24e1c46db7473")
ADD_LIQUIDITY_EVT=bytes.fromhex("1f5e7d5ae3343dba")
OUT=Path("dlmm-add-liquidity2-probe.json")

def _parse_add2(raw):
    if raw[:8]!=ADD_LIQUIDITY2 or len(raw)<28:
        return None
    amount_x,amount_y,n=struct.unpack_from("<QQI",raw,8)
    off=28
    rows=[]
    if n>256 or len(raw)<off+n*8:
        return dict(error="add_liquidity2_payload_shape",amount_x=amount_x,amount_y=amount_y,count=n)
    for _ in range(n):
        bid,dx,dy=struct.unpack_from("<iHH",raw,off);off+=8
        rows.append(dict(bin_id=bid,distribution_x=dx,distribution_y=dy))
    return dict(amount_x=amount_x,amount_y=amount_y,count=n,distribution=rows,trailing_hex=raw[off:].hex())

def _parse_add_event(raw):
    if raw[:8]!=ADD_LIQUIDITY_EVT or len(raw)!=124:
        return None
    return dict(
        pool=pump.b58(raw[8:40]),
        sender=pump.b58(raw[40:72]),
        position=pump.b58(raw[72:104]),
        amount_x=int.from_bytes(raw[104:112],"little"),
        amount_y=int.from_bytes(raw[112:120],"little"),
        active_bin_id=struct.unpack_from("<i",raw,120)[0],
    )

def _token_transfer(ix,keys):
    pi=ix.get("programIdIndex")
    if type(pi) is not int or not 0<=pi<len(keys) or keys[pi]!=pump.TOKEN_PROGRAM:
        return None
    raw=_un58_data(ix.get("data") or ""); accounts=ix.get("accounts") or []
    if len(raw)==9 and raw[0]==3 and len(accounts)>=2:
        return dict(kind="transfer",source=keys[accounts[0]],destination=keys[accounts[1]],
                    amount=int.from_bytes(raw[1:9],"little"))
    if len(raw)==10 and raw[0]==12 and len(accounts)>=3:
        return dict(kind="transfer_checked",source=keys[accounts[0]],mint=keys[accounts[1]],
                    destination=keys[accounts[2]],amount=int.from_bytes(raw[1:9],"little"),
                    decimals=raw[9])
    return None

def _balances(meta):
    out={}
    for side in ("preTokenBalances","postTokenBalances"):
        out[side]=[dict(accountIndex=r.get("accountIndex"),mint=r.get("mint"),owner=r.get("owner"),
                        amount=(r.get("uiTokenAmount") or {}).get("amount")) for r in (meta.get(side) or [])]
    return out

def _direct_rpc(url,method,params):
    body=json.dumps(dict(jsonrpc="2.0",id=1,method=method,params=params)).encode()
    req=urllib.request.Request(url,data=body,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=20) as response:
        payload=json.loads(response.read())
    if payload.get("error"):
        raise RuntimeError(f"add_liquidity2_probe_rpc:{method}:{payload['error'].get('code')}")
    return payload.get("result")

def run():
    pacer=alchemy_provider.AlchemyPacer()
    url=alchemy_provider.rpc_url()
    rpc=alchemy_provider.new_rpc(limit=120,pacer=pacer)
    if rpc.call("getGenesisHash",priority=True)!=pump.MAINNET:
        raise RuntimeError("add_liquidity2_probe_wrong_network")
    telemetry=dict(block_scan_slots=[])
    relevant=[]
    for slot in range(START_SLOT+1,END_SLOT+1):
        if telemetry["block_scan_slots"]:
            time.sleep(1.0)
        block=_direct_rpc(url,"getBlock",[slot,dict(
            commitment="finalized",encoding="json",
            transactionDetails="accounts",rewards=False,
            maxSupportedTransactionVersion=0)])
        telemetry["block_scan_slots"].append(slot)
        if not block:
            continue
        for row in block.get("transactions") or []:
            tx=row.get("transaction") or {}
            message=tx.get("message") or {}
            keys=message.get("accountKeys") or []
            if POOL not in keys:
                continue
            sigs=tx.get("signatures") or []
            if not sigs:
                raise RuntimeError("add_liquidity2_probe_missing_signature")
            relevant.append(dict(
                signature=sigs[0],slot=slot,transactionIndex=len(relevant),
                err=None,confirmationStatus="finalized"))
    if len(relevant)!=2:
        raise RuntimeError(f"add_liquidity2_probe_expected_two:{len(relevant)}")
    txs=_fetch_transaction_bodies(rpc,relevant,telemetry)
    rows=[]
    for sig,tx in zip(relevant,txs):
        meta=tx["meta"]; msg=tx["transaction"]["message"]; keys=_keys(meta,msg)
        items=[]
        for outer,inner,ix in _ordered_instructions(meta,msg):
            pi=ix.get("programIdIndex")
            program=keys[pi] if type(pi) is int and 0<=pi<len(keys) else None
            raw=_un58_data(ix.get("data") or "")
            item=dict(order=[outer,inner],program=program,data_hex=raw.hex(),
                      accounts=[keys[i] if type(i) is int and 0<=i<len(keys) else None
                                for i in (ix.get("accounts") or [])])
            if program==dlmm.PROGRAM:
                item["discriminator"]=raw[:8].hex() if len(raw)>=8 else raw.hex()
                parsed=_parse_add2(raw)
                if parsed is not None:item["add_liquidity2"]=parsed
                if raw[:8]==EVENT_CPI and raw[8:16]==ADD_LIQUIDITY_EVT:
                    item["add_liquidity_event"]=_parse_add_event(raw[8:])
            transfer=_token_transfer(ix,keys)
            if transfer is not None:item["token_transfer"]=transfer
            items.append(item)
        rows.append(dict(signature=sig["signature"],slot=sig["slot"],
                         transactionIndex=sig.get("transactionIndex"),blockTime=tx.get("blockTime"),
                         account_keys=keys,token_balances=_balances(meta),instructions=items))
    report=dict(kind="dlmm_add_liquidity2_probe_v1",allocation_authority=False,pool=POOL,
                start_slot=START_SLOT,end_slot=END_SLOT,census=telemetry,transactions=rows,
                rpc_calls=rpc.calls,rpc_http_requests=rpc.http_requests,rpc_failures=rpc.failures,
                rpc_retries=rpc.retries,pacer=pacer.telemetry())
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(transactions=len(rows),rpc_calls=rpc.calls,rpc_failures=rpc.failures),sort_keys=True))
    return report

if __name__=="__main__":run()
