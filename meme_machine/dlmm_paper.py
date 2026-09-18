"""Isolated DLMM mechanical replay on the existing Store and shared genesis.

There is deliberately no prospective entry implementation. Replay requires a
non-prospective Store at every entry boundary, including after restart. This is a
counterfactual augmented-pool model: identical external exact-input orders are
re-executed against real liquidity plus virtual liquidity. It does not pretend
there is an on-chain position or that real swap totals are unchanged by our LP.
"""
from copy import deepcopy

from . import dlmm
from .provider import Unavailable
from .store import IntegrityError, digest

# Fixed mechanical experiment, not optimized strategy parameters. Two adjacent
# SOL-side bins, excluding active (avoids unmodeled active-bin composition fees).
CAPITAL = 100_000_000
HOLD_SECONDS = 60
GAS_PER_TX = 50_000
# Conservative fixed rent occupancy for a <=70-bin PositionV2 and two ATAs.
# Full recovery only on modeled close; no newly initialized bin arrays supported.
POSITION_RENT = 60_000_000
TOKEN_RENT = 2 * 2_100_000
RENT = POSITION_RENT + TOKEN_RENT
ENTRY_COST = 3 * GAS_PER_TX  # create/ATAs, wrap SOL, add liquidity
EXIT_COST = 4 * GAS_PER_TX   # remove/claim, residual swap, close position, unwrap/close ATAs
RESERVATION = CAPITAL + RENT + ENTRY_COST + EXIT_COST
MAX_POSITIONS = 4
MAX_LIFECYCLES = 100


def reconcile_liquidity(s):
    if 'liquidity_orders' not in s or 'liquidity_positions' not in s:
        raise IntegrityError('dlmm_incomplete_state')
    orders=s['liquidity_orders']; positions=s.get('liquidity_positions',{})
    if s.get('dlmm_allocation_enabled') is not False:
        raise IntegrityError('dlmm_authority_must_remain_disabled')
    if s['mode']=='prospective' and (positions or orders):
        raise IntegrityError('dlmm_prospective_exposure_forbidden')
    if len(orders)>MAX_LIFECYCLES or len(positions)>MAX_POSITIONS:
        raise IntegrityError('dlmm_resource_bound')
    for oid,o in orders.items():
        if o['status'] not in ('reserved','open','settled','cancelled') or o['reservation'] != RESERVATION:
            raise IntegrityError('dlmm_order_invariant')
        if (o['status']=='open') != (oid in positions):
            raise IntegrityError('dlmm_order_position_link')
    for oid,p in positions.items():
        if oid not in orders or p['id']!=oid or p['basis'] != CAPITAL+ENTRY_COST+EXIT_COST or p['rent'] != RENT:
            raise IntegrityError('dlmm_capital_occupation')
        if p['stage'] not in ('deposited','exit_intent','withdrawn') or p['surface']!='meteora-dlmm':
            raise IntegrityError('dlmm_position_stage')
        if len(p['shares'])!=2 or len(p['virtual']['bins'])>dlmm.MAX_BINS or len(p['real']['bins'])>dlmm.MAX_BINS:
            raise IntegrityError('dlmm_position_bound')
        for bid,share in p['shares'].items():
            b=p['virtual']['bins'][bid]
            if share<=0 or min(b['x'],b['y'],b['fee_x'],b['fee_y'])<0:
                raise IntegrityError('dlmm_inventory_invariant')
            if p['stage']!='withdrawn' and share>b['supply']:
                raise IntegrityError('dlmm_share_invariant')
        if p['cursor'][0]<p['entry_slot']:
            raise IntegrityError('dlmm_cursor_invariant')
        if p['inventory']!=inventory(p):
            raise IntegrityError('dlmm_inventory_checkpoint_mismatch')


def prospective_reserve(*args,**kwargs):
    """No configuration, candidate, metric or replay flag can open this gate."""
    raise PermissionError('dlmm_allocation_disabled')


def _guard(store):
    if store.state['mode'] not in ('synthetic','captured'):
        raise PermissionError('dlmm_allocation_disabled')


def inventory(p):
    if p['stage']=='withdrawn':
        return deepcopy(p['withdrawal'])
    x=y=fx=fy=0
    for bid,share in p['shares'].items():
        b=p['virtual']['bins'][bid]
        x+=dlmm.withdraw_amount(share,b['x'],b['supply'])
        y+=dlmm.withdraw_amount(share,b['y'],b['supply'])
        start=p['fee_start'][bid]
        fx+=dlmm.claim_fee(share,b['fee_x']-start['x'])
        fy+=dlmm.claim_fee(share,b['fee_y']-start['y'])
    return dict(x=x,y=y,fee_x=fx,fee_y=fy)


