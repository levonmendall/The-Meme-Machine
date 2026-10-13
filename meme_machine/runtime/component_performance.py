"""Reporting attribution of actual native fills; never accounting authority.

The native pooled basis release is authoritative. Sales allocate integer quantity
pro rata to remaining original/add quantities, then allocate that exact booked
basis release pro rata to their remaining bases. Net proceeds allocate pro rata
to the attributed sold quantities. Each division floors the original allocation
and assigns the remainder to the add, capped by available quantity/basis. Thus
every event conserves native quantities, remaining basis and realized P&L exactly.
Rounding can leave a component with zero quantity and a small remaining pooled
basis allocation until a later release; report that allocation explicitly. Final
settlement consumes all remaining quantity/basis. Booked costs and net proceeds
already include native execution costs; this projection deducts no further fees.

Incremental reducers run only in existing reporting/retention passes. Marks and
observed highs are not fills, and splitting actual P&L is no causal no-add result.
"""
from copy import deepcopy
from contextlib import closing
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from meme_machine.runtime.journal import digest

SCHEMA = 'native-component-performance-v1'
CONVENTION = 'pooled-native-basis-pro-rata-integer-v1'


def unavailable(identity, reason, *, totals=None):
    return dict(schema=SCHEMA, state='UNAVAILABLE', native_lifecycle_id=identity,
        reason=reason, source='ACTUAL_NATIVE_BOOKED_EVENTS', convention=CONVENTION,
        units='native_integer_quote_and_token_units', totals=totals,
        components=None, events=None, hypothetical_no_add=None,
        causal_profit_from_add=None, component_unrealized_pnl=None,
        observed_high_water=None, financial_authority=False)


def _projection(position, adapter):
    basis_key, pnl_key = ('remaining_cost', 'realized_pnl') if adapter == 'pons' else ('basis', 'realized')
    value = dict(id=position['id'], status=position['status'], quantity=position['tokens'],
        remaining_basis=position[basis_key], realized_pnl=position[pnl_key])
    if adapter == 'pons':
        value.update(version=position['version'], booked_cost=position['cost'],
                     net_proceeds=position['realized_proceeds'])
    for key in ('quantity', 'remaining_basis'):
        if type(value[key]) is not int or value[key] < 0:raise ValueError('native_component_integer')
    if type(value['realized_pnl']) is not int:raise ValueError('native_component_integer')
    return value


def _component():
    return dict(purchased_quantity=0, booked_cost=0, sold_quantity=0,
        basis_released=0, net_proceeds=0, remaining_quantity=0,
        remaining_basis=0, realized_pnl=0, entry_at=None)


def _split(total, original, added):
    if min(total, original, added) < 0 or total > original+added:
        raise ValueError('native_component_allocation')
    first = total*original//(original+added) if original+added else 0
    return first, total-first


def _totals(result, native):
    components = result['components']
    totals = {key:sum(c[key] for c in components.values()) for key in
        ('purchased_quantity','booked_cost','sold_quantity','basis_released',
         'net_proceeds','remaining_quantity','remaining_basis','realized_pnl')}
    if (totals['remaining_quantity'] != native['quantity'] or
            totals['remaining_basis'] != native['remaining_basis'] or
            totals['realized_pnl'] != native['realized_pnl'] or
            totals['booked_cost']-totals['basis_released'] != totals['remaining_basis'] or
            totals['net_proceeds']-totals['basis_released'] != totals['realized_pnl'] or
            totals['purchased_quantity']-totals['sold_quantity'] != totals['remaining_quantity']):
        raise ValueError('native_component_conservation')
    if 'booked_cost' in native and any(totals[k] != native[k] for k in ('booked_cost','net_proceeds')):
        raise ValueError('native_component_native_totals')
    result['totals'] = totals


