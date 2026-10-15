"""A bounded, explicit view of one scout command on the canonical owner.

The caller holds the original source-frame transaction. Only this command can
change these rows, and each mutation updates the view before the next fact. The
view is discarded on return (including rollback); it never caches authority
between commands or changes receipt/outbox writes.
"""
from .solana_evidence_plane import EvidenceUnavailable


class ScoutSelection:
    def __init__(self, history, facts):
        if not history.db.in_transaction or not 0 < len(facts) <= 64:
            raise EvidenceUnavailable('candidate_scout_selection_bound')
        keys = tuple(dict.fromkeys((f['family'], f['address']) for f in facts if f is not None))
        self.market = {}; self.lifecycle = {}; self.pinned = set()
        if not keys:
            return
        request = 'WITH requested(family,address) AS (VALUES ' + ','.join('(?,?)' for _ in keys) + ') '
        args = tuple(v for key in keys for v in key)
        for family, address, *row in history.db.execute(request + '''
            SELECT m.family,m.address,m.last_slot,m.last_seen,m.fields
            FROM requested r JOIN market_observations m
              ON m.family=r.family AND m.address=r.address''', args):
            self.market[family, address] = tuple(row)
        for family, address, *row in history.db.execute(request + '''
            SELECT l.family,l.address,l.state,l.epoch,l.last_slot,l.last_seen
            FROM requested r JOIN candidate_lifecycle l
              ON l.family=r.family AND l.address=r.address''', args):
            self.lifecycle[family, address] = tuple(row)
        for family, address in history.db.execute(request + '''
            SELECT DISTINCT r.family,r.address FROM requested r
            JOIN service_interests s ON s.address=r.address
            JOIN interests i ON i.owner=s.owner AND i.scope=s.scope
            WHERE i.active=1 AND s.scope='program:'||r.family''', args):
            self.pinned.add((family, address))

    def priority(self, family, address):
        key = family, address
        row = self.lifecycle.get(key)
        return 2 if (row and row[0] in ('queued', 'warming', 'active')) or key in self.pinned else 3