def _withdraw_preview(p):
    state=deepcopy(p['virtual']); assets=inventory(p)
    if p['stage']!='withdrawn':
        for bid,share in p['shares'].items():
            b=state['bins'][bid]
            b['x']-=dlmm.withdraw_amount(share,b['x'],b['supply'])
            b['y']-=dlmm.withdraw_amount(share,b['y'],b['supply'])
            b['supply']-=share
    return state,assets


def _executable_mark(p,now):
    if p['unresolved'] or now<max(p['last_time'],p.get('withdrawal_time',0)) or now-p['last_time']>dlmm.MAX_AGE:
        raise Unavailable('dlmm_unresolved_or_stale_mark')
    state,assets=_withdraw_preview(p)
    sol_side='x' if p['x']==dlmm.WSOL else 'y'
    token_side='y' if sol_side=='x' else 'x'
    sol=assets[sol_side]+assets['fee_'+sol_side]+p['idle_sol']
    tokens=assets[token_side]+assets['fee_'+token_side]
    quote=None
    if tokens:
        _,quote=dlmm.swap(state,tokens,sol_side=='y',now)
        sol+=quote['output']
    # EXIT_COST is already held within basis; debit it exactly once at settlement.
    return dict(resolved=True,assets=assets,token_input=tokens,liquidation=quote,
                sol_proceeds=sol,net_sol=sol+p['exit_cost_reserve']-EXIT_COST,
                costs=EXIT_COST,rent_recovery=p['rent'],time=now,
                evidence=p['lineage'],kind='hypothetical_virtual_economics')


