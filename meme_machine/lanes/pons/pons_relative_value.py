"""Independent Pons quote-asset relative-value research.

Pons launches can be quoted in non-native assets.  This lane measures the launch
token directly against its quote asset from the authenticated curve reserves, so a
rise in the quote asset itself is not misclassified as token alpha.

Allocation remains disabled because Meme Machine does not yet have a separately
certified quote-asset capital/settlement adapter for arbitrary ERC-20/RWA pairs.
"""
from dataclasses import asdict
import time

from . import BoundaryError, CHAIN_ID
from .abi import calldata
from .evidence import Stamp
from .pons import CurveState, authenticate_curve, factory_record, raw_event, curve_abi
from .pons_natural_observation import RESEARCH_RECIPIENT, _one_word, _two_uints
from .pons_selective_acquisition import (
    _authenticate_window, _header_search, _rpc,
)
from .pons_selective_continuation import demand_metrics, curve_progress_bps
from .identity import load

STRATEGY="pons-quote-relative-value-v1"
ZERO="0x0000000000000000000000000000000000000000"
RESEARCH_THRESHOLDS=dict(
    min_curve_progress_bps=5500,
    max_curve_progress_bps=9200,
    min_relative_return_30s_bps=500,
    min_independent_groups=5,
    min_new_independent_groups_15s=3,
    min_buy_sell_ratio_bps=15_000,
)


def reserve_relative_return_bps(start_quote,start_token,now_quote,now_token):
    values=[int(x) for x in (start_quote,start_token,now_quote,now_token)]
    if min(values)<=0:
        raise BoundaryError("invalid_relative_reserves")
    # (Q1/T1) / (Q0/T0) - 1, measured in the actual quote asset.
    return values[2]*values[1]*10_000//(values[3]*values[0])-10_000


def _authenticate_any_pair(rpc,event):
    block=int(event["blockNumber"],16);block_hex=hex(block)
    curve=event["address"].lower();tx=event["transactionHash"]
    calls=[
        ("eth_chainId",[]),
        ("eth_getBlockByNumber",[block_hex,False]),
        ("eth_getTransactionReceipt",[tx]),
        ("eth_call",[dict(to=curve,data=calldata("token()")),block_hex]),
        ("eth_getCode",[curve,block_hex]),
        ("eth_call",[dict(to=curve,data=calldata("getReserves()")),block_hex]),
        ("eth_call",[dict(to=curve,data=calldata("realQuoteReserve()")),block_hex]),
        ("eth_call",[dict(to=curve,data=calldata("reservedTokens()")),block_hex]),
        ("eth_call",[dict(to=curve,data=calldata("graduated()")),block_hex]),
        ("eth_call",[dict(
            to=curve,data=calldata("currentSnipeTaxBps(address)",RESEARCH_RECIPIENT)
        ),block_hex]),
    ]
    values=rpc.batch(calls,scope="pons_relative")
    chain,header,receipt,token_raw,code,reserves_raw,real_raw,reserved_raw,graduated_raw,snipe_raw=values
    if int(chain,16)!=CHAIN_ID:
        raise BoundaryError("wrong_chain")
    if (
        header["hash"]!=event["blockHash"]
        or receipt["transactionHash"]!=tx
        or receipt["blockHash"]!=event["blockHash"]
    ):
        raise BoundaryError("relative_candidate_identity")
    observed=int(time.time());event_at=int(header["timestamp"],16)
    if observed-event_at>5:
        raise BoundaryError("stale_state")
    decoded=raw_event(
        curve_abi(),event,address=curve,receipt=receipt,header=header,
        observed_at=observed,confirmation="confirmed",
    )
    token=_one_word(token_raw,"address")
    factory=load("pons_v2_factory")["address"].lower()
    factory_raw=rpc.call(
        "eth_call",[dict(
            to=factory,data=calldata("getLaunchedToken(address)",token)
        ),block_hex],scope="pons_relative",
    )
    record=factory_record(factory_raw,"pons_v2_factory")
    auth=authenticate_curve(curve,code,factory_record=record)
    qr,tr=_two_uints(reserves_raw)
    state=CurveState(
        quote_reserve=qr,token_reserve=tr,real_quote=_one_word(real_raw),
        reserved_tokens=_one_word(reserved_raw),
        fee_bps=int(auth["immutables"]["feeBps"]),
        creator_tax_bps=int(auth["immutables"]["creatorTaxBps"]),
        graduated=bool(_one_word(graduated_raw,"bool")),
        launched_at=event_at,snipe_start_bps=0,snipe_seconds=1,timestamp=event_at,
    )
    return dict(
        curve=curve,token=token,block=block,header=header,receipt=receipt,
        decoded_event=decoded,record=record,auth=auth,state=state,
        current_snipe_bps=_one_word(snipe_raw),
        stamp=Stamp(CHAIN_ID,block,header["hash"],event_at,observed,"confirmed","natural"),
    )


