"""Frozen continuation-v1 translation for Robinhood Chain / Pons.

This is not a new strategy.  Every dimensionless continuation-v1 gate is copied
unchanged from the canonical Solana policy.  Only the two SOL-denominated ENTRY
gates are translated into Robinhood's native ETH using one frozen USD-equivalence
snapshot captured before the natural sample.

Translation snapshot (2026-09-18):
  SOL/USD = 112.58
  ETH/USD = 2619.71
  10 SOL -> 0.429742223375869849 ETH
   1 SOL -> 0.042974222337586985 ETH

The translation is frozen for this experiment; sample results cannot alter it.
"""
from dataclasses import asdict
from fractions import Fraction

from . import BoundaryError
from .pons_natural_observation import RESEARCH_RECIPIENT

POLICY="continuation-v1-robinhood"
POLICY_HASH="f363c234daa549365ca00ee5b33247deb1c591a1084b991263233ba9f3870e36"
TRANSLATION_SNAPSHOT=dict(
    observed_date="2026-09-18",
    price_source="CoinGecko spot snapshot captured before sample",
    sol_usd="112.58",
    eth_usd="2619.71",
    semantic="USD-equivalent translation of only canonical SOL-denominated entry gates",
)
THRESHOLDS=dict(
    max_concentration_bps=3500,
    min_real_quote_wei=429742223375869849,
    max_evidence_events=100,
    min_independent_groups=3,
    min_independent_net_buy_wei=42974222337586985,
    max_price_extension_bps=12000,
    max_roundtrip_loss_bps=500,
)
# Solana continuation-v1 sizes one position at initial/20.  Its paper portfolio is
# fixed at $500, so the reference Robinhood sizing for cost measurement is $25,
# translated once at the same ETH snapshot. This is sizing, not a qualification gate.
REFERENCE_ENTRY_WEI=9543041023624753
EXIT_POLICY=dict(
    take_profit_bps=1500,
    risk_bps=-1000,
    timeout_seconds=900,
    delayed_execution_seconds=2,
    liquidity_behavior="adapter_fail_closed_full_position_executable_exit",
)
SIGNAL_WINDOW=60
ZERO="0x0000000000000000000000000000000000000000"


