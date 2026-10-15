"""Local demand attention, never qualification, quotes, capital or exit authority.

Amounts stay in the market's native quote unit. Complete adjacent windows use
half-open time bounds; missing history is unavailable, never quiet. Survivor
aggregates live in its existing hashed candidate row and are advanced only by
new deduplicated authenticated events inside the existing append transaction.
"""
from collections import defaultdict
from copy import deepcopy
import logging
import os

VERSION='volume-quality-attention-v1'
MAX_SECONDS=3600
MAX_GROUP_CELLS=16384
MAX_UPDATE_EVENTS=65536
CURRENT_WINDOWS=(10,15,30,60)
SURVIVOR_WINDOWS=(60,300,1800)


def enabled():
    return os.environ.get('MM_VOLUME_QUALITY_ENABLED','0')=='1'


def unavailable(reason,*,at=0,asset=None):
    return dict(version=VERSION,classification='INSUFFICIENT_EVIDENCE',
        complete=False,reason=reason,asof=at,quote_asset=asset,rank=0,windows={})


def trade(row,*,cluster_map=None):
    """Only normalize existing flow schemas; no independent wallet inference."""
    at=row.get('at',row.get('event_at',row.get('market_time')))
    amount=row.get('quote',row.get('amount'))
    if type(at) is not int or type(amount) is not int or amount<=0:
        raise ValueError('volume_quality_trade_shape')
    wallet=row.get('wallet',row.get('actor'))
    group=row.get('group')
    if group is None:group=(cluster_map or {}).get(wallet,wallet)
    if not isinstance(group,str) or not group:raise ValueError('volume_quality_group_missing')
    buy=row.get('buy')
    if buy is None:buy=row.get('side')=='buy' if row.get('side') in ('buy','sell') else None
    if type(buy) is not bool:raise ValueError('volume_quality_side_missing')
    return at,amount,group,buy


def advance(previous,events,*,lower,through,complete,asset,authoritative):
    """The caller supplies only newly inserted events, with native continuity.

    A gap/reorganization invalidates the aggregate. Its original evidence stays
    in the host history. Restart reuses the same hashed aggregate; replayed IDs
    never reach this reducer a second time. Capacity failure is neutral attention.
    """
    if not authoritative or not complete:
        return dict(version=VERSION,asset=asset,lower=through,through=through,
                    complete=False,buckets={},reason='canonical_interval_incomplete')
    old=previous or {}
    if (old.get('version')!=VERSION or old.get('asset')!=asset
            or old.get('complete') is not True or lower!=old.get('through')):
        old=dict(version=VERSION,asset=asset,lower=lower,through=lower,
                 complete=True,buckets={})
    if type(lower) is not int or type(through) is not int or through<lower:
        raise ValueError('volume_quality_watermark')
    state=deepcopy(old);buckets=state['buckets'];count=0
    for event in events:
        count+=1
        if count>MAX_UPDATE_EVENTS:raise ValueError('volume_quality_update_bound')
        if event.get('authenticated') is not True:raise ValueError('volume_quality_event_authority')
        at,amount,group,buy=trade(event)
        if at>through:raise ValueError('volume_quality_future_event')
        if at<max(state['lower'],through-MAX_SECONDS):continue
        value=buckets.setdefault(str(at),{}).setdefault(group,[0,0,0])
        value[0 if buy else 1]+=amount;value[2]+=1
    state['buckets']={k:v for k,v in buckets.items() if int(k)>=through-MAX_SECONDS}
    if sum(map(len,state['buckets'].values()))>MAX_GROUP_CELLS:
        raise ValueError('volume_quality_aggregate_capacity')
    state.update(through=through,lower=max(state['lower'],through-MAX_SECONDS),complete=True)
    return state