def relative_value_vector(*,candidate,start_reserves,market_events,asof):
    pair=candidate["record"]["pairToken"].lower()
    if pair==ZERO:
        raise BoundaryError("relative_value_requires_non_native_quote")
    start_quote,start_token=start_reserves
    relative=reserve_relative_return_bps(
        start_quote,start_token,
        candidate["state"].quote_reserve,candidate["state"].token_reserve,
    )
    creators=(
        candidate["record"].get("deployer"),
        candidate["record"].get("creatorFeeRecipient"),
    )
    demand=demand_metrics(market_events,asof=int(asof),creator_groups=creators)
    progress=curve_progress_bps(
        candidate["state"].real_quote,candidate["record"]["graduationThreshold"]
    )
    rejects=[]
    if not RESEARCH_THRESHOLDS["min_curve_progress_bps"]<=progress<=RESEARCH_THRESHOLDS["max_curve_progress_bps"]:
        rejects.append("curve_progress")
    if relative<RESEARCH_THRESHOLDS["min_relative_return_30s_bps"]:
        rejects.append("relative_strength")
    if demand["independent_groups"]<RESEARCH_THRESHOLDS["min_independent_groups"]:
        rejects.append("independent_breadth")
    if demand["new_independent_groups_15s"]<RESEARCH_THRESHOLDS["min_new_independent_groups_15s"]:
        rejects.append("buyer_growth")
    if demand["buy_sell_ratio_bps"]<RESEARCH_THRESHOLDS["min_buy_sell_ratio_bps"]:
        rejects.append("buy_sell_flow")
    return dict(
        strategy=STRATEGY,research_only=True,allocation_authority=False,
        pair_token=pair,progress_bps=progress,
        relative_return_30s_bps=relative,demand=demand,
        thresholds=dict(RESEARCH_THRESHOLDS),
        candidate=not rejects,all_rejections=rejects,
    )


def evaluate_relative_candidate(endpoint,event,tape):
    rpc=_rpc(endpoint)
    candidate=_authenticate_any_pair(rpc,event)
    if candidate["record"]["pairToken"].lower()==ZERO:
        raise BoundaryError("relative_value_requires_non_native_quote")
    current_block=candidate["block"];current_at=candidate["stamp"].event_at
    launched_raw=rpc.call(
        "eth_call",[dict(
            to=candidate["curve"],data=calldata("launchedAt()")
        ),hex(current_block)],scope="pons_relative",
    )
    launch_at=_one_word(launched_raw)
    cache={current_block:candidate["header"]}
    start_header=_header_search(
        rpc,current_block,current_at,max(launch_at,current_at-30),cache
    )
    start_block=int(start_header["number"],16)
    reserves_raw=rpc.call(
        "eth_call",[dict(
            to=candidate["curve"],data=calldata("getReserves()")
        ),hex(start_block)],scope="pons_relative",
    )
    start_reserves=_two_uints(reserves_raw)
    market,sessions=_authenticate_window(endpoint,candidate,list(tape),seconds=60)
    vector=relative_value_vector(
        candidate=candidate,start_reserves=start_reserves,
        market_events=market,asof=current_at,
    )
    return dict(
        strategy=STRATEGY,token=candidate["token"],curve=candidate["curve"],
        source_transaction=event["transactionHash"],source_block=current_block,
        start_block=start_block,start_at=int(start_header["timestamp"],16),
        current_at=current_at,start_reserves=start_reserves,
        current_reserves=(
            candidate["state"].quote_reserve,candidate["state"].token_reserve
        ),
        vector=vector,provider_sessions=[rpc.telemetry()]+sessions,
        candidate_state=asdict(candidate["state"]),
    )
