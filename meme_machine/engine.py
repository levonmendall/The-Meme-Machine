"""Versioned policy, shared capital, delayed fills, scheduled exits."""
from dataclasses import dataclass
from . import pump
from .store import digest
from .wallets import observe

GAS = 50_000                 # Conservative per simulated transaction, incl priority fee.
RENT = 2_100_000             # Refundable SPL token account capital, separate from fees.
DELAY = 2
MAX_AGE = 20
SIGNAL_WINDOW = 60


@dataclass(frozen=True)
class LiquidityPosition:
    chain: str
    pool: str
    token_units: dict
    shares: dict
    cost_basis_lamports: int


class Allocator:
    def __init__(self, store):
        self.store = store

    def allowed(self, kind, amount, mint, related, now=None):
        s = self.store.state
        if kind != 'spot':
            return 'dlmm_disabled'
        observed_now = s.get('last_time',0) if now is None else now
        if observed_now < s.get('entry_quarantine_until',0):
            return 'unresolved_data_gap'
        if mint in s['positions'] or any(o['mint']==mint and o['status']=='reserved' for o in s['orders'].values()):
            return 'token_exposure'
        if any(o['mint']==mint and o['status']=='settled' for o in s['orders'].values()):
            return 'reentry_deferred'
        if any(o['related']==related and o['status']=='reserved' for o in s['orders'].values()):
            return 'related_exposure'
        if any(p['related']==related for p in s['positions'].values()):
            return 'related_exposure'
        active = len(s['positions'])+sum(o['status']=='reserved' for o in s['orders'].values())
        if active >= 4 or amount > s['initial']//20:
            return 'aggregate_exposure'
        if s['cash']-amount-GAS-RENT < s['initial']//10:
            return 'capital_or_gas_reserve'
        if self.store.pressure():
            return 'storage_or_experiment_limit'
        return None


