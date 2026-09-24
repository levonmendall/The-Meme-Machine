"""Read-only Pump history/body attribution for preserved run 35935431384.

Usage: python pump_shared_query.py SHARED_DB [PURE_DECODER_SOURCE_ROOT]
Writes only JSON to stdout. SQLite is opened read-only and query_only; no RPCs.
The optional source root supplies the frozen pure PumpSwap event decoder.
"""
import collections
import hashlib
import json
import pathlib
import sqlite3
import sys
import zlib

if len(sys.argv) > 2:
    sys.path.insert(0, sys.argv[2])
from meme_machine.pump_acceleration_evidence import pumpswap_trade_events
import meme_machine.pump_acceleration_evidence as decoder

path = pathlib.Path(sys.argv[1]).resolve()
db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
db.execute('PRAGMA query_only=ON')
db.row_factory = sqlite3.Row
consumers = [dict(r) for r in db.execute(
    "SELECT owner,signature,kind,deadline,created_at,state,lane,candidate_id,first_transport_at "
    "FROM evidence_consumers WHERE lane='pump'")]
signatures = {r['signature'] for r in consumers}
negative = {}
hint_counts = collections.Counter()
for row in db.execute('SELECT stream,signature,address,slot,observed_at,payload FROM stream_signature_archive'):
    if row['signature'] not in signatures:
        continue
    hint_counts['consumer_matched_notifications'] += 1
    payload = json.loads(zlib.decompress(row['payload'])) if row['payload'] else {}
    logs = payload.get('logs')
    safe = bool(isinstance(logs, list) and logs
        and not any('truncat' in str(x).lower() for x in logs)
        and not any(e.get('pool') == row['address'] for e in pumpswap_trade_events(
            {'slot': int(row['slot']), 'meta': {'err': payload.get('err'), 'logMessages': logs}})))
    if safe:
        hint_counts['safe_negative_notifications'] += 1
        key = (row['address'], row['signature'])
        old = negative.get(key)
        if old is None or row['observed_at'] < old['observed_at']:
            negative[key] = dict(observed_at=row['observed_at'], slot=row['slot'],
                logs_sha256=hashlib.sha256(json.dumps(logs, separators=(',', ':')).encode()).hexdigest())

bodies = {}
for row in db.execute('SELECT signature,payload,cached_at,lane FROM immutable_transactions'):
    if row['signature'] not in signatures:
        continue
    body = json.loads(zlib.decompress(row['payload']))
    bodies[row['signature']] = dict(cached_at=row['cached_at'], lane=row['lane'],
        pools=sorted({e['pool'] for e in pumpswap_trade_events(body)}),
        block_time=body.get('blockTime'), slot=body.get('slot'))

groups = collections.defaultdict(collections.Counter)
unique = collections.defaultdict(set)
samples = []
for row in consumers:
    candidate = row['candidate_id']
    owner_scope = 'history' if ':history:' in row['owner'] else 'window' if ':window:' in row['owner'] else 'other'
    group = '|'.join((owner_scope, row['kind'], row['state']))
    g = groups[group]
    g['consumers'] += 1
    unique[group + '|candidates'].add(candidate)
    neg = negative.get((candidate, row['signature']))
    body = bodies.get(row['signature'])
    if body:
        g['body_eventually_acquired'] += 1
        if candidate not in body['pools']:
            g['body_has_no_candidate_pool_trade'] += 1
    if not neg:
        continue
    g['safe_negative_hint_retained'] += 1
    before_create = neg['observed_at'] < int(row['created_at'])
    before_transport = row['first_transport_at'] is not None and neg['observed_at'] < int(row['first_transport_at'])
    if before_create:
        g['negative_hint_strictly_before_consumer_second'] += 1
        unique[group + '|prior_negative_candidates'].add(candidate)
    if before_transport:
        g['negative_hint_strictly_before_transport_second'] += 1
        unique[group + '|prior_negative_transported_signatures'].add(row['signature'])
    if before_transport and body and candidate not in body['pools']:
        g['prior_negative_and_acquired_body_confirms_no_candidate_trade'] += 1
    if before_transport and body and candidate in body['pools']:
        g['contradictory_prior_negative_body_has_candidate_trade'] += 1
    if owner_scope == 'history' and before_create and len(samples) < 20:
        samples.append(dict(row, negative_hint=neg, immutable_body=body))

phase_counts = [dict(r) for r in db.execute(
    "SELECT kind,phase,count(*) count FROM acquisition_phases WHERE lane='pump' GROUP BY kind,phase")]
result = dict(schema='pump-shared-read-only-attribution-v1', run=35935431384,
    scope='Retained same-pool negative log hint before original consumer/transport; complete logs are negative-only admission evidence, never reconstructed economics.',
    decoder_sha256=hashlib.sha256(pathlib.Path(decoder.__file__).read_bytes()).hexdigest(),
    hints=dict(hint_counts), consumers=len(consumers), unique_consumer_signatures=len(signatures),
    groups={k: dict(v) for k,v in sorted(groups.items())},
    unique_counts={k: len(v) for k,v in sorted(unique.items())}, samples=samples, phase_counts=phase_counts)
print(json.dumps(result, indent=2, sort_keys=True))
db.close()
