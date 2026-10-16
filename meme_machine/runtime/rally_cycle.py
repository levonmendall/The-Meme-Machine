"""Authenticated, bounded identities for completed post-graduation rallies.

The market adapters own acquisition and qualification.  This module only binds
their structural witnesses into a stable certificate.  Demand counts and moving
decision watermarks are deliberately absent from the identity.
"""
from meme_machine.runtime.journal import digest


SCHEMA = 'rally-cycle-v1'


def accumulate_outcomes(previous, additions):
    """Four fixed lifecycle buckets; missing deployed basis stays unknown."""
    result={key:dict(value) for key,value in (previous or {}).items()}
    for key,value in additions.items():
        if key not in ('first','second','third','later'):raise ValueError('rally_outcome_bucket')
        old=result.setdefault(key,dict(terminal_count=0,realized_pnl=0,original_basis=0,missing_original_basis=0))
        for field in ('terminal_count','realized_pnl','original_basis','missing_original_basis'):
            old[field]+=value[field]
        old['after_cost_return_bps']=(None if old['missing_original_basis'] or not old['original_basis']
            else old['realized_pnl']*10000//old['original_basis'])
    return result


def build_cycle(*, candidate, venue, graduation, peak_at, reset_at, base_start,
                base_end, breakout_at, decision_at, evidence_id, authoritative,
                complete, minimum_base_seconds, peak_price=None, reset_price=None,
                canonical_generation=None):
    if (not candidate or not venue or not isinstance(graduation,dict)
            or not graduation or not evidence_id or authoritative is not True
            or complete is not True):
        raise ValueError('rally_cycle_authenticated_evidence_required')
    times=(peak_at,reset_at,base_start,base_end,breakout_at,decision_at)
    graduated=graduation.get('at')
    if (any(type(t) is not int for t in times) or type(graduated) is not int
            or type(minimum_base_seconds) is not int or minimum_base_seconds<=0
            or not graduated<=peak_at<reset_at<=base_start<base_end<breakout_at<=decision_at
            or base_end-base_start<minimum_base_seconds):
        raise ValueError('rally_cycle_incomplete_structure')
    # Graduation records are immutable native lineage receipts. Their hash also
    # separates a replaced canonical graduation from its invalid predecessor.
    lineage=digest(dict(candidate=str(candidate),venue=venue,graduation=graduation))
    # The originating peak identifies the rally. A deeper low in the *same*
    # retracement, or a rolling completed base, cannot mint another identity.
    identity=dict(schema=SCHEMA,lineage=lineage,peak_at=peak_at)
    if peak_price is not None:identity['peak_price']=str(peak_price)
    value=dict(identity,id=digest(identity),candidate=str(candidate),venue=venue,
        graduation_at=graduated,reset_at=reset_at,base_start=base_start,base_end=base_end,
        breakout_at=breakout_at,decision_at=decision_at,evidence_id=str(evidence_id),
        authoritative=True,complete=True,minimum_base_seconds=minimum_base_seconds,
        canonical_generation=canonical_generation)
    if reset_price is not None:value['reset_price']=str(reset_price)
    value['certificate_hash']=digest(value)
    return value


def validate_cycle(value, *, candidate=None, observation_at=None):
    if not isinstance(value,dict) or value.get('schema')!=SCHEMA:
        raise ValueError('rally_cycle_certificate_required')
    body={k:v for k,v in value.items() if k!='certificate_hash'}
    identity={k:value.get(k) for k in ('schema','lineage','peak_at')}
    for key in ('peak_price',):
        if key in value:identity[key]=value[key]
    times=[value.get(k) for k in ('graduation_at','peak_at','reset_at','base_start','base_end','breakout_at','decision_at')]
    if (digest(body)!=value.get('certificate_hash') or digest(identity)!=value.get('id')
            or value.get('authoritative') is not True or value.get('complete') is not True
            or not value.get('evidence_id') or any(type(t) is not int for t in times)
            or not times[0]<=times[1]<times[2]<=times[3]<times[4]<times[5]<=times[6]
            or type(value.get('minimum_base_seconds')) is not int
            or value['minimum_base_seconds']<=0
            or value['base_end']-value['base_start']<value['minimum_base_seconds']
            or (candidate is not None and value.get('candidate')!=str(candidate))
            or (observation_at is not None and value['breakout_at']>observation_at)):
        raise ValueError('rally_cycle_certificate_invalid')
    return value


def reentry(previous, current, *, settlement, minimum_seconds=3600):
    """Setup spacing and settlement publication are independent clocks."""
    try:
        old=validate_cycle(previous['rally_cycle']) if previous.get('rally_cycle') else None
        new=validate_cycle(current['rally_cycle'],observation_at=current['at'])
        if (not isinstance(settlement,dict) or settlement.get('obligations_clear') is not True
                or type(settlement.get('terminal_at')) is not int
                or type(settlement.get('global_ack_at')) is not int):
            return False
        after=max(settlement['terminal_at'],settlement['global_ack_at'])
        decision_at=current.get('decision_at',new['decision_at'])
        if (type(decision_at) is not int or decision_at<max(after,new['breakout_at'])
                or new['breakout_at']<settlement['terminal_at']):
            return False
        # A legacy setup still retains its original spacing. It cannot supply
        # a synthetic structural cycle or a retroactive ACK.
        if current['at']-previous['at']<minimum_seconds:return False
        if old is not None:
            return (new['lineage']==old['lineage'] and new['id']!=old['id']
                    and new['peak_at']>old['breakout_at'])
        return new['peak_at']>previous['at']
    except (KeyError,TypeError,ValueError):
        return False