class Engine:
    def __init__(self, store, seeds, groups=None):
        if len(seeds)>8:
            raise ValueError('seed_limit')
        self.store,self.seeds,self.groups = store,set(seeds),groups or {}
        for address in seeds:
            pump.un58(address)
        identity=digest(dict(seeds=sorted(seeds),groups=self.groups))
        if 'scout_config' in store.state and store.state['scout_config']!=identity:
            raise ValueError('scout_configuration_changed')
        if 'scout_config' not in store.state:
            with store.transaction('scout_configuration'):
                store.state['scout_config']=identity
        self.allocator = Allocator(store)

    def group(self, wallet):
        return self.groups.get(wallet,wallet)

    def note(self, reason, mint, now):
        s = self.store.state
        s['counts'][reason]=s['counts'].get(reason,0)+1
        s['decisions'].append(dict(reason=reason,mint=mint,time=now))
        s['decisions']=s['decisions'][-100:]

    def quarantine(self, reason, now, seconds=SIGNAL_WINDOW):
        """Fail closed only for the signal window that could contain unseen events.

        Gap history is retained for diagnosis, while new exposure automatically
        becomes eligible again only after the missed 60-second nomination window
        has fully aged out. Existing positions remain monitorable throughout.
        Caller must hold a Store transaction.
        """
        s=self.store.state
        until=now+seconds
        s['entry_quarantine_until']=max(s.get('entry_quarantine_until',0),until)
        s['gaps']=(s['gaps']+[dict(reason=reason,time=now,until=until)])[-20:]

    def validate_snapshot(self, snap, now):
        s = self.store.state
        if snap['network']!='solana-mainnet' or snap['protocol']!='pump.fun':
            raise ValueError('unsupported_scope')
        if snap['kind'] != ('real' if s['mode']=='prospective' else s['mode']):
            raise ValueError('experiment_contamination')
        if not snap['market_time'] <= snap['available_time'] <= now or now-snap['market_time']>MAX_AGE:
            raise ValueError('stale_or_future_quote')
        if snap['pool'] != pump.pda([b'bonding-curve',pump.un58(snap['mint'])]):
            raise ValueError('pool_identity')
        c = pump.curve(snap['accounts'][0])
        supply,decimals = pump.mint_info(snap['accounts'][1])
        pump.validate_mint_supply(snap['accounts'][0],c,supply,decimals)
        return c,pump.fees(snap['accounts'][2],c,supply)

    def scout(self, events, now):
        nominations = []
        with self.store.transaction('scout'):
            s = self.store.state
            f=s['funnel'];f['scout_batches']+=1
            if now < s['last_time']:
                raise ValueError('time_regression')
            s['last_time']=now
            for e in events[:100]:
                if not e['market_time'] <= e['available_time'] <= now:
                    raise ValueError('future_event')
                h = digest({k:v for k,v in e.items() if k!='available_time'})
                prior = s['seen'].get(e['id'])
                if prior:
                    if prior['hash']!=h:
                        raise ValueError('conflicting_event')
                    continue
                s['seen'][e['id']]=dict(hash=h,time=e['market_time'])
                f['observed_events']+=1
                if e['wallet'] in self.seeds:
                    f['seed_events']+=1
                    w=s['wallets'].setdefault(e['wallet'],dict(nominations=0,skill='unvalidated',sizing_influence=0))
                    observe(w,e)
                if e.get('type','trade')=='trade' and e['wallet'] in self.seeds and e['buy'] and now-e['market_time']<=SIGNAL_WINDOW:
                    nominations.append(e)
                    f['nominations']+=1
                    w=s['wallets'].setdefault(e['wallet'],dict(nominations=0,skill='unvalidated',sizing_influence=0))
                    w['nominations']+=1
            # Dedup lifetime exceeds signal eligibility; old events cannot trigger entries.
            s['seen']={k:v for k,v in s['seen'].items() if now-v['time']<=120}
            if len(s['seen'])>1000:
                s['seen']=dict(list(s['seen'].items())[-1000:])
                self.quarantine('dedup_capacity',now)
            if len(events)>100:
                self.quarantine('intake_capacity',now)
            s['progress']+=1
        return nominations

    def qualify(self, nomination, evidence, now):
        snap=evidence['snapshot']
        c,rates=self.validate_snapshot(snap,now)
        if nomination['mint']!=snap['mint'] or nomination['wallet'] not in self.seeds:
            return 'invalid_nomination'
        if not nomination['market_time'] <= nomination['available_time'] <= now or now-nomination['market_time']>SIGNAL_WINDOW:
            return 'stale_signal'
        if not evidence.get('covered'):
            return 'incomplete_market_window'
        if evidence.get('concentration_bps') is None:
            return 'missing_concentration'
        if evidence['concentration_bps']>3500:
            return 'concentration'
        if c.complete or c.real_sol<10_000_000_000:
            return 'exit_liquidity'
        excluded={self.group(nomination['wallet']),self.group(c.creator)}
        participants=set()
        net=0
        events=evidence['events']
        if len(events)>100:
            return 'evidence_capacity'
        seen={}
        for e in events:
            if e['id'] in seen:
                if seen[e['id']]!=digest(e):
                    return 'conflicting_market_event'
                continue
            seen[e['id']]=digest(e)
            if e['amount']<=0 or e['tokens']<=0:
                return 'invalid_trade_amount'
            if e['mint']!=snap['mint'] or not now-SIGNAL_WINDOW <= e['market_time'] <= e['available_time'] <= now or e['slot']>snap['slot']:
                return 'invalid_market_window'
            if self.group(e['wallet']) in excluded:
                continue
            net+=e['amount']*(1 if e['buy'] else -1)
            if e['buy']:
                participants.add(self.group(e['wallet']))
        if len(participants)<3 or net<1_000_000_000:
            return 'independent_demand'
        # No leader price credited: entry is quoted at current reserves after observation.
        if nomination['tokens']<=0 or c.sol*nomination['tokens']*10000 > c.token*nomination['amount']*12000:
            return 'extended_price'
        amount=self.store.state['initial']//20
        tokens,cost,_=pump.buy(c,amount,rates)
        proceeds,_=pump.sell(c,tokens,rates)
        if (cost+2*GAS-proceeds)*10000 > cost*500:
            return 'roundtrip_cost'
        return self.allocator.allowed('spot',amount,snap['mint'],self.group(c.creator),now) or 'qualified'

    def consider(self, nomination, evidence, now):
        oid=nomination['id']
        if oid in self.store.state['orders']:
            return self.store.state['orders'][oid]['status']
        try:
            reason=self.qualify(nomination,evidence,now)
        except (ValueError,KeyError,TypeError):
            reason='unavailable_executable_evidence'
        with self.store.transaction('qualification'):
            s=self.store.state
            s['funnel']['qualification_attempts']+=1
            self.note(reason,nomination['mint'],now)
            if reason=='qualified':
                s['funnel']['qualified']+=1
                amount=s['initial']//20
                reservation=amount+GAS+RENT
                tokens,_,_=pump.buy(*self._quote_args(evidence['snapshot'],now,amount))
                c,_=self.validate_snapshot(evidence['snapshot'],now)
                s['cash']-=reservation
                s['reserved']+=reservation
                s['orders'][oid]=dict(status='reserved',mint=nomination['mint'],related=self.group(c.creator),
                    reservation=reservation,budget=amount,min_tokens=tokens*9900//10000,
                    created=now,due=now+DELAY,slot=evidence['snapshot']['slot'],
                    evidence=evidence,nomination=nomination)
        return reason

    def _quote_args(self,snap,now,amount):
        c,rates=self.validate_snapshot(snap,now)
        return c,amount,rates

    def fill(self,oid,snap,now,failed=False):
        o=self.store.state['orders'][oid]
        if o['status']!='reserved':
            return o['status']
        if now<o['due']:
            return 'waiting'
        error=None
        try:
            c,rates=self.validate_snapshot(snap,now)
            if snap['mint']!=o['mint']:
                raise ValueError('fill_identity')
            if snap['market_time']<o['due'] or snap['slot']<=o['slot']:
                if now-o['created'] <= 60:
                    return 'waiting'
                raise ValueError('no_post_delay_quote')
            tokens,cost,fee=pump.buy(c,o['budget'],rates)
            if tokens<o['min_tokens'] or failed:
                raise ValueError('simulated_attempt_failed')
        except (ValueError,KeyError,TypeError) as exc:
            error=str(exc)
        with self.store.transaction('entry_attempt'):
            s=self.store.state
            s['reserved']-=o['reservation']
            if error:
                charge=GAS if failed else 0
                s['cash']+=o['reservation']-charge
                s['fees']+=charge
                s['realized']-=charge
                o.update(status='cancelled',reason=error)
                self.note('entry_failed',o['mint'],now)
            else:
                s['cash']+=o['reservation']-cost-GAS-RENT
                s['rent']+=RENT
                s['fees']+=fee+GAS
                s['positions'][o['mint']]=dict(kind='spot',chain='solana-mainnet',tokens=tokens,basis=cost+GAS,
                    rent=RENT,opened=now,related=o['related'],entry_slot=snap['slot'],next_monitor=now+5,
                    mark=None,mark_time=None,unresolved=False,exit_due=None,exit_reason=None)
                s['entry_count']+=1
                s['funnel']['entries']+=1
                o.update(status='settled',fill=dict(tokens=tokens,cost=cost,fee=fee,gas=GAS,
                    slot=snap['slot'],market_time=snap['market_time'],available_time=snap['available_time'],time=now),fill_snapshot=snap)
        return o['status']

    def monitor(self,mint,snap,now,failed=False):
        p=self.store.state['positions'].get(mint)
        if p is None:
            return 'closed'
        if now<p['next_monitor']:
            return 'not_due'
        error=None
        try:
            c,rates=self.validate_snapshot(snap,now)
            if snap['mint']!=mint or snap['slot']<p['entry_slot']:
                raise ValueError('position_quote_identity')
            proceeds,fee=pump.sell(c,p['tokens'],rates)
        except (ValueError,KeyError,TypeError) as exc:
            error=str(exc)
        with self.store.transaction('monitor'):
            s=self.store.state
            p['next_monitor']=now+5
            if error:
                p.update(mark=None,mark_time=None,unresolved=True)
                self.note('unavailable_exit',mint,now)
                return 'unresolved'
            p.update(mark=max(0,proceeds-GAS),mark_time=now,unresolved=False)
            reason = ('risk' if proceeds-GAS<=p['basis']*9000//10000 else
                      'take_profit' if proceeds-GAS>=p['basis']*11500//10000 else
                      'timeout' if now-p['opened']>=900 else
                      'liquidity_invalidation' if c.real_sol<5_000_000_000 else None)
            if p['exit_due'] is None and reason:
                p.update(exit_due=now+DELAY,exit_reason=reason,exit_slot=snap['slot'])
                return 'exit_intended'
            if p['exit_due'] is None or now<p['exit_due'] or snap['market_time']<p['exit_due'] or snap['slot']<=p['exit_slot']:
                return 'holding'
            if failed:
                # Failed exits consume fees but retain the position and its exit intent.
                if s['cash']<GAS:
                    p['unresolved']=True
                    return 'gas_exhausted'
                s['cash']-=GAS
                s['realized']-=GAS
                s['fees']+=GAS
                p['unresolved']=True
                return 'exit_failed'
            s['cash']+=proceeds-GAS+p['rent']
            s['rent']-=p['rent']
            s['realized']+=proceeds-GAS-p['basis']
            s['fees']+=fee+GAS
            for order in s['orders'].values():
                if order['mint']==mint and order['status']=='settled' and 'exit' not in order:
                    order['exit']=dict(reason=p['exit_reason'],proceeds=proceeds,fee=fee,gas=GAS,
                                       realized=proceeds-GAS-p['basis'],time=now,snapshot=snap)
            del s['positions'][mint]
            s['funnel']['settled_exits']+=1
            self.note('settled_exit',mint,now)
            return 'settled'

    def status(self,now):
        s=self.store.state
        positions={k:dict(v) for k,v in s['positions'].items()}
        for p in positions.values():
            if p['mark_time'] is None or now-p['mark_time']>MAX_AGE:
                p['mark']=None
        marks=[p['mark'] for p in positions.values()]
        quarantined=now < s.get('entry_quarantine_until',0)
        return dict(live=True,ready=not quarantined and s['progress']>0 and now-s['last_time']<=MAX_AGE,
            operational_acceptance=False,profitability_evidence=False,policy=s['policy'],model=s['model'],
            mode=s['mode'],network='solana-mainnet',initial_usd_micros=s['initial_usd_micros'],
            cash_lamports=s['cash'],reserved_lamports=s['reserved'],rent_lamports=s['rent'],
            realized_lamports=s['realized'],fees_lamports=s['fees'],positions=positions,
            unrealized_lamports=None if any(m is None for m in marks) else sum(marks)-sum(p['basis'] for p in positions.values()),
            current_usd_value=None,counts=s['counts'],decisions=s['decisions'][-10:],gaps=s['gaps'],
            entry_quarantine_until=s.get('entry_quarantine_until',0),active_entry_quarantine=quarantined,
            funnel=dict(s['funnel']),progress=s['progress'],coverage=s.get('coverage',{}),wallets=s['wallets'],
            provider=s['provider'],dlmm_enabled=False,pressure=self.store.pressure())
