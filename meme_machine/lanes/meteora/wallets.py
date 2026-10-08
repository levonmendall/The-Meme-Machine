"""Bounded shadow cash-flow episodes. Never supplies entry or sizing authority."""
from .store import digest


def observe(scorecard, event):
    """Record known trade cash flows; transfers invalidate return attribution.

    A trade-window start is not proof of zero starting wallet inventory. Thus even
    a flat observed episode remains unvalidated without a complete balance boundary.
    """
    episodes=scorecard.setdefault('episodes',{})
    mint=event['mint']
    if mint not in episodes and len(episodes)>=32:
        oldest=next(iter(episodes))
        del episodes[oldest]
        scorecard['dropped_episode_count']=scorecard.get('dropped_episode_count',0)+1
    e=episodes.setdefault(mint,dict(bought=0,sold=0,spent=0,received=0,fees=0,
        first_available=event['available_time'],last_available=event['available_time'],
        outcome_available=None,return_lamports=None,status='unresolved',
        inventory_boundary='unknown',follower_return=None))
    e['last_available']=max(e['last_available'],event['available_time'])
    if event.get('type','trade')!='trade':
        e['inventory_boundary']='transfer_or_airdrop'
        e['status']='unresolved'
        e['return_lamports']=None
        return
    if event['buy']:
        e['bought']+=event['tokens'];e['spent']+=event['amount']
    else:
        e['sold']+=event['tokens'];e['received']+=event['amount']
    e['fees']+=event.get('fees_lamports',0)
    if e['sold']>e['bought']:
        e['inventory_boundary']='preexisting_or_transferred_inventory'
    if e['sold']==e['bought'] and e['bought']:
        e['status']='observed_flat_unvalidated'
        e['outcome_available']=event['available_time']
    # Do not transform partial windows, leader timing or deposits into performance.
    scorecard['skill']='unvalidated'
    scorecard['sizing_influence']=0
