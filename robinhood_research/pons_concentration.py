"""Exact top-five ERC-20 holder concentration for Pons research vectors.

Solana continuation-v1 uses top-five token-account concentration / total supply,
excluding protocol curve custody from the numerator.  This module preserves that
semantic on Robinhood: enumerate all ERC-20 transfers through the already-authorized
Alchemy endpoint, reconstruct balances at the point-in-time block, reconcile them to
ERC-20 totalSupply, exclude the Pons curve balance from the numerator, and verify the
top five plus curve against historical balanceOf calls.

If enumeration is unavailable, paginated beyond the bound, or does not reconcile,
concentration is unavailable and qualification fails closed.
"""
from . import BoundaryError
from .abi import calldata, words, scalar

ZERO="0x0000000000000000000000000000000000000000"
DEAD="0x000000000000000000000000000000000000dead"
MAX_PAGES=4
PAGE_SIZE="0x3e8"


def _uint(raw):
    row=words(raw)
    if len(row)!=1:
        raise BoundaryError("erc20_call_shape")
    return scalar("uint256",row[0])


def _balance(rpc,token,holder,block,scope):
    raw=rpc.call(
        "eth_call",
        [dict(to=token,data=calldata("balanceOf(address)",holder)),hex(block)],
        scope=scope,
    )
    return _uint(raw)


def top5_concentration_bps(rpc,*,token,curve,block,scope="pons_sample"):
    token=token.lower();curve=curve.lower()
    total=_uint(rpc.call(
        "eth_call",[dict(to=token,data=calldata("totalSupply()")),hex(block)],
        scope=scope,
    ))
    if total<=0:
        raise BoundaryError("invalid_token_supply")

    balances={}
    page_key=None
    transfer_count=0
    for page in range(MAX_PAGES):
        params=dict(
            fromBlock="0x0",toBlock=hex(block),contractAddresses=[token],
            category=["erc20"],excludeZeroValue=False,maxCount=PAGE_SIZE,
        )
        if page_key:
            params["pageKey"]=page_key
        result=rpc.call("alchemy_getAssetTransfers",[params],scope=scope)
        if not isinstance(result,dict) or not isinstance(result.get("transfers"),list):
            raise BoundaryError("transfer_enumeration_shape")
        rows=result["transfers"]
        transfer_count+=len(rows)
        for row in rows:
            raw=row.get("rawContract") or {}
            contract=(raw.get("address") or token).lower()
            if contract!=token:
                raise BoundaryError("transfer_contract_disagreement")
            value=raw.get("value")
            if not isinstance(value,str) or not value.startswith("0x"):
                raise BoundaryError("transfer_raw_value_missing")
            amount=int(value,16)
            if amount<0:
                raise BoundaryError("negative_transfer")
            sender=(row.get("from") or ZERO).lower()
            recipient=(row.get("to") or ZERO).lower()
            if sender!=ZERO:
                balances[sender]=balances.get(sender,0)-amount
            if recipient!=ZERO:
                balances[recipient]=balances.get(recipient,0)+amount
        page_key=result.get("pageKey") or None
        if not page_key:
            break
    if page_key:
        raise BoundaryError("concentration_transfer_capacity")
    if transfer_count<=0:
        raise BoundaryError("concentration_no_transfers")

    balances={a:v for a,v in balances.items() if v}
    if any(v<0 for v in balances.values()):
        raise BoundaryError("concentration_negative_balance")
    if sum(balances.values())!=total:
        raise BoundaryError("concentration_supply_disagreement")

    eligible=[(v,a) for a,v in balances.items()
              if a not in (curve,ZERO,DEAD) and v>0]
    eligible.sort(reverse=True)
    top=eligible[:5]

    # Verify the curve custody and top-five balances in one bounded transport
    # roundtrip. Logical request/accounting budgets are unchanged.
    holders=[curve]+[holder for _,holder in top]
    calls=[
        ("eth_call",[dict(to=token,data=calldata("balanceOf(address)",holder)),hex(block)])
        for holder in holders
    ]
    raw_values=rpc.batch(calls,scope=scope)
    actuals=[_uint(raw) for raw in raw_values]
    curve_actual=actuals[0]
    if balances.get(curve,0)!=curve_actual:
        raise BoundaryError("concentration_curve_balance_disagreement")
    for (expected,holder),actual in zip(top,actuals[1:]):
        if actual!=expected:
            raise BoundaryError("concentration_holder_balance_disagreement")

    value=sum(v for v,_ in top)*10_000//total
    return value,dict(
        semantic="top5_token_balances_over_total_supply_excluding_curve_custody",
        block=block,total_supply=total,curve_balance=curve_actual,
        transfer_count=transfer_count,holders=len(eligible),
        top5=[dict(address=a,balance=v) for v,a in top],
        source="alchemy_getAssetTransfers_plus_historical_balanceOf_reconciliation",
        complete=True,
    )
