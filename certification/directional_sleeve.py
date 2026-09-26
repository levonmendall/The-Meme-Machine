"""Bindings between native directional ledgers and their one sleeve ceiling."""
import os
from certification.journal import digest
from certification.sleeve_reservations import SleeveReservations


def policies(lane):
    if lane=='pump':
        from meme_machine.pump_acceleration_strategy import STRATEGY_ID,policy_hash
        from meme_machine.pumpswap_survivor import STRATEGY_ID as survivor, POLICY_HASH
        return {STRATEGY_ID:policy_hash(),survivor:POLICY_HASH}
    if lane=='pons':
        from robinhood_research.pons_selective_continuation import POLICY_HASH
        from robinhood_research.pons_postgrad_survivor import STRATEGY_VERSION, POLICY_HASH as survivor_hash
        return {'pons-selective-continuation-v1':POLICY_HASH,STRATEGY_VERSION:survivor_hash}
    raise ValueError('directional_sleeve_lane')


def composite_policy(lane):
    return dict(lane=lane,strategies=policies(lane),allocation=dict(
        one_sleeve=True,portfolio_allocation_increased=False,
        survivor_target_sleeve_bps=25,priority=['positions','current','survivor'],
        reservation_authority='durable_shared_sleeve_v1',
        same_regime_reentry=False,accounting_namespaces_separate=True))


def composite_hash(lane):
    return digest(composite_policy(lane))


def open_sleeve(lane,capital):
    path=os.environ.get('MM_DIRECTIONAL_SLEEVE_DB')
    if not path:
        # Standalone historical native ledger replay has no allocation authority.
        if os.environ.get('MM_DIRECTIONAL_COMPOSITE_REQUIRED')=='1':
            raise ValueError('directional_sleeve_path_required')
        return None
    cohort=os.environ.get('MM_DIRECTIONAL_COHORT_ID')
    if not cohort:raise ValueError('directional_cohort_required')
    return SleeveReservations(path,lane=lane,capital=capital,policies=policies(lane),cohort=cohort)


def native_terminal(sleeve,identity,position,at,*,verified):
    if sleeve is None:return
    if position['status'] not in ('settled','cancelled'):
        raise ValueError('native_position_not_terminal')
    pnl=position.get('realized',position.get('pnl'))
    if pnl is None:raise ValueError('native_realized_required')
    sleeve.release(identity,pnl=pnl,at=at,terminal_hash=digest(position),native_verified=verified,
                   cancelled=position['status']=='cancelled')


def recover_pump_terminals(book):
    """Finish only the allocation-side acknowledgement of an existing terminal."""
    import json
    sleeve=open_sleeve('pump',book.identity['initial'])
    if sleeve is None:return
    try:
        verified=book.replay()['verified']
        for raw, in book.db.execute('SELECT body FROM positions'):
            position=json.loads(raw);held=sleeve.get(position['id'])
            if position['status'] in ('settled','cancelled') and held and held['held']:
                native_terminal(sleeve,position['id'],position,position['last_at'],verified=verified)
    finally:sleeve.close()