def _window(state,lo,hi,excluded):
    buyers=defaultdict(int);buy=sell=trades=raw_buy=raw_sell=excluded_buy=0
    for timestamp,groups in state['buckets'].items():
        if not lo<=int(timestamp)<hi:continue
        for group,(b,s,n) in groups.items():
            raw_buy+=b;raw_sell+=s
            if group in excluded:excluded_buy+=b;continue
            buy+=b;sell+=s;trades+=n
            if b:buyers[group]+=b
    return dict(buy=buy,sell=sell,net=buy-sell,gross=buy+sell,
        raw_gross=raw_buy+raw_sell,raw_buy=raw_buy,raw_sell=raw_sell,
        trades=trades,buyers=dict(buyers),excluded_buy=excluded_buy,
        concentration_bps=0 if not buy else max(buyers.values())*10000//buy)


def signal(state,*,now,observed_at,windows=SURVIVOR_WINDOWS,excluded=(),
           maximum_age=5,market_warnings=(),progress=None):
    if not state or state.get('complete') is not True:return unavailable('canonical_interval_incomplete')
    at=state['through'];asset=state['asset']
    if not 0<=now-observed_at<=maximum_age or not 0<=now-at<=maximum_age:
        return unavailable('stale_observation',at=at,asset=asset)
    result=dict(version=VERSION,asof=at,observed_at=observed_at,expires_at=observed_at+maximum_age,
        quote_asset=asset,complete=True,windows={},market_warnings=list(market_warnings),
        progress_context=progress,rank=0)
    excluded=set(excluded);available=[]
    for seconds in windows:
        if state['lower']>at-2*seconds:
            result['windows'][str(seconds)]=dict(complete=False,reason='window_not_yet_observed');continue
        prior=_window(state,at-2*seconds,at-seconds,excluded)
        current=_window(state,at-seconds,at,excluded)
        recent=set(current['buyers']);previous=set(prior['buyers']);repeat=recent&previous
        repeat_quote=sum(current['buyers'][g] for g in repeat)
        net_change=current['net']-prior['net'];gross_change=current['raw_gross']-prior['raw_gross']
        breadth=len(recent)-len(previous)
        warnings=list(market_warnings)
        if current['excluded_buy']>current['buy']:warnings.append('related_flow_dominant')
        if current['concentration_bps']>5000:warnings.append('single_group_majority')
        if current['concentration_bps']>prior['concentration_bps'] and breadth<=0:
            warnings.append('concentration_increasing_without_breadth')
        if current['trades']>prior['trades'] and breadth<=0:warnings.append('activity_without_breadth_growth')
        if (net_change<0 or breadth<0 or market_warnings
                or current['sell']-prior['sell']>current['buy']-prior['buy']):
            classification='DEMAND_DETERIORATING'
        elif (net_change>0 and current['net']>0 and gross_change>0
                and (breadth>0 or repeat) and not any(w!='activity_without_breadth_growth' for w in warnings)):
            classification='QUALITY_ACCELERATING'
        elif gross_change>0:classification='VOLUME_ONLY_ACCELERATION'
        else:classification='STABLE_OR_QUIET'
        row=dict(complete=True,seconds=seconds,prior=prior,current=current,
            volume_change=gross_change,net_buy_change=net_change,buyer_growth=breadth,
            new_buying_groups=len(recent-previous),repeat_buying_groups=len(repeat),
            repeat_buy_share_bps=0 if not current['buy'] else repeat_quote*10000//current['buy'],
            classification=classification,warnings=warnings,
            # Exact ratios: numerator/denominator, not floating point or infinity.
            gross_rate=[current['raw_gross'],seconds],net_rate=[current['net'],seconds],
            gross_rate_change=[gross_change,seconds],net_rate_change=[net_change,seconds],
            net_per_trade=None if not current['trades'] else [current['net'],current['trades']],
            net_per_buyer=None if not recent else [current['net'],len(recent)],
            acceleration_bps=None if prior['raw_gross']==0 else gross_change*10000//prior['raw_gross'],
            prior_activity_zero=prior['raw_gross']==0)
        # Group IDs stay in existing evidence, not the signal's compact context.
        for period in (prior,current):period['independent_groups']=len(period.pop('buyers'))
        result['windows'][str(seconds)]=row;available.append(row)
    if not available:return unavailable('window_not_yet_observed',at=at,asset=asset)
    primary=available[0];result['classification']=primary['classification']
    # One classification rank, not several weighted versions of the same flow.
    result['rank']={'QUALITY_ACCELERATING':2,'STABLE_OR_QUIET':0,
                    'VOLUME_ONLY_ACCELERATION':0,'DEMAND_DETERIORATING':-1}[primary['classification']]
    return result


def from_events(events,*,lower,through,now,observed_at,asset,authoritative,
                cluster_map=None,excluded=(),windows=CURRENT_WINDOWS,progress=None):
    """Reduce an already loaded, complete native window; no history/provider read."""
    normalized=[];seen={}
    for row in events:
        at,amount,group,buy=trade(row,cluster_map=cluster_map)
        if not lower<=at<through:continue
        identity=row.get('identity',row.get('id'))
        if identity is None:
            signature=row.get('signature');index=row.get('index',row.get('event_index'))
            if not signature or index is None:return unavailable('event_identity_missing',at=through,asset=asset)
            identity=str(signature)+':'+str(index)
        body=(at,amount,group,buy)
        if identity in seen:
            if seen[identity]!=body:raise ValueError('volume_quality_event_conflict')
            continue
        seen[identity]=body
        if len(seen)>MAX_UPDATE_EVENTS:raise ValueError('volume_quality_update_bound')
        normalized.append(dict(at=at,quote=amount,group=group,buy=buy,authenticated=authoritative))
    state=advance(None,normalized,lower=lower,through=through,complete=authoritative,
                  asset=asset,authoritative=authoritative)
    return signal(state,now=now,observed_at=observed_at,windows=windows,excluded=excluded,
                  progress=progress)


def attention(value,now):
    if not enabled() or not value or value.get('complete') is not True:return 0
    if not value.get('observed_at',now+1)<=now<=value.get('expires_at',-1):return 0
    rank=value.get('rank',0)
    return rank if type(rank) is int and rank in (-1,0,2) else 0


def recovered(before,after,now):
    return (attention(after,now)>0 and before is not None
            and before.get('classification')!='QUALITY_ACCELERATING'
            and after.get('asof',0)>before.get('asof',0))


def neutral_failure(error,*,at=0,asset=None):
    logging.getLogger(__name__).warning('volume_quality_neutral_failure %s',type(error).__name__)
    return unavailable(type(error).__name__,at=at,asset=asset)
