"""Source-defined owner pause, independent of restart and inherited overrides.

Historical readers and provider-free archive fixtures retain all family identities.
Operational producers use this set; environment values cannot reactivate a lane.
Historical journal replay deliberately remains independent of this admission gate.
"""
import os

ACTIVE_LANES = ('pump', 'pons')
PAUSED_LANES = {'ramses': 'market_opportunity_insufficient',
                'meteora': 'owner_indefinite_pause'}
SOLANA_FAMILIES = ('pump', 'pumpswap', 'meteora')


class PausedFamily(RuntimeError):
    pass


def operational(environ=None):
    env = os.environ if environ is None else environ
    return bool(env.get('MM_OPERATIONAL_PHASE') or
                env.get('MM_PAPER_EPOCH', '').startswith('paper-'))


def family(lane):
    if lane=='pumpswap':return 'pump'
    return next((f for f in (*ACTIVE_LANES,*PAUSED_LANES)
                 if lane==f or lane.startswith(f+'_') or lane.startswith(f+'-')),lane)


def enabled(lane, *, production=None):
    production = operational() if production is None else production
    return not production or family(lane) not in PAUSED_LANES


def require_active(lane, *, production=None):
    if not enabled(lane, production=production):
        raise PausedFamily('paused_family_activity_forbidden:' + family(lane))


def solana_families():
    return tuple(f for f in SOLANA_FAMILIES if enabled(f))


def active_sql(column, *, solana=False):
    """Fixed source literals; archived rows are retained without being serviced."""
    lanes = solana_families() if solana else ACTIVE_LANES
    if not operational():
        return '1=1'
    return column + ' IN (' + ','.join("'" + f + "'" for f in lanes) + ')'


def require_scope(scope):
    for lane in PAUSED_LANES:
        if lane in scope.split(':'):
            require_active(lane)


def active_scope_sql(column,*,production=None):
    if not (operational() if production is None else production):return '1=1'
    return '('+' AND '.join('('+column+" NOT LIKE '%:"+lane+":%' AND "+
        column+" NOT LIKE '"+lane+":%' AND "+column+" NOT LIKE '"+lane+"_%' AND "+
        column+" NOT LIKE '"+lane+"-%' AND "+column+" NOT IN ('"+lane+"','program:"+lane+"'))"
        for lane in PAUSED_LANES)+')'


def evidence_scope_sql(column):
    """Freeze accounts owned only by paused lanes; keep shared Pump accounts.

    Call with a qualified scope column in the canonical evidence schema.
    Historical interests remain preserved without becoming live authority.
    """
    if not operational():return '1=1'
    return '('+active_scope_sql(column)+''' AND NOT EXISTS(
        SELECT 1 FROM interests paused_owner WHERE paused_owner.scope='''+column+'''
        AND NOT ('''+active_scope_sql('paused_owner.owner')+''') AND NOT EXISTS(
            SELECT 1 FROM interests live_owner WHERE live_owner.scope='''+column+'''
            AND live_owner.active=1 AND '''+active_scope_sql('live_owner.owner')+''')))'''
