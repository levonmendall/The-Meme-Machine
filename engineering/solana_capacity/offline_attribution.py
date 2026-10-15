"""Attribute retained proof tapes only. No endpoint, credentials or provider I/O.

Byte categories are application payload, not TLS/network or billed CU. A log
substring is not a supported provider projection. Timestamp ages are not proof
of provider dispatch or finality duration.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import time
import zlib

from meme_machine.yellowstone import geyser_pb2 as pb
from meme_machine.solana_program_decoders import pump_events, pumpswap_trade_events
from meme_machine.solana_selective_history import PROGRAMS


def distribution(values):
    a = sorted(values)
    if not a:
        return dict(n=0, p50=None, p95=None, p99=None, max=None)
    return dict(n=len(a), **{k: a[min(len(a)-1, int((len(a)-1)*p))]
                for k, p in (('p50', .5), ('p95', .95), ('p99', .99))}, max=a[-1])


def frames(path):
    decoder = zlib.decompressobj(); pending = b''
    with Path(path).open('rb') as source:
        while chunk := source.read(65536):
            pending += decoder.decompress(chunk)
            while len(pending) >= 8:
                header, raw = struct.unpack('!II', pending[:8])
                if header > 65536 or raw > 16*1024*1024:
                    raise ValueError('capture_record_bound')
                end = 8+header+raw
                if len(pending) < end: break
                yield json.loads(pending[8:8+header]), pending[8+header:end]
                pending = pending[end:]
    pending += decoder.flush()
    if pending or not decoder.eof or decoder.unused_data:
        raise ValueError('capture_incomplete')


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024*1024): h.update(chunk)
    return h.hexdigest()


def json_field_bytes(raw, field):
    # Exact encoded JSON value bytes, excluding field name, colon and commas.
    text = raw.decode(); start = text.index('"'+field+'"') + len(field)+2
    start = text.index(':', start)+1
    while text[start].isspace(): start += 1
    _, end = json.JSONDecoder().raw_decode(text, start)
    return len(text[start:end].encode())


def audit(folder):
    folder = Path(folder); result = json.loads((folder/'result.json').read_text())
    ceilings = json.loads((folder/'ceilings.json').read_text())
    start = result['measurement_started']; release = result.get('steady_started')
    totals = Counter(); by_class = defaultdict(Counter); ages = defaultdict(list)
    subscriptions = {}; ws_subscriptions = {}; identities = {}; native_facts = {}
    duplicate = Counter(); ws_unique = {}; blocks = {}; buckets = Counter()
    observer = Counter(); errors = Counter(); economic = Counter(); economic_ids = set();first_delivery=None;last_delivery=None
    source_hashes = result.get('source_sha256', {})
    for metadata, raw in frames(folder/'provider.frames.zlib'):
        observer['records'] += 1
        observer['uncompressed_archive_bytes'] += 8+len(json.dumps(metadata,separators=(',',':')).encode())+len(raw)
        if metadata['kind'] == 'subscribe':
            request = pb.SubscribeRequest.FromString(raw)
            subscriptions[metadata['id']] = metadata
            continue
        if metadata['kind'] == 'websocket_open':
            ws_subscriptions[metadata['id']] = metadata['addresses']; continue
        if metadata['kind'] != 'delivery': continue
        size = len(raw); transport = metadata['transport']; seen = metadata['seen']
        first_delivery=seen if first_delivery is None else min(first_delivery,seen)
        last_delivery=seen if last_delivery is None else max(last_delivery,seen)
        buckets[int(seen)] += size
        totals[transport+'_bytes'] += size; totals[transport+'_messages'] += 1
        phase = 'startup' if release is None or seen < release else 'steady'
        if transport == 'websocket':
            value = json.loads(raw)
            if 'id' in value:
                by_class['ws_ack']['bytes'] += size; by_class['ws_ack']['messages'] += 1
                addresses = ws_subscriptions[metadata['id']]
                family = next((f for f in ('pump','pumpswap') if PROGRAMS[f] == addresses[value['id']-1]), 'position')
                identities[metadata['id'],value['result']] = family
                continue
            params = value['params']; v = params['result']['value']; slot = params['result']['context']['slot']
            family = identities[metadata['id'],params['subscription']]
            failed = v['err'] is not None; label = family+('_failed' if failed else '_successful')
            bucket = by_class[label]; bucket['bytes'] += size; bucket['messages'] += 1
            bucket['logs_json_value_bytes'] += json_field_bytes(raw, 'logs')
            bucket[phase+'_bytes'] += size
            txkey = (slot,v['signature'])
            fact = json.dumps([v['err'],v['logs']],separators=(',',':')).encode()
            prior = ws_unique.get(txkey)
            if prior is not None:
                if prior[0] != fact: raise ValueError('capture_log_identity_contradiction')
                duplicate['ws_duplicate_bytes'] += size; duplicate['ws_duplicate_messages'] += 1
                if prior[1] != family: duplicate['ws_cross_program_bytes'] += size
                else: duplicate['ws_same_program_bytes'] += size
            else: ws_unique[txkey] = (fact,family)
            if failed: continue
            bucket['program_data_string_bytes'] += sum(len(json.dumps(line).encode()) for line in v['logs'] if line.startswith('Program data: '))
            if prior is not None: continue
            tx = dict(slot=slot,transaction=dict(signatures=[v['signature']]),meta=dict(err=None,logMessages=v['logs']))
            for f, decoder in (('pump',pump_events),('pumpswap',pumpswap_trade_events)):
                try: events = decoder(tx)
                except ValueError as error:
                    errors[f+':'+str(error)] += 1; continue
                for event in events:
                    eventkey = (f,slot,v['signature'],event['index'])
                    if eventkey in economic_ids: raise ValueError('duplicate_decoded_event')
                    economic_ids.add(eventkey); economic[f+':'+event.get('event_type','trade')] += 1
                    economic[f+':event_json_bytes'] += len(json.dumps(event,sort_keys=True,separators=(',',':')).encode())
            continue
        update = pb.SubscribeUpdate.FromString(raw); kind = update.WhichOneof('update_oneof')
        subscription = subscriptions[metadata['id']]
        stream = 'scout' if subscription['filter_types']['accounts'] else 'control' if not subscription['addresses'] else 'candidate_status'
        item = getattr(update,kind); slot = getattr(item,'slot',None)
        bucket = by_class[stream+':'+kind]; bucket['bytes'] += size; bucket['messages'] += 1
        bucket[phase+'_bytes'] += size
        prefix = slot is not None and slot < subscription['from_slot']
        bucket['below_requested_floor_bytes'] += size if prefix else 0
        created = update.created_at.seconds+update.created_at.nanos/1e9 if update.HasField('created_at') else None
        if created is not None:
            ages[stream+':'+kind+':created_age'].append(seen-created)
            ages[stream+':'+phase+':'+('prefix' if prefix else 'in_range')+':created_age'].append(seen-created)
        if kind == 'block_meta':
            if item.HasField('block_time'):
                chain = item.block_time.timestamp
                blocks[slot] = chain
                ages[stream+':'+phase+':chain_age'].append(seen-chain)
                if created is not None: ages[stream+':created_minus_blocktime'].append(created-chain)
        elif kind == 'transaction_status':
            bucket['failed_messages' if item.HasField('err') else 'successful_messages'] += 1
            bucket['failed_bytes' if item.HasField('err') else 'successful_bytes'] += size
            if len(update.filters)>1: bucket['multi_scope_bytes'] += size
        update.ClearField('filters'); update.ClearField('created_at')
        checksum = hashlib.sha256(update.SerializeToString()).digest()
        prior = native_facts.get(checksum)
        if prior is not None:
            duplicate['grpc_duplicate_bytes'] += size
            duplicate['grpc_cross_stream_bytes' if prior[0]!=metadata['id'] else 'grpc_same_stream_bytes'] += size
            if created is not None and prior[2]==created:
                ages['same_native_fact_original_created_at_receipt_separation'].append(seen-prior[1])
        else: native_facts[checksum] = (metadata['id'],seen,created)
    dbpath = folder/'state/canonical.sqlite'
    with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tables = {name: dict(bytes=size, pages=pages) for name,size,pages in db.execute('SELECT name,SUM(pgsize),COUNT(*) FROM dbstat GROUP BY name ORDER BY SUM(pgsize) DESC')}
        delivery = [list(r) for r in db.execute('SELECT family,transport,SUM(raw_bytes),SUM(retained_bytes),SUM(canonical_bytes),SUM(ipc_bytes) FROM provider_delivery GROUP BY family,transport')]
        canonical = db.execute('SELECT COUNT(*),COUNT(DISTINCT identity),SUM(LENGTH(body)) FROM canonical_evidence').fetchone()
        schema = {name:[r[1] for r in db.execute('PRAGMA table_info('+name+')')] for name in ('canonical_evidence','rolling_economic_events','rolling_event_refs','candidate_checkpoints')}
        stock = {name: db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in ('rolling_economic_events','candidate_content_receipts','candidate_outbox','market_observations','candidate_lifecycle','acquisition_jobs')}
        published = db.execute('SELECT COUNT(*),SUM(LENGTH(body)) FROM candidate_history_outbox').fetchone()
        outbox_timings={}
        for kind in ('canonical','scout','promotion'):
            rows=db.execute("SELECT created,consumed,body FROM candidate_history_outbox WHERE kind=?",(kind,)).fetchall()
            outbox_timings[kind]=dict(staged_to_publication_ack=distribution(b-a for a,b,_ in rows if b is not None))
            if kind=='canonical':
                available=[(json.loads(raw)['available'],a,b) for a,b,raw in rows]
                outbox_timings[kind].update(content_receipt_to_outbox_staging=distribution(a-t for t,a,_ in available),
                    content_receipt_to_publication_ack=distribution(b-t for t,_,b in available if b is not None))
    samples = [json.loads(line) for line in zlib.decompress((folder/'owner.samples.ndjson.zlib').read_bytes()).splitlines()]
    first,last = samples[0],samples[-1]
    last_io = next(s for s in reversed(samples) if 'process_io' in s)
    io = {k:last_io['process_io'][k]-first['process_io'].get(k,0) for k in last_io['process_io']}
    manifest = {str(p.relative_to(folder)):dict(bytes=p.stat().st_size,sha256=sha256(p)) for p in sorted(folder.rglob('*')) if p.is_file() and not str(p).endswith(('-shm','.lock'))}
    return dict(schema='pump-provider-offline-attribution-v1',capture=str(folder),source_hashes=source_hashes,
        preserved_capture_manifest=manifest,physical_payload=dict(totals),ranked_payload=[dict(component=k,**v) for k,v in sorted(by_class.items(),key=lambda kv:-kv[1]['bytes'])],
        duplicate_payload=dict(duplicate),decoded_unique_economic_events=dict(economic),decoder_failures=dict(errors),
        archive= dict(observer),persisted=dict(canonical_events=canonical[0],distinct_canonical_events=canonical[1],canonical_body_bytes=canonical[2],published_rows=published[0],published_body_bytes=published[1],stock=stock,tables=tables,schema=schema,delivery_accounting=delivery),
        timestamp_ages={k:distribution(v) for k,v in ages.items()},
        resource_samples=dict(process_cpu_seconds=last['cpu_seconds']-first['cpu_seconds'],child_cpu_seconds=last_io['child_cpu_seconds']-first['child_cpu_seconds'],io_sample_seconds=last_io['at']-first['at'],process_io_delta=io,peak_owner_wait=max(s['oldest_wait'] for s in samples)),
        outbox_timings=outbox_timings,
        throughput=dict(window_seconds=result['window_seconds'],steady_seconds=None if release is None else result['running_close_at']-release,
            first_captured_delivery=first_delivery,last_captured_delivery=last_delivery,active_captured_delivery_seconds=last_delivery-first_delivery,
            post_release_captured_delivery_seconds=None if release is None else max(0,last_delivery-release),
            post_delivery_drain_seconds=result['running_close_at']-last_delivery,byte_buckets=sorted(buckets.items()),peak_one_second_bucket=max(buckets.values())),
        ceiling_receipt=ceilings,captured_vs_charged_bytes=ceilings['native_delivery_bytes']-totals['yellowstone_bytes']-totals['websocket_bytes'],
        limitations=['Application bytes exclude TLS, framing and NIC traffic.', 'Duplicate accounting does not imply provider-filter support or safe suppression.', 'All program data and decoded event bytes are informative content sizes, not a provider projection.', 'created_at semantics and physical dispatch/finality clocks are unproved.', 'SQLite page stock is not cumulative durable write traffic; process writes include captures and every DB.', 'No new history or live provider evidence was acquired.'])


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--capture',required=True); parser.add_argument('--output',required=True)
    args=parser.parse_args(); started=time.monotonic(); result=audit(args.capture)
    Path(args.output).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(output=args.output,seconds=time.monotonic()-started,physical=result['physical_payload'],ranked=result['ranked_payload'],duplicates=result['duplicate_payload'],ages=result['timestamp_ages'],canonical=result['persisted']['stock'],missing_capture_bytes=result['captured_vs_charged_bytes'],decoder_failures=result['decoder_failures']),indent=2))


if __name__=='__main__': main()
