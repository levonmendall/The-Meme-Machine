"""Append-only confirmed observations, displacement and later canonical checks.

This bounded ledger is an evidence gate, not a new trading policy. A hash change
invalidates dependent research without rewriting its original availability time.
"""
from dataclasses import asdict
import json

from . import BoundaryError
from .evidence import Stamp, digest


class Finality:
    def __init__(self, store, scope='robinhood', max_blocks=2048):
        if not 1 <= max_blocks <= 10000:
            raise BoundaryError('finality_capacity')
        self.store, self.scope, self.max_blocks = store, scope, max_blocks

    def _id(self, block_hash):
        return self.scope + ':' + block_hash

    def _optional(self, category, ident):
        row = self.store.db.execute('SELECT 1 FROM records WHERE category=? AND id=?', (category, ident)).fetchone()
        return self.store.get(category, ident) if row else None

    def block(self, block_hash):
        return self.store.get('confirmed_block', self._id(block_hash))

    def status(self, block_hash):
        self.block(block_hash)
        if self._optional('displaced_block', self._id(block_hash)):
            return 'invalidated'
        if self._optional('finalized_block', self._id(block_hash)):
            return 'finalized'
        return 'confirmed'

    def _active(self):
        cursor = self.store.cursor('finality:' + self.scope)
        if not cursor:
            return []
        chain = []
        current = self.block(cursor[1])
        while current:
            chain.append(current)
            if len(chain) > self.max_blocks:
                raise BoundaryError('finality_capacity')
            current = self._optional('confirmed_block', self._id(current['parent_hash']))
        return chain

    def _invalidate(self, blocks, at, reason):
        for block in blocks:
            bh = block['stamp']['block_hash']
            if self.status(bh) == 'finalized':
                raise BoundaryError('finalized_chain_disagreement')
            if self.status(bh) != 'invalidated':
                self.store.put('displaced_block', self._id(bh), dict(at=at, reason=reason))

    def observe(self, stamp, parent_hash):
        if stamp.finality != 'confirmed':
            raise BoundaryError('expected_confirmed_observation')
        # Validate original availability and chain while retaining non-final status.
        Stamp(**(asdict(stamp) | {'finality': 'finalized'})).check(stamp.observed_at, 120)
        body = dict(stamp=asdict(stamp), parent_hash=parent_hash)
        old = self._optional('confirmed_block', self._id(stamp.block_hash))
        if old:
            # Re-observation time is not a new original-availability timestamp.
            if old['parent_hash'] != parent_hash or any(old['stamp'][k] != asdict(stamp)[k]
                for k in ('chain_id', 'block', 'block_hash', 'event_at', 'kind')):
                raise BoundaryError('conflicting_block_header')
            if self.status(stamp.block_hash) == 'invalidated':
                raise BoundaryError('displaced_evidence')
            return False
        active = self._active()
        if len(active) >= self.max_blocks:
            raise BoundaryError('finality_capacity')
        parent = next((b for b in active if b['stamp']['block_hash'] == parent_hash), None)
        if active and (parent is None or stamp.block != parent['stamp']['block'] + 1):
            raise BoundaryError('missing_reorg_ancestry')
        if parent and self.status(parent['stamp']['block_hash']) == 'invalidated':
            raise BoundaryError('displaced_parent')
        if parent and (stamp.event_at < parent['stamp']['event_at'] or stamp.observed_at < parent['stamp']['observed_at']):
            raise BoundaryError('nonmonotonic_observation')
        displaced = [b for b in active if b['stamp']['block'] >= stamp.block]
        self.store.db.execute('BEGIN IMMEDIATE')
        try:
            self._invalidate(displaced, stamp.observed_at, 'replacement_branch')
            self.store.put('confirmed_block', self._id(stamp.block_hash), body)
            self.store.db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',
                                  ('finality:' + self.scope, stamp.block, stamp.block_hash))
            self.store.db.execute('COMMIT')
        except Exception:
            self.store.db.execute('ROLLBACK')
            raise
        return True

    def removed(self, block_hash, *, observed_at):
        block = self.block(block_hash)
        if observed_at < block['stamp']['observed_at']:
            raise BoundaryError('backdated_invalidation')
        active = self._active()
        affected = [b for b in active if b['stamp']['block'] >= block['stamp']['block']]
        self.store.db.execute('BEGIN IMMEDIATE')
        try:
            self._invalidate(affected, observed_at, 'removed_log')
            self.store.db.execute('COMMIT')
        except Exception:
            self.store.db.execute('ROLLBACK')
            raise

    def reconcile(self, *, frontier, canonical_headers, observed_at):
        """Adapter supplies canonical-by-number headers under a finalized frontier.

        Require every stored active height through that frontier, not an isolated
        finality flag. A mismatch invalidates first; it never promotes a replacement
        as if the replacement had been available at the original observation time.
        """
        frontier.check(observed_at, max_age=86400)
        active = self._active()
        due = [b for b in active if b['stamp']['block'] <= frontier.block]
        supplied = {h['block']: h for h in canonical_headers}
        if len(supplied) != len(canonical_headers) or set(supplied) != {b['stamp']['block'] for b in due}:
            raise BoundaryError('incomplete_finalization_coverage')
        if any(observed_at < b['stamp']['observed_at'] for b in due):
            raise BoundaryError('backdated_finalization')
        if frontier.block in supplied and supplied[frontier.block]['block_hash'] != frontier.block_hash:
            raise BoundaryError('frontier_hash_disagreement')
        mismatch = next((b for b in reversed(due) if supplied[b['stamp']['block']]['block_hash'] != b['stamp']['block_hash']), None)
        self.store.db.execute('BEGIN IMMEDIATE')
        try:
            if mismatch:
                self._invalidate([b for b in active if b['stamp']['block'] >= mismatch['stamp']['block']],
                                 observed_at, 'finalized_hash_disagreement')
            else:
                for b in due:
                    bh = b['stamp']['block_hash']
                    if self.status(bh) == 'invalidated':
                        raise BoundaryError('displaced_evidence')
                    if self.status(bh) != 'finalized':
                        self.store.put('finalized_block', self._id(bh), dict(
                            observed_at=observed_at, frontier=asdict(frontier),
                            canonical_header=supplied[b['stamp']['block']]))
            self.store.db.execute('COMMIT')
        except Exception:
            self.store.db.execute('ROLLBACK')
            raise
        if mismatch:
            raise BoundaryError('finalized_hash_disagreement')

    def check(self, stamp, asof, max_age):
        block = self.block(stamp.block_hash)
        if asdict(stamp) != block['stamp']:
            raise BoundaryError('observation_identity_disagreement')
        if self.status(stamp.block_hash) == 'invalidated':
            raise BoundaryError('displaced_evidence')
        Stamp(**(asdict(stamp) | {'finality': 'finalized'})).check(asof, max_age)

    def bind(self, identity, stamps, *, asof):
        if not stamps or len(stamps) > 2048:
            raise BoundaryError('dependency_capacity')
        for stamp in stamps:
            self.check(stamp, asof, 86400)
        self.store.put('confirmed_dependency', self._id(identity), dict(
            block_hashes=sorted(set(s.block_hash for s in stamps)), observed_at=asof))

    def check_dependency(self, identity):
        row = self.store.get('confirmed_dependency', self._id(identity))
        statuses = [self.status(h) for h in row['block_hashes']]
        if 'invalidated' in statuses:
            raise BoundaryError('displaced_dependent_evidence')
        return 'finalized' if all(s == 'finalized' for s in statuses) else 'confirmed'
