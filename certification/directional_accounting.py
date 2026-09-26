"""Combine economic namespaces without duplicating a sleeve's genesis capital."""
from copy import deepcopy


def combine(lane,current,survivor):
    s=survivor['accounting'];ceiling=survivor['sleeve'];c=deepcopy(current)
    capital=c['initial'] if lane=='pump' else c['genesis']
    if capital!=s['initial'] or capital!=ceiling['capital']:
        raise ValueError('directional_accounting_genesis_disagreement')
    if not s['reconciled'] or not ceiling['reconciled']:raise ValueError('directional_accounting_unverified')
    # Namespace genesis is only a native ledger conservation parameter. There is
    # exactly one funded sleeve; the second nominal initial balance is subtracted.
    if lane=='pump':
        for key in ('cash','reserved','basis','realized','unrealized','marked_equity','capital_unit_seconds','open_positions','pending','settled'):
            c[key]+=s[key]
        c['cash']-=capital;c['marked_equity']-=capital
        if c['cash']+c['reserved']+c['basis']!=capital+c['realized']:
            raise ValueError('directional_cash_conservation')
    elif lane=='pons':
        if c.get('native_observation_complete') is not True or c.get('cash_basis_conservation') is not True:
            raise ValueError('directional_current_native_incomplete')
        c['cash']+=s['cash']+s['reserved']-capital
        c['remaining_cost_basis']+=s['basis'];c['booked_realized']+=s['realized']
        c['realized']=ceiling['realized'];c['unsettled']+=s['open_positions']+s['pending'];c['positions']+=s['open_positions']+s['pending']+s['settled']
        c['available']=ceiling['available'];c['reserved']=ceiling['reserved']
        c['capital_at_risk_unit_nanoseconds']+=s['capital_unit_seconds']*1_000_000_000
        c['cash_basis_conservation']=capital+c['booked_realized']==c['cash']+c['remaining_cost_basis']
        if not c['cash_basis_conservation']:raise ValueError('directional_cash_conservation')
        c['conservation']=capital+ceiling['realized']==ceiling['available']+ceiling['reserved']
    else:raise ValueError('directional_lane')
    c['shared_sleeve']=ceiling;c['one_funded_genesis']=True
    c['strategy_namespaces']=survivor['policies']
    return c


def summarize_survivor(lane,report,result):
    survivor=report.get('survivor')
    if not survivor or 'accounting' not in survivor:return result
    key='native_accounting' if lane=='pump' else 'cohort_accounting'
    current=result.get(key)
    if current is None:return result
    result['current_strategy_accounting']=deepcopy(current)
    result['survivor']=deepcopy(survivor)
    result[key]=combine(lane,current,survivor)
    s=survivor['accounting'];current_open=result['open_positions']
    result['open_positions']=current_open+s['open_positions']+s['pending']
    result['natural_settled']+=s['settled']
    result['accounting_reconciled']=result['accounting_reconciled'] is True and survivor['accounting_replay']['verified'] is True
    result['active_regimes']=list(survivor['policies'])
    result['durable_handoff']=bool(current_open==0 and s['open_positions']>0 and s['pending']==0
                                  and survivor.get('durable_handoff') is True)
    if result['durable_handoff']:result['continuation_state']=dict(schema='directional-survivor-handoff-v1',lane=lane,positions=s['open_positions'])
    return result


def terminal(lane,root,current):
    """Read-only verification of both namespaces and the one sleeve authority."""
    import json
    from pathlib import Path
    import threading
    from contextlib import closing
    from certification.terminal_reconciliation import connect
    from certification.sleeve_reservations import SleeveReservations
    from certification.survivor_paper_book import PaperBook
    from certification.survivor_history import History
    from certification.directional_sleeve import policies
    root=Path(root);sleeve_path=root/'directional-sleeve.sqlite'
    if not sleeve_path.exists():return current # Historical four-regime artifact.
    folder=root/'pump-survivor' if lane=='pump' else root/'pons-selective-continuation-v1-cohort/pons-survivor'
    with closing(connect(folder/'paper.sqlite')) as db,closing(connect(sleeve_path)) as allocation,closing(connect(folder/'history.sqlite')) as history_db:
        book=PaperBook.__new__(PaperBook);book.db=db;book.lock=threading.RLock()
        book.identity=json.loads(db.execute('SELECT body FROM genesis').fetchone()[0])
        strategy=book.identity['lane'];expected=policies(lane)
        if expected.get(strategy)!=book.identity['policy_hash']:raise ValueError('survivor_terminal_policy')
        replay=book.replay();accounting=book.reconcile()
        sleeve=SleeveReservations.__new__(SleeveReservations);sleeve.db=allocation
        sleeve.identity=json.loads(allocation.execute('SELECT body FROM sleeve_genesis').fetchone()[0])
        if sleeve.identity['policies']!=expected:raise ValueError('survivor_terminal_sleeve_identity')
        ceiling=sleeve.reconcile()
        history=History.__new__(History);history.db=history_db
        rows={r['id']:r for r in history.rows()}
        owned={p['position']:p for p in rows.values() if p.get('position')}
        positions=[json.loads(raw) for raw, in db.execute('SELECT body FROM positions')]
        for p in positions:
            reserved=sleeve.get(p['id'])
            if not reserved or reserved['strategy']!=strategy:raise ValueError('survivor_sleeve_reservation_missing')
            if p['status'] in ('open','reserved') and reserved['held']<p['basis']+p['reserved']:
                raise ValueError('survivor_capital_unreserved')
            if p['status']=='open' and p['id'] not in owned:raise ValueError('survivor_controller_missing')
            if p['status'] in ('settled','cancelled') and reserved['held']!=0:
                raise ValueError('survivor_terminal_capital_not_reconciled')
        status=dict(accounting=accounting,accounting_replay=replay,sleeve=ceiling,policies=expected,
            durable_handoff=accounting['pending']==0,active=True,strategy=strategy,policy_hash=expected[strategy])
        aggregate=combine(lane,current['accounting'],status)
        opened=current['open_positions']+accounting['open_positions']+accounting['pending']
        handoff=bool(current['open_positions']==0 and accounting['open_positions']>0 and accounting['pending']==0)
        return dict(current,accounting=aggregate,open_positions=opened,verified=current['verified'] and replay['verified'],
            strategy_accounting=dict(current=current['accounting'],survivor=accounting),
            survivor=status,durable_handoff=handoff,
            continuation_state=dict(schema='directional-survivor-handoff-v1',lane=lane,positions=accounting['open_positions']) if handoff else None)