def extend_native(events, prior=None, *, adapter, lifecycle_id):
    """Extend an already verified native prefix without inventing retired detail.

    Caller verifies the native journal using its existing authority. This reducer
    also requires the original reservation, consecutive Pons versions, and exact
    native integer deltas. Failures affect component availability only.
    """
    if adapter not in ('pons', 'paper'):raise ValueError('native_component_adapter')
    result = deepcopy(prior) if prior else dict(unavailable(lifecycle_id, 'missing_native_history'),
        state='AVAILABLE', reason=None, adapter=adapter,
        components=dict(original=_component(), add=_component()), events=[],
        native_projection=None, through_event_hash=None)
    for event in events:
        native = None
        try:
            candidate_native = _projection(event['position'], adapter)
            if candidate_native['id'] != lifecycle_id:raise ValueError('native_component_lifecycle_join')
            native = candidate_native
            checksum = digest(event)
            if result.get('through_event_hash') == checksum:continue
            previous = result.get('native_projection')
            if result['state'] != 'AVAILABLE':
                result.update(native_projection=native, totals=native)
                continue
            if result.get('adapter') != adapter:raise ValueError('native_component_adapter_join')
            if previous and previous['id'] != lifecycle_id:raise ValueError('native_component_lifecycle_join')
            action = event['action']
            if previous is None:
                if (action not in ('reserve','reserved') or native['quantity'] or
                        native['remaining_basis'] or native['realized_pnl'] or
                        adapter == 'pons' and native['version'] != 0):
                    raise ValueError('missing_original_native_reservation')
                previous = dict(native)
            elif adapter == 'pons' and (native['version'] != previous['version']+1 or
                    event.get('previous_hash') != result['through_event_hash']):
                raise ValueError('native_component_prefix_join')
            components = result['components'];original,added = components['original'],components['add']
            quantity = native['quantity']-previous['quantity']
            basis = native['remaining_basis']-previous['remaining_basis']
            pnl = native['realized_pnl']-previous['realized_pnl']
            allocations = None
            if action in ('entry','filled','scale_add') and quantity > 0:
                name = 'add' if action == 'scale_add' else 'original';component = components[name]
                if basis <= 0 or pnl or component['purchased_quantity']:
                    raise ValueError('native_component_fill')
                component['purchased_quantity'] += quantity;component['remaining_quantity'] += quantity
                component['booked_cost'] += basis;component['remaining_basis'] += basis
                component['entry_at'] = event['at']
                allocations = {name:dict(quantity=quantity, booked_cost=basis)}
            elif action in ('exit','partial_harvest','settled','liquidity_writeoff') and quantity < 0:
                sold,released = -quantity,-basis;net = pnl+released
                if released < 0 or net < 0:raise ValueError('native_component_sale')
                quantities = _split(sold, original['remaining_quantity'], added['remaining_quantity'])
                bases = _split(released, original['remaining_basis'], added['remaining_basis'])
                proceeds_original = net*quantities[0]//sold
                proceeds = (proceeds_original,net-proceeds_original)
                allocations = {}
                for name,q,b,n in zip(('original','add'), quantities,bases,proceeds):
                    component = components[name]
                    component['sold_quantity'] += q;component['remaining_quantity'] -= q
                    component['basis_released'] += b;component['remaining_basis'] -= b
                    component['net_proceeds'] += n;component['realized_pnl'] += n-b
                    allocations[name] = dict(quantity=q,basis_released=b,net_proceeds=n,realized_pnl=n-b)
            elif quantity or basis or pnl:
                raise ValueError('native_component_unrecognized_economic_delta')
            _totals(result, native)
            if allocations is not None:
                result['events'].append(dict(event_id=(lifecycle_id+':'+str(native['version'])) if adapter == 'pons' else checksum,
                    at=event['at'], action=action, allocations=allocations,
                    remaining_quantity=native['quantity'],remaining_basis=native['remaining_basis'],
                    realized_pnl=native['realized_pnl']))
            result.update(native_projection=native, through_event_hash=checksum)
        except (KeyError,TypeError,ValueError) as error:
            result = unavailable(lifecycle_id,str(error),totals=native)
    return result


