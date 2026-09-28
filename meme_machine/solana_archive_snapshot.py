"""Bounded archive selection with set reads and shared per-slot coverage.

Only the SQLite owner calls this module. It never publishes evidence, changes a
pin, or reads an archive. The return shape and archive-byte accounting match the
original EvidenceWriter snapshot contract.
"""
from collections import defaultdict

SQL_SLICE = 128
MAX_SINGLE_SNAPSHOT_BYTES = 20 * 1024 * 1024


def _slices(values):
    for offset in range(0, len(values), SQL_SLICE):
        yield values[offset:offset + SQL_SLICE]


def snapshot(writer, before_time, *, max_records=1000, max_bytes=4*1024*1024):
    from .solana_evidence_plane import EvidenceUnavailable, canonical
    writer._check()
    if not 1 <= max_records <= 1000:
        raise EvidenceUnavailable('archive_batch_bound')
    # Select identities and lengths first. Do not fetch 1,000 arbitrary bodies
    # before enforcing the original encoded-byte ceiling.
    cursor = writer.db.execute('''WITH account_pins AS MATERIALIZED
      (SELECT scope,floor FROM account_interest_floors)
      SELECT r.identity,r.hash,r.scope,r.slot,length(r.body) FROM records r
      WHERE r.body IS NOT NULL AND COALESCE(r.market_time,r.first_seen) < ?
      AND NOT EXISTS(SELECT 1 FROM interests i WHERE i.active=1
         AND i.scope=r.scope AND r.slot>=i.lower_slot
         AND (NOT EXISTS(SELECT 1 FROM service_interests s WHERE s.owner=i.owner AND s.scope=i.scope)
           OR EXISTS(SELECT 1 FROM service_interests s JOIN addresses a ON a.address=s.address
                     WHERE s.owner=i.owner AND s.scope=i.scope AND a.identity=r.identity)))
      AND NOT EXISTS(SELECT 1 FROM account_pins p
         WHERE r.scope=p.scope AND r.kind='account' AND r.slot>=p.floor)
      AND NOT EXISTS(SELECT 1 FROM gaps g WHERE g.scope=r.scope AND g.repaired IS NULL
          AND r.slot>=g.lo AND (g.hi IS NULL OR r.slot<=g.hi))
      ORDER BY COALESCE(r.market_time,r.first_seen),r.identity LIMIT ?''',
      (before_time, max_records))
    candidates = []; body_bytes = 0
    try:
        for row in cursor:
            cost = row[4]
            if candidates and body_bytes + cost > max_bytes:
                break
            if body_bytes + cost > MAX_SINGLE_SNAPSHOT_BYTES:
                raise EvidenceUnavailable('archive_snapshot_bound')
            candidates.append(row); body_bytes += cost
    finally:
        cursor.close()
    if not candidates:
        return None

    # Metadata is fetched in bounded sets; coverage is fetched once per distinct
    # (scope, slot), rather than again for every event in the same block.
    ids = [row[0] for row in candidates]
    refs = defaultdict(list); lineage = defaultdict(list); coverage = defaultdict(list)
    for part in _slices(ids):
        marks = ','.join('?' for _ in part)
        for identity, checksum, size in writer.db.execute(
                'SELECT r.identity,c.hash,length(c.body) FROM hot_refs r '
                'JOIN hot_chunks c ON c.hash=r.hash WHERE r.identity IN ('+marks+') '
                'ORDER BY r.identity,c.hash', part):
            refs[identity].append((checksum, size))
        for identity, source, endpoint, observed in writer.db.execute(
                'SELECT identity,source,endpoint,observed FROM lineage '
                'WHERE identity IN ('+marks+') ORDER BY identity,source,endpoint', part):
            lineage[identity].append((source, endpoint, observed))
    pairs = list(dict.fromkeys((row[2], row[3]) for row in candidates))
    for part in _slices(pairs):
        values = ','.join('(?,?)' for _ in part)
        args = [value for pair in part for value in pair]
        for scope, slot, lo, hi, available, proof in writer.db.execute(
                'WITH wanted(scope,slot) AS (VALUES '+values+') '
                'SELECT w.scope,w.slot,c.lo,c.hi,c.available,c.proof FROM wanted w '
                'JOIN coverage c ON c.scope=w.scope AND c.lo<=w.slot AND c.hi>=w.slot '
                'ORDER BY w.scope,w.slot,c.lo,c.hi,c.id', args):
            coverage[(scope, slot)].append((lo, hi, available, proof))

    selected = []; selected_chunks = set(); size = 0
    for identity, checksum, scope, slot, encoded_length in candidates:
        new_chunks = {key: length for key, length in refs[identity]
                      if key not in selected_chunks}
        cost = encoded_length + sum(new_chunks.values()) + len(
            canonical((lineage[identity], coverage[(scope, slot)])).encode())
        if selected and size + cost > max_bytes:
            break
        if size + cost > MAX_SINGLE_SNAPSHOT_BYTES:
            raise EvidenceUnavailable('archive_snapshot_bound')
        selected.append((identity, checksum, scope, slot))
        selected_chunks.update(new_chunks); size += cost

    bodies = {}; chunks = {}
    selected_ids = [row[0] for row in selected]
    for part in _slices(selected_ids):
        marks = ','.join('?' for _ in part)
        bodies.update(writer.db.execute(
            'SELECT identity,body FROM records WHERE identity IN ('+marks+')', part))
    for part in _slices(sorted(selected_chunks)):
        marks = ','.join('?' for _ in part)
        chunks.update(writer.db.execute(
            'SELECT hash,body FROM hot_chunks WHERE hash IN ('+marks+')', part))
    if len(bodies) != len(selected_ids) or set(chunks) != selected_chunks:
        raise EvidenceUnavailable('archive_snapshot_source_changed')
    rows = [dict(identity=identity, encoded=bodies[identity], hash=checksum,
                 lineage=lineage[identity], coverage=coverage[(scope, slot)])
            for identity, checksum, scope, slot in selected]
    return dict(rows=rows, chunks=chunks, encoded_bytes=size) if rows else None
