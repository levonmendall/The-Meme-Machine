"""Restart-safe isolated paper state machine driven by time-bound executable quotes.

No Robinhood-native policy is empirically established. Synthetic decisions exercise
the lifecycle; natural/captured allocation stays blocked until that separate gate.
"""
from dataclasses import asdict, dataclass
import json

from . import BoundaryError
from .evidence import Stamp, canonical


@dataclass(frozen=True)
class Quote:
    market: str
    side: str
    amount_in: int
    amount_out: int | None
    gas_quote: int
    fee_quote: int
    stamp: Stamp
    reason: str | None = None

    def check(self, now, market, side, amount, kind):
        self.stamp.check(now, 5)
        if self.market != market or self.side != side or self.amount_in != amount or self.stamp.kind != kind:
            raise BoundaryError('quote_identity_mismatch')
        if min(self.amount_in, self.gas_quote, self.fee_quote) < 0:
            raise BoundaryError('negative_quote_accounting')
        if self.amount_out is None:
            raise BoundaryError(self.reason or 'unavailable_executable_quote')
        if self.amount_out <= 0 or self.reason is not None:
            raise BoundaryError('invalid_quote')


class Paper:
    def __init__(self, store, experiment, capital, *, delay=2):
        if capital <= 0 or delay < 1:
            raise BoundaryError('invalid_paper_config')
        self.store, self.experiment, self.delay = store, experiment, delay
        self.store.put('paper_genesis', experiment, dict(capital=capital, delay=delay,
            authority='isolated_robinhood_directional', shared_allocator=False))

    def positions(self):
        return [json.loads(r[0]) for r in self.store.db.execute('SELECT body FROM paper')
                if json.loads(r[0])['experiment'] == self.experiment]

    def reconcile(self):
        genesis = self.store.get('paper_genesis', self.experiment)['capital']
        rows = self.positions()
        realized = sum(p['pnl'] for p in rows if p['status'] == 'settled')
        committed = sum(p['reserved'] for p in rows if p['status'] != 'settled')
        available = genesis + realized - committed
        if available < 0:
            raise BoundaryError('paper_capital_invariant')
        return dict(genesis=genesis, realized=realized, committed=committed, available=available,
                    open_exposure=sum(p['tokens'] for p in rows if p['status'] != 'settled'))

    def _get(self, identity):
        row = self.store.db.execute('SELECT body FROM paper WHERE id=?', (identity,)).fetchone()
        if not row:
            raise BoundaryError('paper_position_missing')
        p = json.loads(row[0])
        if p['experiment'] != self.experiment:
            raise BoundaryError('cross_experiment_authority')
        return p

    def _save(self, p, action, now):
        self.store.put('paper_journal', f'{p["id"]}:{p["version"]}', dict(action=action, at=now, position=p))
        self.store.db.execute('INSERT OR REPLACE INTO paper VALUES(?,?)', (p['id'], canonical(p)))

    def reserve(self, identity, *, market, amount, gas_budget, now, features, kind='synthetic'):
        if kind != 'synthetic':
            raise BoundaryError('native_policy_not_established')
        if features['asof'] != now or features['market'] != market or amount <= 0 or gas_budget < 0:
            raise BoundaryError('invalid_paper_decision')
        self.store.db.execute('BEGIN IMMEDIATE')
        try:
            if self.store.db.execute('SELECT 1 FROM paper WHERE id=?', (identity,)).fetchone():
                raise BoundaryError('duplicate_reservation')
            if amount + gas_budget > self.reconcile()['available']:
                raise BoundaryError('isolated_capital_exhausted')
            if len(self.positions()) >= 100:
                raise BoundaryError('paper_position_capacity')
            p = dict(id=identity, experiment=self.experiment, market=market, kind=kind,
                     status='reserved', reserved=amount+gas_budget, amount=amount,
                     due=now+self.delay, tokens=0, cost=0, pnl=0, version=0,
                     last_at=now, reason=None)
            self.store.put('paper_decision', identity, features)
            self._save(p, 'reserve', now)
            self.store.db.execute('COMMIT')
        except Exception:
            self.store.db.execute('ROLLBACK')
            raise
        return p

    def advance(self, identity, *, now, action, quote=None, transition=None):
        self.store.db.execute('BEGIN IMMEDIATE')
        try:
            p = self._get(identity)
            if now < p['last_at']:
                raise BoundaryError('paper_time_regression')
            if action == 'entry':
                if p['status'] != 'reserved' or now < p['due']:
                    raise BoundaryError('entry_not_due')
                quote.check(now, p['market'], 'buy', p['amount'], p['kind'])
                if quote.stamp.event_at < p['due']:
                    raise BoundaryError('pre_delay_quote')
                cost = p['amount'] + quote.gas_quote
                if cost > p['reserved']:
                    raise BoundaryError('entry_exceeds_reservation')
                p.update(tokens=quote.amount_out, cost=cost, status='open')
            elif action == 'exit_intent':
                if p['status'] != 'open':
                    raise BoundaryError('position_not_open')
                p.update(status='exit_pending', due=now+self.delay)
            elif action == 'exit':
                if p['status'] != 'exit_pending' or now < p['due']:
                    raise BoundaryError('exit_not_due')
                try:
                    quote.check(now, p['market'], 'sell', p['tokens'], p['kind'])
                    if quote.stamp.event_at < p['due']:
                        raise BoundaryError('pre_delay_quote')
                except BoundaryError as exc:
                    # Exposure persists. Identical repeated failures coalesce into latest state.
                    if p['reason'] == str(exc):
                        self.store.db.execute('COMMIT')
                        return p
                    p['reason'] = str(exc)
                else:
                    net = quote.amount_out - quote.gas_quote
                    if net < 0:
                        raise BoundaryError('exit_gas_exceeds_proceeds')
                    p.update(status='settled', pnl=net-p['cost'], tokens=0, reserved=0, reason=None)
            elif action == 'transition':
                if p['status'] not in ('open', 'exit_pending') or not transition or transition['previous_market'] != p['market']:
                    raise BoundaryError('invalid_pool_transition')
                # Only a stored proof emitted by the graduation validator may route exposure.
                proof = self.store.get('graduation', transition['proof_hash'])
                if proof != transition:
                    raise BoundaryError('unproven_pool_transition')
                p['market'] = transition['market']
            else:
                raise BoundaryError('unsupported_paper_action')
            p['version'] += 1
            p['last_at'] = now
            self._save(p, action, now)
            self.reconcile()
            self.store.db.execute('COMMIT')
            return p
        except Exception:
            self.store.db.execute('ROLLBACK')
            raise