def pons_report(paper, identity):
    """Existing verified native prefix and its exact suffix, at report time."""
    from meme_machine.runtime.storage import pons_prefix
    positions = {p['id']:p for p in paper.positions()}
    if identity not in positions:return unavailable(identity,'native_position_unavailable')
    prefix = pons_prefix(paper).get(identity)
    if prefix and not prefix.get('component_performance'):
        return unavailable(identity,'retired_component_detail',totals=_projection(positions[identity],'pons'))
    events = paper.events(identity)
    if prefix:
        events = [e for e in events if e['position']['version'] > prefix['event']['position']['version']]
    report = extend_native(events, prefix.get('component_performance') if prefix else None,
                           adapter='pons',lifecycle_id=identity)
    if report.get('native_projection') != _projection(positions[identity],'pons'):
        return unavailable(identity,'native_component_final_join',totals=_projection(positions[identity],'pons'))
    return report


def pons_path_report(path, expected):
    """Read-only completed-lifecycle adapter; never initializes a native writer."""
    identity = expected.get('id')
    if not identity:return unavailable(identity,'native_lifecycle_identity_unavailable')
    try:
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper
        from meme_machine.lanes.pons.evidence import BoundaryError
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN')
            def get(category,key):
                row = db.execute('SELECT body,hash FROM records WHERE category=? AND id=?',(category,key)).fetchone()
                if row is None:raise BoundaryError('missing_evidence')
                value = json.loads(row[0])
                if digest(value) != row[1]:raise BoundaryError('evidence_checksum_mismatch')
                return value
            paper = object.__new__(SelectivePaper)
            paper.store = SimpleNamespace(db=db,get=get);paper.experiment = expected['experiment']
            report = pons_report(paper,identity)
            row=db.execute('SELECT body FROM pons_selective_paper WHERE id=?',(identity,)).fetchone()
            if row is None or json.loads(row[0]) != expected:
                return unavailable(identity,'completed_native_position_join',totals=_projection(expected,'pons'))
            return report
    except (OSError,sqlite3.Error,ValueError,KeyError) as error:
        return unavailable(identity,'native_detail_unavailable:'+type(error).__name__)


def coverage(reports, *, prior=None, missing_records=0, population='completed_native_lifecycles'):
    """Coverage counts accompany every retained component aggregate."""
    value = dict(prior or dict(records=0,available=0,unavailable=0))
    for report in reports:
        value['records'] += 1
        key = 'available' if isinstance(report,dict) and report.get('state') == 'AVAILABLE' else 'unavailable'
        value[key] += 1
    value['records'] += missing_records;value['unavailable'] += missing_records
    value.update(population=population,complete_component_coverage=value['unavailable'] == 0 and
        not value.get('historical_record_count_unavailable',False))
    return value


def paper_report(book, identity):
    """Reporting consumer for Pump Current and the two native Survivor books."""
    book.replay()
    if not book.db.execute('SELECT 1 FROM positions WHERE id=?',(identity,)).fetchone():
        from meme_machine.runtime.learning import get
        retained=get(book.db,'lifecycle:'+identity)
        report=(retained or {}).get('facts',{}).get('component_performance')
        return deepcopy(report) if report else unavailable(identity,'retired_component_record_unavailable')
    anchor = book._archive() or {}
    prior = anchor.get('component_performance',{}).get(identity)
    if identity in anchor.get('positions',{}) and prior is None:
        prior = unavailable(identity,'retired_component_detail')
    events = (json.loads(raw) for raw, in book.db.execute(
        "SELECT body FROM journal WHERE json_extract(body,'$.position.id')=? ORDER BY seq",(identity,)))
    report = extend_native(events,prior,adapter='paper',lifecycle_id=identity)
    native = _projection(book._load(identity),'paper')
    if report.get('native_projection') != native:
        return unavailable(identity,report.get('reason') or 'native_component_final_join',totals=native)
    return report


def accumulate(report, prior=None):
    """Bounded population totals for available captured splits, with coverage.

    Caller retains coverage separately. This is never a substitute for missing
    component detail or authoritative native totals.
    """
    value=deepcopy(prior) if prior else dict(original=_component(),add=_component())
    if not isinstance(report,dict) or report.get('state') != 'AVAILABLE':return value
    for name in ('original','add'):
        for key in ('purchased_quantity','booked_cost','sold_quantity','basis_released',
                    'net_proceeds','remaining_quantity','remaining_basis','realized_pnl'):
            value[name][key] += report['components'][name][key]
    return value
