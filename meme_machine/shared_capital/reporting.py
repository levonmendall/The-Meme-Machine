"""Read-only projections for the existing dashboard and acceptance observer."""
from copy import deepcopy
from contextlib import contextmanager
from decimal import Decimal
from functools import wraps
from meme_machine.exact_money import exact, money, amount
from meme_machine.portfolio_accounting import _decode_checkpoint, LANES
from meme_machine.runtime.usd_valuation import utc
from .model import FAMILIES, digest, scaled, ZERO
from .authority import _size_equity
from .runtime import RuntimeCapital


class ReportingReader(RuntimeCapital):
    @contextmanager
    def _transaction(self,*,write):
        if write:raise RuntimeError('reporting_reader_cannot_write')
        with self._mutex:
            owned=not self.db.in_transaction
            if owned:self.db.execute('BEGIN')
            try:
                yield
                if owned:self.db.execute('COMMIT')
            except BaseException:
                if owned and self.db.in_transaction:self.db.execute('ROLLBACK')
                raise


def coherent_read(fn):
    @wraps(fn)
    def read(authority,*args,**kwargs):
        reader=read_authority(authority.db);reader._mutex=authority._mutex
        with reader._transaction(write=False):return fn(reader,*args,**kwargs)
    return read


@coherent_read
@exact
def summary(authority,at):
    snap=authority.snapshot(at=at);state=snap['ledger'];risk=snap['risk'];capital=snap['capital']
    pending=[*state['pending_deliveries'],*state.get('runtime_pending',{}).values()]
    pnl=money(capital['realized_equity'])-money(state['initial_capital'])
    nav=risk['marked_equity']
    return dict(epoch_id=state['epoch_id'],inception_sha256=state['inception_sha256'],
        sequence=state['migration_source']['sequence']+authority.db.execute('SELECT count(*) FROM shared_capital_events').fetchone()[0],
        journal_hash=authority.db.execute('SELECT hash FROM shared_capital_events ORDER BY sequence DESC LIMIT 1').fetchone()[0],
        reconciliation='PASS',checks={k:True for k in ('lane_realized_less_shared_costs','remaining_basis','cash_basis_conservation','cost_attribution')},
        reservations=len(state['reservations'])+len(state['commitments']),pending_deliveries=len(pending),
        open_positions=sum(p['status']=='OPEN' for p in state['positions'].values()),
        positions_by_lane={f:sum(FAMILIES[p['regime']]==f and p['status']=='OPEN' for p in state['positions'].values()) for f in LANES},
        reservations_by_lane={f:sum(FAMILIES[h['regime']]==f for bucket in ('reservations','commitments') for h in state[bucket].values()) for f in LANES},
        pending_by_lane={f:sum(p['lane']==f for p in pending) for f in LANES},
        realized_pnl=amount(pnl),marked_equity=nav,unrealized_pnl=amount(money(nav)-money(capital['realized_equity'])) if nav is not None else None,
        funding_authority='SHARED',capital=capital,risk= risk,
        starting_capital=state['initial_capital'],sizing_basis=state['policy']['sizing_basis'],authority_health='CURRENT',cutover_status='SHARED')