class Replay:
    def __init__(self,store):
        _guard(store)
        self.store=store
        if 'liquidity_orders' not in store.state:
            with store.transaction('dlmm_replay_schema_v1') as s:
                s.update(dlmm_allocation_enabled=False,liquidity_orders={},liquidity_positions={})

    def reserve(self,oid,snapshot,now):
        _guard(self.store)
        if not isinstance(oid,str) or not 1<=len(oid)<=80:
            raise ValueError('dlmm_order_id_bound')
        s=self.store.state
        if oid in s['liquidity_orders']:
            raise ValueError('dlmm_duplicate_order')
        p=dlmm.validate(snapshot,now,'synthetic' if s['mode']=='synthetic' else 'real')
        active=len(s['positions'])+len(s['liquidity_positions'])+sum(o['status']=='reserved' for o in s['orders'].values())+sum(o['status']=='reserved' for o in s['liquidity_orders'].values())
        if active>=MAX_POSITIONS or len(s['liquidity_orders'])>=MAX_LIFECYCLES or self.store.pressure():
            raise ValueError('dlmm_capacity')
        if s['cash']-RESERVATION<s['initial']//10:
            raise ValueError('dlmm_shared_capital_insufficient')
        if any(o['pool']==p['pool'] and o['status'] in ('reserved','open') for o in s['liquidity_orders'].values()):
            raise ValueError('dlmm_duplicate_pool_exposure')
        if any(m in s['positions'] for m in (p['x'],p['y'])) or any(o['mint'] in (p['x'],p['y']) and o['status']=='reserved' for o in s['orders'].values()):
            raise ValueError('dlmm_related_directional_exposure')
        with self.store.transaction('dlmm_replay_reserve') as s:
            s['cash']-=RESERVATION; s['reserved']+=RESERVATION
            s['liquidity_orders'][oid]=dict(status='reserved',reservation=RESERVATION,pool=p['pool'],
                x=p['x'],y=p['y'],snapshot_hash=digest(snapshot),slot=p['slot'],time=now)
        return oid

    def cancel(self,oid):
        _guard(self.store)
        with self.store.transaction('dlmm_replay_cancel') as s:
            o=s['liquidity_orders'][oid]
            if o['status']!='reserved':
                raise ValueError('dlmm_not_reserved')
            s['reserved']-=o['reservation']; s['cash']+=o['reservation']; o['status']='cancelled'

    def deposit(self,oid,snapshot,now):
        _guard(self.store)
        s=self.store.state; o=s['liquidity_orders'][oid]
        if o['status']!='reserved':
            raise ValueError('dlmm_not_reserved')
        real=dlmm.validate(snapshot,now,'synthetic' if s['mode']=='synthetic' else 'real')
        if real['pool']!=o['pool'] or real['slot']<o['slot'] or now<o['time']:
            raise ValueError('dlmm_reservation_evidence_mismatch')
        v=deepcopy(real); sol_y=real['y']==dlmm.WSOL
        ids=[real['active']-2,real['active']-1] if sol_y else [real['active']+1,real['active']+2]
        shares={}; starts={}; distribution=[]
        # SpotOneSide: flat quote-value weight. For SOL=X, inverse-price weights
        # distribute equal quote value; integer remainder remains idle SOL.
        weights=[dlmm.Q if sol_y else dlmm.Q*dlmm.Q//dlmm.price(i,real['step']) for i in ids]
        amounts=[CAPITAL*w//sum(weights) for w in weights]
        for bid,amount in zip(ids,amounts):
            b=v['bins'].get(str(bid))
            if b is None:
                raise Unavailable('dlmm_missing_deposit_bin_array')
            if b['x' if sol_y else 'y']:
                raise ValueError('dlmm_non_sol_side_composition')
            x,y=(0,amount) if sol_y else (amount,0)
            share=dlmm.deposit_share(b,x,y)
            if share>>64==0 or share+b['supply']>dlmm.U128:
                raise ValueError('dlmm_invalid_deposit_share')
            shares[str(bid)]=share; starts[str(bid)]=dict(x=b['fee_x'],y=b['fee_y'])
            b['x']+=x; b['y']+=y; b['supply']+=share
            distribution.append(dict(bin=bid,x=x,y=y))
        p=dict(id=oid,surface='meteora-dlmm',pool=real['pool'],x=real['x'],y=real['y'],
            entry_slot=real['slot'],entry_time=now,entry_active_bin=real['active'],
            lower=min(ids),upper=max(ids),distribution_type='SpotOneSide',distribution=distribution,
            shares=shares,fee_start=starts,initial_x=0 if sol_y else sum(amounts),
            initial_y=sum(amounts) if sol_y else 0,shared_capital_reserved=RESERVATION,
            basis=CAPITAL+ENTRY_COST+EXIT_COST,rent=RENT,entry_cost=ENTRY_COST,
            exit_cost_reserve=EXIT_COST,idle_sol=CAPITAL-sum(amounts),real=real,virtual=v,
            cursor=[real['slot'],2**31-1,2**31-1],last_time=real['time'],events=0,lineage=digest(snapshot),
            stage='deposited',exit_reason=None,withdrawal=None,last_mark=None,unresolved=None,
            range_state='out_of_range',last_authoritative_slot=real['slot'])
        p['inventory']=inventory(p)
        with self.store.transaction('dlmm_replay_deposit') as s:
            s['liquidity_orders'][oid]['status']='open'; s['reserved']-=RESERVATION
            s['rent']+=RENT; s['fees']+=ENTRY_COST
            s['liquidity_positions'][oid]=p
        return deepcopy(p)

    def process(self,oid,event,now=None):
        return self._process(oid,event,now,False)

    def _process(self,oid,event,now,verified_real):
        """Complete synthetic mutation tape only, with a durable predecessor cursor.

        A current real snapshot may seed captured replay, but invented orders must
        still be labelled synthetic. Real historical attribution stays blocked
        until a complete on-chain mutation/prestate extractor is implemented.
        """
        _guard(self.store)
        p=self.store.state['liquidity_positions'][oid]
        # After withdrawal, advance the external market for residual liquidation;
        # inventory() preserves withdrawn assets and no LP fees accrue further.
        if event.get('kind')!='synthetic' and not (verified_real and event.get('kind')=='real'):
            raise Unavailable('dlmm_real_event_requires_verified_mutation_tape')
        # An offline tape uses its explicit availability time as replay clock;
        # callers advancing their own clock can require a stricter upper bound.
        now=event['available_time'] if now is None else now
        if not event['time']<=event['available_time']<=now:
            raise ValueError('dlmm_future_evidence')
        cursor=event['cursor']
        if len(cursor)!=3 or any(type(n) is not int or n<0 for n in cursor):
            raise ValueError('dlmm_invalid_cursor')
        if cursor<=p['cursor']:
            raise ValueError('dlmm_duplicate_or_out_of_order')
        if event['previous_cursor']!=p['cursor'] or event['prestate_hash']!=digest(p['real']):
            raise Unavailable('dlmm_history_gap_or_unmodeled_mutation')
        if event['pool']!=p['pool'] or event.get('commitment')!='finalized' or event['time']<p['last_time']:
            raise ValueError('dlmm_event_identity_or_time')
        real,observed=dlmm.swap(p['real'],event['amount'],event['for_y'],event['time'])
        if any(event['observed'][k]!=observed[k] for k in ('output','fee','protocol_fee','start','end')):
            raise ValueError('dlmm_observed_swap_mismatch')
        virtual,hypothetical=dlmm.swap(p['virtual'],event['amount'],event['for_y'],event['time'])
        with self.store.transaction('dlmm_replay_swap') as s:
            p=s['liquidity_positions'][oid]
            real['slot']=virtual['slot']=cursor[0]
            p.update(real=real,virtual=virtual,cursor=list(cursor),last_time=event['time'],
                events=p['events']+1,lineage=digest([p['lineage'],event]),last_mark=None,
                last_authoritative_slot=cursor[0],unresolved=None)
            p['range_state']='in_range' if p['lower']<=virtual['active']<=p['upper'] else 'out_of_range'
            p['inventory']=inventory(p)
        return hypothetical

    def _process_adjustment(self,oid,item,now):
        from .dlmm_tape import apply_external_adjustment
        _guard(self.store)
        p=self.store.state['liquidity_positions'][oid]
        if item.get('commitment')!='finalized' or item.get('pool')!=p['pool']:
            raise ValueError('dlmm_adjustment_identity')
        if not item['time']<=item['available_time']<=now or item['time']<p['last_time']:
            raise ValueError('dlmm_adjustment_time')
        cursor=item['cursor']
        if len(cursor)!=3 or any(type(n) is not int or n<0 for n in cursor):
            raise ValueError('dlmm_invalid_cursor')
        if cursor<=p['cursor']:
            raise ValueError('dlmm_duplicate_or_out_of_order')
        if item['previous_cursor']!=p['cursor'] or item['prestate_hash']!=digest(p['real']):
            raise Unavailable('dlmm_history_gap_or_unmodeled_mutation')
        real=apply_external_adjustment(p['real'],item,counterfactual=False)
        virtual=apply_external_adjustment(p['virtual'],item,counterfactual=True)
        with self.store.transaction('dlmm_replay_external_adjustment') as s:
            p=s['liquidity_positions'][oid]
            real['slot']=virtual['slot']=cursor[0]
            p.update(
                real=real,virtual=virtual,cursor=list(cursor),last_time=item['time'],
                events=p['events']+1,lineage=digest([p['lineage'],item]),
                last_mark=None,last_authoritative_slot=cursor[0],unresolved=None)
            p['range_state']='in_range' if p['lower']<=virtual['active']<=p['upper'] else 'out_of_range'
            p['inventory']=inventory(p)

    def process_tape(self,oid,tape,now):
        from .dlmm_tape import VerifiedTape, ordered_tape_actions
        _guard(self.store)
        p=self.store.state['liquidity_positions'][oid]
        if not isinstance(tape,VerifiedTape) or digest(tape.terminal)!=tape.end_hash:
            raise Unavailable('dlmm_tape_anchor_mismatch')
        if self.store.state['mode']!='captured':
            raise ValueError('dlmm_real_tape_requires_captured_store')
        actions=list(ordered_tape_actions(tape))
        if digest(p['real'])!=tape.start_hash:
            offsets=[i for i,(_kind,item) in enumerate(actions)
                     if item['prestate_hash']==digest(p['real'])
                     and item['previous_cursor']==p['cursor']]
            if offsets:
                actions=actions[offsets[0]:]
            elif actions and p['cursor']==actions[-1][1]['cursor']:
                expected=deepcopy(tape.terminal)
                expected.update(slot=p['real']['slot'],time=p['real']['time'])
                if expected!=p['real']:
                    raise Unavailable('dlmm_tape_anchor_mismatch')
                actions=[]
            else:
                raise Unavailable('dlmm_tape_anchor_mismatch')
        for kind,item in actions:
            if kind=='swap':
                self._process(oid,item,now,True)
            else:
                self._process_adjustment(oid,item,now)
        with self.store.transaction('dlmm_verified_interval_end') as s:
            p=s['liquidity_positions'][oid]
            if tape.terminal['time']<p['last_time']:
                raise ValueError('dlmm_interval_time_regression')
            mismatches=[key for key in set(p['real'])-{'time','slot'}
                        if p['real'][key]!=tape.terminal[key]]
            if mismatches:
                raise Unavailable(
                    'dlmm_tape_terminal_checkpoint_mismatch:'+mismatches[0])
            p.update(
                real=deepcopy(tape.terminal),
                cursor=[tape.terminal['slot'],2**31-1,2**31-1],
                last_time=tape.terminal['time'],
                last_authoritative_slot=tape.terminal['slot'],
                lineage=digest([p['lineage'],tape.lineage]),
                unresolved=None,last_mark=None)
            p['virtual']['slot']=tape.terminal['slot']
            p['virtual']['time']=tape.terminal['time']


    def unresolved(self,oid,reason,now):
        # Coalesce repeated provider gaps without pretending inventory advanced.
        p=self.store.state['liquidity_positions'][oid]
        if p['unresolved']==reason and now-p.get('unresolved_recorded',0)<60:
            return
        with self.store.transaction('dlmm_unresolved') as s:
            p=s['liquidity_positions'][oid]
            p.update(unresolved=reason[:120],unresolved_recorded=now,last_mark=None)

    def mark(self,oid,now):
        p=self.store.state['liquidity_positions'][oid]
        try:
            result=_executable_mark(p,now)
        except (Unavailable,ValueError) as exc:
            return dict(resolved=False,reason=str(exc),net_sol=None)
        prior=p['last_mark']
        if prior is None or now-prior['time']>=60:
            with self.store.transaction('dlmm_executable_mark') as s:
                s['liquidity_positions'][oid]['last_mark']=result
        return result

    def monitor(self,oid,now):
        p=self.store.state['liquidity_positions'][oid]
        mark=self.mark(oid,now)
        if p['stage']=='deposited' and now>=p['entry_time']+HOLD_SECONDS:
            self.exit_intent(oid,'fixed_mechanical_horizon',now)
        return dict(active_bin=p['virtual']['active'],range_state=p['range_state'],
            inventory=inventory(p),mark=mark,unresolved=p['unresolved'],cursor=p['cursor'])

    def exit_intent(self,oid,reason,now):
        p=self.store.state['liquidity_positions'][oid]
        if p['stage']!='deposited' or now<p['last_time']:
            raise ValueError('dlmm_exit_stage_or_time')
        with self.store.transaction('dlmm_exit_intent') as s:
            s['liquidity_positions'][oid].update(stage='exit_intent',exit_reason=reason[:120],exit_time=now)

    def withdraw(self,oid,now):
        p=self.store.state['liquidity_positions'][oid]
        if p['stage']!='exit_intent' or now<p['exit_time']:
            raise ValueError('dlmm_withdraw_stage_or_time')
        if p['unresolved'] or now-p['last_time']>dlmm.MAX_AGE:
            raise Unavailable('dlmm_unresolved_withdrawal')
        virtual,assets=_withdraw_preview(p)
        with self.store.transaction('dlmm_withdrawal') as s:
            s['liquidity_positions'][oid].update(stage='withdrawn',virtual=virtual,
                withdrawal=assets,withdrawal_time=now,last_mark=None)
        return assets

    def settle(self,oid,now):
        p=self.store.state['liquidity_positions'].get(oid)
        if p is None or p['stage']!='withdrawn' or now<p['withdrawal_time']:
            raise ValueError('dlmm_settlement_stage_or_duplicate')
        mark=_executable_mark(p,now)
        with self.store.transaction('dlmm_sol_settlement') as s:
            p=s['liquidity_positions'].pop(oid)
            pnl=mark['net_sol']-p['basis']
            s['cash']+=mark['net_sol']+p['rent']; s['rent']-=p['rent']
            s['realized']+=pnl; s['fees']+=EXIT_COST
            s['liquidity_orders'][oid].update(status='settled',settlement=dict(
                sol=mark['net_sol'],rent=p['rent'],basis=p['basis'],realized=pnl,
                costs=ENTRY_COST+EXIT_COST,assets=mark['assets'],liquidation=mark['liquidation'],
                time=now,cursor=p['cursor'],lineage=p['lineage']))
        return deepcopy(self.store.state['liquidity_orders'][oid]['settlement'])


def monitoring_tick(store,adapter,now,discovery_addresses=()):
    """Existing LP evidence work precedes any discretionary discovery.

    Live event reconstruction is deliberately unresolved until a complete mutation
    tape exists. A newer snapshot never rewrites past inventory or awards fees.
    """
    for oid,p in list(store.state.get('liquidity_positions',{}).items()):
        try:
            snap=adapter.snapshot(p['pool'],now,priority=True)
            tape=adapter.swap_history(p['real'],p['cursor'],end_snapshot=snap,now=now,priority=True)
            Replay(store).process_tape(oid,tape,now)
        except (Unavailable,ValueError,KeyError,TypeError):
            Replay(store).unresolved(oid,'dlmm_complete_mutation_history_unavailable',now)
    if store.state.get('liquidity_positions'):
        return dict(discovery_deferred=True,allocation_enabled=False)
    return adapter.discover(discovery_addresses,now)
