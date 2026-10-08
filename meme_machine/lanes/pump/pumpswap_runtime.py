"""Durable prospective Pump -> canonical PumpSwap paper continuity.

This module does not qualify or allocate new exposure. It only carries an already
reserved/open continuation-v1 Pump paper lifecycle across a verified graduation into
the deterministic canonical PumpSwap pool. Legacy Raydium is intentionally absent.
"""
from dataclasses import asdict
import time

from .engine import DELAY, GAS, RENT, UNRESOLVED_RECORD_INTERVAL
from .postgrad import (
    GraduationHandoff, PUMPSWAP_MODEL, buy_quote, graduation_handoff,
    sell_quote, validate_postgrad_snapshot,
)
from .provider import Unavailable


POSTGRAD_WAIT_SECONDS = 60


class PumpSwapPaperRuntime:
    """Continue existing Pump paper orders/positions after canonical graduation."""
    def __init__(self, store, adapter, clock=time.time):
        self.store = store
        self.adapter = adapter
        self.clock = clock

    def _now(self):
        return int(self.clock())

    @staticmethod
    def _decode_handoff(value):
        if not isinstance(value, dict):
            return None
        try:
            return GraduationHandoff(**value)
        except (TypeError, KeyError):
            return None

    def handoff_from_snapshot(self, snapshot):
        """Return a verified handoff for a completed Pump snapshot, else None."""
        now=max(self._now(), int(snapshot.get('available_time', 0)))
        try:
            return graduation_handoff(snapshot, now)
        except ValueError as exc:
            if str(exc) == 'bonding_curve_not_complete':
                return None
            raise

    def _remember_handoff(self, container, key, handoff, now):
        target=self.store.state[container].get(key)
        if target is None:
            return
        encoded=asdict(handoff)
        if target.get('postgrad_handoff') == encoded:
            return
        with self.store.transaction('pumpswap_graduation_handoff'):
            target=self.store.state[container].get(key)
            if target is None:
                return
            target['postgrad_handoff']=encoded
            target['postgrad_target']='pumpswap'
            target['graduation_observed']=now
            if container == 'positions':
                target['surface']='graduating-pumpswap'
                target['model']=PUMPSWAP_MODEL

    def _discover_handoff(self, container, key, mint, graduation_snapshot=None):
        target=self.store.state[container].get(key)
        if target is None:
            return None
        remembered=self._decode_handoff(target.get('postgrad_handoff'))
        if remembered is not None:
            if remembered.mint != mint:
                raise ValueError('stored_handoff_identity')
            return remembered
        if graduation_snapshot is not None:
            handoff=self.handoff_from_snapshot(graduation_snapshot)
            if handoff is None:
                return None
            observed=max(self._now(), int(graduation_snapshot.get('available_time',0)))
        else:
            observed=self._now()
            try:
                snapshot=self.adapter.graduation_snapshot(mint, observed, priority=True)
            except ValueError as exc:
                if str(exc) == 'bonding_curve_not_complete':
                    return None
                raise
            handoff=graduation_handoff(snapshot, max(self._now(), int(snapshot['available_time'])))
            observed=max(self._now(), int(snapshot['available_time']))
        if handoff.mint != mint:
            raise ValueError('graduation_handoff_identity')
        self._remember_handoff(container,key,handoff,observed)
        return handoff

    def _snapshot(self, handoff):
        observed=self._now()
        snapshot=self.adapter.pumpswap_snapshot(handoff, observed, priority=True)
        observed=max(self._now(), int(snapshot.get('available_time',0)))
        validate_postgrad_snapshot(snapshot, observed, self.store.state['mode'])
        if snapshot['surface'] != 'pumpswap' or snapshot['mint'] != handoff.mint:
            raise ValueError('canonical_pumpswap_identity')
        return snapshot,observed

    def _defer_or_cancel(self, oid, now, reason):
        order=self.store.state['orders'].get(oid)
        if order is None or order['status'] != 'reserved':
            return 'closed'
        if now-int(order['created']) <= POSTGRAD_WAIT_SECONDS:
            return 'waiting_postgrad'
        with self.store.transaction('pumpswap_entry_timeout'):
            s=self.store.state
            order=s['orders'][oid]
            if order['status'] != 'reserved':
                return order['status']
            s['reserved']-=order['reservation']
            s['cash']+=order['reservation']
            order.update(status='cancelled',reason=reason)
        return 'cancelled'

    def fill_existing_order(self, oid, graduation_snapshot=None, failed=False):
        """Fill an already-authorized Pump order on PumpSwap after graduation.

        No new reservation is created here. The unchanged Pump qualification and shared
        allocator must already have created the durable reservation.
        """
        order=self.store.state['orders'].get(oid)
        if order is None:
            return 'closed'
        if order['status'] != 'reserved':
            return order['status']
        now=self._now()
        if now < int(order['due']):
            return 'waiting'
        try:
            handoff=self._discover_handoff('orders',oid,order['mint'],graduation_snapshot)
            if handoff is None:
                return 'not_graduated'
            snapshot,now=self._snapshot(handoff)
        except Unavailable:
            return self._defer_or_cancel(oid,self._now(),'pumpswap_quote_unavailable')
        except (ValueError,KeyError,TypeError):
            return self._defer_or_cancel(oid,self._now(),'pumpswap_evidence_invalid')

        order=self.store.state['orders'][oid]
        if snapshot['market_time'] < order['due'] or snapshot['slot'] <= order['slot']:
            return self._defer_or_cancel(oid,now,'no_post_delay_pumpswap_quote')
        try:
            quote=buy_quote(snapshot,order['budget'])
            if quote.output_amount < order['min_tokens'] or failed:
                raise ValueError('simulated_attempt_failed' if failed else 'entry_slippage')
            error=None
        except (ValueError,KeyError,TypeError) as exc:
            error=str(exc)

        with self.store.transaction('pumpswap_entry_attempt'):
            s=self.store.state
            order=s['orders'][oid]
            if order['status'] != 'reserved':
                return order['status']
            s['reserved']-=order['reservation']
            if error:
                charge=GAS if failed else 0
                s['cash']+=order['reservation']-charge
                s['fees']+=charge
                s['realized']-=charge
                order.update(status='cancelled',reason=error)
                return 'cancelled'
            cost=quote.input_amount
            s['cash']+=order['reservation']-cost-GAS-RENT
            s['rent']+=RENT
            s['fees']+=quote.fee_amount+GAS
            s['positions'][order['mint']]=dict(
                kind='spot',chain='solana-mainnet',surface='pumpswap',
                model=PUMPSWAP_MODEL,pool=snapshot['pool'],tokens=quote.output_amount,
                basis=cost+GAS,rent=RENT,opened=now,related=order['related'],
                entry_slot=snapshot['slot'],next_monitor=now+5,mark=None,mark_time=None,
                unresolved=False,last_unresolved_record=0,exit_due=None,exit_reason=None,
                postgrad_handoff=asdict(handoff),postgrad_target='pumpswap',
                graduation_observed=order.get('graduation_observed',now),
            )
            s['entry_count']+=1
            s['funnel']['entries']+=1
            order.update(
                status='settled',surface='pumpswap',model=PUMPSWAP_MODEL,
                postgrad_handoff=asdict(handoff),
                fill=dict(tokens=quote.output_amount,cost=cost,fee=quote.fee_amount,gas=GAS,
                          slot=snapshot['slot'],market_time=snapshot['market_time'],
                          available_time=snapshot['available_time'],time=now,surface='pumpswap'),
                fill_snapshot=snapshot,
            )
        return 'settled'

    def _mark_unresolved(self, mint, now, reason):
        position=self.store.state['positions'].get(mint)
        if position is None:
            return 'closed'
        if (position.get('unresolved') and
                now-int(position.get('last_unresolved_record',0)) < UNRESOLVED_RECORD_INTERVAL):
            return 'unresolved_coalesced'
        with self.store.transaction('pumpswap_monitor_unavailable'):
            s=self.store.state
            position=s['positions'].get(mint)
            if position is None:
                return 'closed'
            position.update(
                next_monitor=now+5,mark=None,mark_time=None,unresolved=True,
                last_unresolved_record=now,postgrad_error=reason,
                last_exit_error=dict(reason=reason,time=now,stage='pumpswap_exit_quote'),
            )
            s['counts']['unavailable_exit']=s['counts'].get('unavailable_exit',0)+1
            key=f'unavailable_exit:{reason}'
            s['counts'][key]=s['counts'].get(key,0)+1
        return 'unresolved'

    def monitor_existing_position(self, mint, graduation_snapshot=None, failed=False):
        """Monitor/exit an existing Pump position on canonical PumpSwap after migration."""
        position=self.store.state['positions'].get(mint)
        if position is None:
            return 'closed'
        now=self._now()
        if now < int(position['next_monitor']):
            return 'not_due'
        try:
            handoff=self._discover_handoff('positions',mint,mint,graduation_snapshot)
            if handoff is None:
                return 'not_graduated'
            snapshot,now=self._snapshot(handoff)
            position=self.store.state['positions'][mint]
            if snapshot['slot'] < int(position['entry_slot']):
                raise ValueError('position_quote_slot')
            quote=sell_quote(snapshot,position['tokens'])
        except Unavailable:
            return self._mark_unresolved(mint,self._now(),'pumpswap_quote_unavailable')
        except (ValueError,KeyError,TypeError) as exc:
            return self._mark_unresolved(mint,self._now(),str(exc) or 'pumpswap_evidence_invalid')

        with self.store.transaction('pumpswap_monitor'):
            s=self.store.state
            position=s['positions'].get(mint)
            if position is None:
                return 'closed'
            position.update(
                surface='pumpswap',model=PUMPSWAP_MODEL,pool=snapshot['pool'],
                postgrad_handoff=asdict(handoff),postgrad_target='pumpswap',
                next_monitor=now+5,mark=max(0,quote.output_amount-GAS),mark_time=now,
                unresolved=False,last_unresolved_record=0,postgrad_error=None,last_exit_error=None,
            )
            proceeds=quote.output_amount
            reason=(
                'risk' if proceeds-GAS <= position['basis']*9000//10000 else
                'take_profit' if proceeds-GAS >= position['basis']*11500//10000 else
                'timeout' if now-position['opened'] >= 900 else
                'liquidity_invalidation' if int(snapshot['state']['quote_reserve']) < 5_000_000_000
                else None
            )
            if position['exit_due'] is None and reason:
                position.update(exit_due=now+DELAY,exit_reason=reason,exit_slot=snapshot['slot'])
                return 'exit_intended'
            if (position['exit_due'] is None or now < position['exit_due'] or
                    snapshot['market_time'] < position['exit_due'] or
                    snapshot['slot'] <= position['exit_slot']):
                return 'holding'
            if failed:
                if s['cash'] < GAS:
                    position['unresolved']=True
                    return 'gas_exhausted'
                s['cash']-=GAS
                s['realized']-=GAS
                s['fees']+=GAS
                position['unresolved']=True
                return 'exit_failed'
            s['cash']+=proceeds-GAS+position['rent']
            s['rent']-=position['rent']
            s['realized']+=proceeds-GAS-position['basis']
            s['fees']+=quote.fee_amount+GAS
            for order in s['orders'].values():
                if order['mint']==mint and order['status']=='settled' and 'exit' not in order:
                    order['exit']=dict(
                        reason=position['exit_reason'],proceeds=proceeds,
                        fee=quote.fee_amount,gas=GAS,
                        realized=proceeds-GAS-position['basis'],time=now,
                        surface='pumpswap',snapshot=snapshot,
                    )
            del s['positions'][mint]
            s['funnel']['settled_exits']+=1
        return 'settled'

    def status(self):
        positions=self.store.state['positions'].values()
        orders=self.store.state['orders'].values()
        return dict(
            enabled=True,
            surface='pumpswap',
            new_allocation_authority=False,
            legacy_raydium_authority=False,
            transitioned_positions=sum(p.get('surface')=='pumpswap' for p in positions),
            graduating_positions=sum(p.get('surface')=='graduating-pumpswap' for p in positions),
            transitioning_orders=sum(bool(o.get('postgrad_handoff')) and o.get('status')=='reserved'
                                     for o in orders),
        )