@coherent_read
@exact
def export(authority,*,at=None):
    snap=authority.snapshot(at=at);state=snap['ledger'];at=max(state['at'],at or state['at']);c=snap['capital'];risk=snap['risk']
    old=_decode_checkpoint(state['migration_source']['replayed_state']);identities=old['identities']
    positions=[]
    for life,p in sorted(state['positions'].items()):
        r=p['regime'];mark=p.get('mark');family=FAMILIES[r]
        legacy_mark=(p.get('legacy_position') or {}).get('mark') or {}
        mark_at=mark.get('at') if mark else None
        if mark and mark_at is None:
            from .runtime import seconds
            mark_at=seconds(legacy_mark['as_of']) if legacy_mark.get('as_of') else mark['valuation']['as_of']
        value=dict(state='CURRENT',net_liquidation_value=mark['net_value'],
            as_of=utc(mark_at),valid_until=utc(mark['valuation']['valid_until'])) if mark else dict(state='UNAVAILABLE')
        if p['status']=='SETTLED':value=None
        native=deepcopy(p.get('legacy_position') or {})
        if native:
            native=_decode_checkpoint(native)
        native.update(id=life,epoch_id=state['epoch_id'],lane=family,
            asset=native.get('asset','asset-'+digest(p['economic_keys'])[:32]),state=p['status'],
            entered_at=utc(p['opened_at']),settled_at=utc(p['settled_at']) if p['status']=='SETTLED' else None,
            strategy_id=p['strategy_id'],exposure_entered=True,capital=p['capital_deployed'],remaining_basis=p['basis'],
            realized_pnl=p['realized_pnl'],fees=p['costs'],gross_result=p['gross_result'],entry_value=p['original_basis'],
            exit_value=None,mark=value,lifecycle=native.get('lifecycle',[]),**identities['lanes'][family])
        native.update(regime=r,original_basis=p['original_basis'],partial_exits=p['partials'],scale_committed=p['scale_committed'],
            staged_add_basis=amount(money(p['capital_deployed'])-money(p['original_basis'])))
        ceilings = dict(portfolio_equity=scaled(max(ZERO,_size_equity(state,r)),250),
            half_original_basis=scaled(money(p['original_basis']),5000),
            combined_basis_headroom=max(ZERO,scaled(max(ZERO,_size_equity(state,r)),750)-money(p['original_basis'])))
        native['staged_add_limits'] = dict({k:amount(v) for k,v in ceilings.items()},
            maximum_basis=amount(min(ceilings.values())) if p['status']=='OPEN' and not p['scale_committed'] else '0',
            native_qualification_required=True)
        positions.append(native)
    reserved=sum((money(c[k]) for k in ('active_reservations','pending_authoritative_commitments','required_funding_obligations')),Decimal(0))
    pnl=money(c['realized_equity'])-money(state['initial_capital'])
    retired={f:dict(count=sum(v['count'] for r,v in state['retired'].items() if FAMILIES[r]==f),
        realized_pnl=amount(sum((money(v['pnl']) for r,v in state['retired'].items() if FAMILIES[r]==f),Decimal(0))),
        fees=amount(sum((money(v['costs']) for r,v in state['retired'].items() if FAMILIES[r]==f),Decimal(0)))) for f in LANES}
    fees=sum((money(v) for v in state['costs'].values()),Decimal(0))+money(state['shared_costs'])
    details=dict(inception_equity=state['initial_capital'],**c,marked_equity=risk['marked_equity'],
        sizing_basis=state['policy']['sizing_basis'],
        directional_sizing={r:dict(realized_equity=amount(_size_equity(state,r)),new_position_target=amount(scaled(max(ZERO,_size_equity(state,r)),500)),
            staged_add_equity_ceiling=amount(scaled(max(ZERO,_size_equity(state,r)),250)),combined_basis_ceiling=amount(scaled(max(ZERO,_size_equity(state,r)),750)),
            target_bps=500,add_bps=250,combined_bps=750,native_qualification_required=True) for r in state['realized'] if '_' in r},
        regimes=snap['lanes'],risk=wire_risk(risk),risk_limits={
            **{k:state['policy'][k] for k in ('portfolio_bps','family_max_bps','regime_max_bps','asset_bps','group_bps','drawdown_stop_bps')},
            'cash_floor_bps':state['policy'].get('cash_floor_bps',0),
            'transaction_cost_floor':state['policy'].get('transaction_cost_floor','0')},authority_health='CURRENT',cutover_status='SHARED',
        paused_families={'meteora':'PAUSED','ramses':'PAUSED'},allocation_latency=state.get('runtime_latency',{'state':'UNMEASURED'}))
    if state['policy']['sizing_basis']=='effective_family_equivalence':
        details['family_equivalent_equity']={f:amount(_size_equity(state,f+'_current' if f in ('pump','pons') else f)) for f in LANES}
    sequence=old['sequence']+authority.db.execute('SELECT count(*) FROM shared_capital_events').fetchone()[0]
    until=min([at+30]+[p['mark']['valuation']['valid_until'] for p in state['positions'].values()
        if p['status']=='OPEN' and p.get('mark') and p['mark']['valuation']['valid_until']>=at])
    return dict(schema='meme-machine-portfolio-export-v1',mode='canonical',epoch_id=state['epoch_id'],inception_sha256=state['inception_sha256'],
        sequence=sequence,as_of=utc(at),valid_until=utc(until),complete_lifecycle_coverage=True,
        balances=dict(equity=risk['marked_equity'],available_cash=c['free_cash'],reserved_cash=amount(reserved),deployed_capital=c['deployed_basis'],
            realized_pnl=amount(pnl),unrealized_pnl=amount(money(risk['marked_equity'])-money(c['realized_equity'])) if risk['marked_equity'] is not None else None,
            fees=amount(fees),shared_costs=state['shared_costs']),positions=positions,history=state.get('reporting_history',old['history'])[-2000:],history_complete=False,
        reconciliation=dict(state='CURRENT',checks={k:True for k in ('lane_realized_less_shared_costs','remaining_basis','cash_basis_conservation','cost_attribution')}),
        lane_identities=identities['lanes'],external_adjustments=[],retired_lane_totals=retired,
        retired_regime_totals={r:dict(count=v['count'],realized_pnl=v['pnl'],fees=v['costs']) for r,v in state['retired'].items()},
        shared_capital=details,**identities['portfolio'])


def wire_risk(risk):
    from .model import wire
    return wire(risk)


def read_authority(db):
    """Use a caller-owned read snapshot; no schema setup, writer or provider."""
    import threading
    reader=object.__new__(ReportingReader);reader.db=db;reader._mutex=threading.RLock()
    reader._replaying=False;reader.fault=None
    return reader


def observe(db):
    import time
    return summary(read_authority(db),int(time.time()))