def ceildiv(a,b):
    if b<=0:
        raise BoundaryError("invalid_policy_denominator")
    return -(-a//b)


def normalized_trade(decoded,*,identity,event_at):
    """Convert an authenticated/finalized Pons curve event to policy evidence."""
    name=decoded["name"];args=decoded["args"]
    if name=="CurveBuy":
        quote=int(args["quoteIn"]);tokens=int(args["tokensOut"])
        actor=args["buyer"].lower();recipient=args["recipient"].lower()
        side="buy";group=recipient
    elif name=="CurveSell":
        quote=int(args["quoteOut"]);tokens=int(args["tokensIn"])
        actor=args["seller"].lower();recipient=args["recipient"].lower()
        side="sell";group=actor
    else:
        raise BoundaryError("unsupported_continuation_event")
    if quote<=0 or tokens<=0:
        raise BoundaryError("invalid_trade_amount")
    return dict(
        identity=identity,side=side,quote=quote,tokens=tokens,event_at=int(event_at),
        actor=actor,recipient=recipient,group=group,
    )


def qualification_vector(*,state,record,nomination,events,concentration_bps,
                         concentration_meta,current_snipe_bps,roundtrip_gas_wei,
                         asof,asof_block,evidence_available_at=None):
    """Evaluate the frozen policy without order/allocation authority."""
    vector=dict(
        policy=POLICY,authority="research_only",qualification_authority=False,
        thresholds=dict(THRESHOLDS),exit_policy=dict(EXIT_POLICY),
        translation_snapshot=dict(TRANSLATION_SNAPSHOT),
        reference_entry_wei=REFERENCE_ENTRY_WEI,
        asof=int(asof),asof_block=int(asof_block),
        evidence_available_at=int(asof if evidence_available_at is None else evidence_available_at),
        decision_state_age_seconds=int((asof if evidence_available_at is None else evidence_available_at)-state.timestamp),
        decision_state_fresh=bool(int((asof if evidence_available_at is None else evidence_available_at)-state.timestamp)<=5),
        all_rejections=[],current_threshold_pass=False,
        pair_token=record.get("pairToken"),curve=record.get("curve"),
        token=record.get("token"),creator=record.get("deployer"),
        creator_fee_recipient=record.get("creatorFeeRecipient"),
        concentration_bps=concentration_bps,concentration_meta=concentration_meta,
        evidence_event_count=len(events),real_quote_wei=int(state.real_quote),
        independent_buyer_groups=None,independent_net_buy_wei=None,
        price_extension_bps=None,roundtrip_loss_bps=None,
        roundtrip_loss_wei=None,roundtrip_gas_wei=int(roundtrip_gas_wei),
    )
    reject=vector["all_rejections"]
    def add(reason):
        if reason not in reject:
            reject.append(reason)

    if not vector["decision_state_fresh"] or vector["decision_state_age_seconds"]<0:
        add("stale_state_after_evidence")
    if record.get("pairToken","").lower()!=ZERO:
        add("unsupported_pair_quote")
    if state.graduated:
        add("graduated_requires_v4")
    if int(state.real_quote)<THRESHOLDS["min_real_quote_wei"]:
        add("exit_liquidity")
    if len(events)>THRESHOLDS["max_evidence_events"]:
        add("evidence_capacity")
    if concentration_bps is None:
        add("missing_concentration")
    elif int(concentration_bps)>THRESHOLDS["max_concentration_bps"]:
        add("concentration")

    if nomination.get("side")!="buy" or int(nomination.get("quote",0))<=0 or int(nomination.get("tokens",0))<=0:
        add("invalid_nomination")
    if not int(nomination.get("event_at",0))<=asof or asof-int(nomination.get("event_at",0))>SIGNAL_WINDOW:
        add("stale_signal")

    # Preserve Solana semantics: the nominating buyer/group and creator-related
    # addresses do not count as independent confirming demand.
    excluded={
        str(nomination.get("actor","")).lower(),
        str(nomination.get("group","")).lower(),
        str(record.get("deployer","")).lower(),
        str(record.get("creatorFeeRecipient","")).lower(),
        ZERO,
    }
    groups=set();net=0;seen={}
    valid=True
    for event in events:
        try:
            ident=event["identity"]
            body=(event["side"],int(event["quote"]),int(event["tokens"]),
                  int(event["event_at"]),event["actor"],event["recipient"],event["group"])
            if ident in seen:
                if seen[ident]!=body:
                    add("conflicting_market_event");valid=False;break
                continue
            seen[ident]=body
            if not asof-SIGNAL_WINDOW<=int(event["event_at"])<=asof:
                add("invalid_market_window");valid=False;break
            if int(event["quote"])<=0 or int(event["tokens"])<=0:
                add("invalid_trade_amount");valid=False;break
            group=str(event["group"]).lower()
            if group in excluded or str(event["actor"]).lower() in excluded:
                continue
            net+=int(event["quote"])*(1 if event["side"]=="buy" else -1)
            if event["side"]=="buy":
                groups.add(group)
        except (KeyError,TypeError,ValueError):
            add("invalid_market_window");valid=False;break
    if valid:
        vector["independent_buyer_groups"]=len(groups)
        vector["independent_net_buy_wei"]=net
        if len(groups)<THRESHOLDS["min_independent_groups"] or net<THRESHOLDS["min_independent_net_buy_wei"]:
            add("independent_demand")

    try:
        vector["price_extension_bps"]=ceildiv(
            int(state.quote_reserve)*int(nomination["tokens"])*10_000,
            int(state.token_reserve)*int(nomination["quote"]),
        )
        if vector["price_extension_bps"]>THRESHOLDS["max_price_extension_bps"]:
            add("extended_price")
    except (KeyError,TypeError,ValueError,ZeroDivisionError,BoundaryError):
        add("extended_price")

    try:
        buy=state.buy_with_snipe(REFERENCE_ENTRY_WEI,int(current_snipe_bps))
        if buy["refund"] or buy["ready_to_graduate"]:
            raise BoundaryError("entry_graduation_boundary")
        sell=state.sell(buy["tokens_out"])
        loss=int(buy["spent"])+int(roundtrip_gas_wei)-int(sell["quote_out"])
        vector["roundtrip_loss_wei"]=loss
        vector["roundtrip_loss_bps"]=ceildiv(max(0,loss)*10_000,int(buy["spent"]))
        if loss*10_000>int(buy["spent"])*THRESHOLDS["max_roundtrip_loss_bps"]:
            add("roundtrip_cost")
    except (BoundaryError,KeyError,TypeError,ValueError,ZeroDivisionError):
        add("roundtrip_cost_unavailable")

    vector["margins"]=dict(
        concentration_bps=(None if concentration_bps is None else
            THRESHOLDS["max_concentration_bps"]-int(concentration_bps)),
        real_quote_wei=int(state.real_quote)-THRESHOLDS["min_real_quote_wei"],
        evidence_events=THRESHOLDS["max_evidence_events"]-len(events),
        independent_groups=(None if vector["independent_buyer_groups"] is None else
            vector["independent_buyer_groups"]-THRESHOLDS["min_independent_groups"]),
        net_buy_wei=(None if vector["independent_net_buy_wei"] is None else
            vector["independent_net_buy_wei"]-THRESHOLDS["min_independent_net_buy_wei"]),
        price_extension_bps=(None if vector["price_extension_bps"] is None else
            THRESHOLDS["max_price_extension_bps"]-vector["price_extension_bps"]),
        roundtrip_loss_bps=(None if vector["roundtrip_loss_bps"] is None else
            THRESHOLDS["max_roundtrip_loss_bps"]-vector["roundtrip_loss_bps"]),
    )
    vector["complete"]=all(vector[k] is not None for k in (
        "concentration_bps","independent_buyer_groups","independent_net_buy_wei",
        "price_extension_bps","roundtrip_loss_bps",
    ))
    vector["current_threshold_pass"]=bool(vector["complete"] and not reject)
    vector["qualification"]="qualified" if vector["current_threshold_pass"] else (
        reject[0] if reject else "incomplete")
    return vector
