"""Bounded offline provider-delivery census; never opens a provider connection.

All source bytes count, including failures, duplicates and replay prefixes. A
partial protobuf gives a LOWER BOUND, not an available provider projection.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import zlib

import based58

from .offline_replay import frames
from meme_machine.solana_candidate_join import candidate_subscription
from meme_machine.solana_native_evidence import signature, transaction_error
from meme_machine.solana_program_decoders import pump_events, pumpswap_trade_events
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.yellowstone import geyser_pb2 as pb

MAX_RECORDS = 100000
MAX_SOURCE_BYTES = 512 * 1024 * 1024
FAMILIES = ('pump', 'pumpswap')


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(65536):
            value.update(chunk)
    return value.hexdigest()


def successful_content_lower_bound(slot, sig, logs):
    """Missing transaction, metadata, index, labels and clocks cost MORE bytes.

    No fabricated transaction is sent through production evidence authority.
    The lower bound is serialized only to estimate the minimum required logs.
    """
    update = pb.SubscribeUpdate()
    update.transaction.slot = slot
    update.transaction.transaction.signature = based58.b58decode(sig.encode())
    update.transaction.transaction.meta.log_messages.extend(logs)
    return update.ByteSize()


def audit_records(records, *, charged_bytes=None):
    subscriptions = {}
    ws_connections = {}
    ws_routes = {}
    components = defaultdict(Counter)
    by_subscription = defaultdict(Counter)
    statuses = {}
    logs = {}
    unique_logs = {}
    economic_ids = set()
    economics = Counter()
    decode_errors = Counter()
    telemetry = Counter()
    active = set()
    ordinal = 0
    source_raw_bytes = 0
    for ordinal, (meta, raw) in enumerate(records, 1):
        if ordinal > MAX_RECORDS or len(raw) > 16 * 1024 * 1024:
            raise ValueError('bandwidth_capture_record_budget')
        source_raw_bytes += len(raw)
        if source_raw_bytes > MAX_SOURCE_BYTES:
            raise ValueError('bandwidth_capture_byte_budget')
        kind = meta['kind']
        sid = meta.get('id')
        if kind == 'subscribe':
            request = pb.SubscribeRequest.FromString(raw)
            routes = {}
            for label, filt in request.transactions_status.items():
                families = {f for f in FAMILIES if PROGRAMS[f] in filt.account_include}
                if families:
                    if filt.HasField('failed') or not filt.HasField('vote') or filt.vote:
                        raise ValueError('bandwidth_status_witness_filter_changed')
                    routes[label] = families
            counts = {name: len(getattr(request, name)) for name in
                      ('accounts', 'transactions', 'transactions_status', 'blocks', 'blocks_meta', 'slots')}
            if sid in subscriptions:
                telemetry['subscription_rebuilds'] += 1
            subscriptions[sid] = dict(routes=routes, from_slot=request.from_slot,
                                      filters=counts, family=meta['family'])
            active.add(sid)
            telemetry['peak_native_subscriptions'] = max(telemetry['peak_native_subscriptions'], len(active))
            telemetry['native_subscriptions_started'] += 1
            continue
        if kind == 'unsubscribe':
            active.discard(sid)
            continue
        if kind == 'websocket_open':
            ws_connections[sid] = meta['addresses']
            telemetry['ws_connections_opened'] += 1
            continue
        if kind == 'native_error':
            telemetry['native_error:' + meta['status']] += 1
            continue
        if kind != 'delivery':
            continue
        if meta.get('bytes', len(raw)) != len(raw):
            raise ValueError('bandwidth_frame_size_contradiction')
        transport = meta['transport']
        telemetry['source_delivered_bytes'] += len(raw)
        telemetry[transport + '_bytes'] += len(raw)
        by_subscription[sid]['bytes'] += len(raw)
        by_subscription[sid]['messages'] += 1
        if transport == 'yellowstone':
            sub = subscriptions[sid]
            update = pb.SubscribeUpdate.FromString(raw)
            message = update.WhichOneof('update_oneof')
            item = getattr(update, message)
            label = sub['family'] + ':' + message
            components[label]['bytes'] += len(raw)
            components[label]['messages'] += 1
            if hasattr(item, 'slot') and item.slot < sub['from_slot']:
                components[label]['below_requested_floor_bytes'] += len(raw)
            if message == 'transaction_status':
                err = transaction_error(bytes(item.err.err)) if item.HasField('err') else None
                failure = err is not None
                components[label]['failed_bytes' if failure else 'successful_bytes'] += len(raw)
                components[label]['failed_messages' if failure else 'successful_messages'] += 1
                for family in set().union(*(sub['routes'].get(f, set()) for f in update.filters)):
                    key = family, item.slot, signature(item.signature)
                    fact = dict(index=item.index, error=err, bank_id=item.bank_id)
                    if key in statuses and statuses[key] != fact:
                        raise ValueError('bandwidth_native_witness_contradiction')
                    statuses[key] = fact
            continue
        if transport != 'websocket':
            raise ValueError('bandwidth_unknown_transport')
        value = json.loads(raw)
        if 'id' in value:
            program = ws_connections[sid][value['id'] - 1]
            ws_routes[sid, value['result']] = next((f for f in FAMILIES if PROGRAMS[f] == program), 'scoped_other')
            components['ws_ack']['bytes'] += len(raw)
            components['ws_ack']['messages'] += 1
            continue
        params = value['params']
        family = ws_routes[sid, params['subscription']]
        slot = params['result']['context']['slot']
        tx = params['result']['value']
        failure = tx['err'] is not None
        bucket = components[family + ('_failed' if failure else '_successful')]
        bucket['bytes'] += len(raw)
        bucket['messages'] += 1
        fact = dict(error=tx['err'], logs_digest=hashlib.sha256(
            json.dumps(tx['logs'], separators=(',', ':'), ensure_ascii=False).encode()).hexdigest())
        key = family, slot, tx['signature']
        cross_key = slot, tx['signature']
        if key in logs and logs[key] != fact or cross_key in unique_logs and unique_logs[cross_key] != fact:
            raise ValueError('bandwidth_ws_content_contradiction')
        logs[key] = fact
        duplicate = cross_key in unique_logs
        unique_logs[cross_key] = fact
        if duplicate:
            telemetry['duplicate_ws_bytes'] += len(raw)
        if failure:
            continue
        bucket['required_success_content_lower_bound_bytes'] += successful_content_lower_bound(slot, tx['signature'], tx['logs'])
        if duplicate:
            continue
        body = dict(slot=slot, transaction=dict(signatures=[tx['signature']]),
                    meta=dict(err=None, logMessages=tx['logs']))
        # Decode the COMPLETE source success population before any selection.
        for f, decoder in (('pump', pump_events), ('pumpswap', pumpswap_trade_events)):
            try:
                events = decoder(body)
            except ValueError as error:
                decode_errors[f + ':' + str(error)] += 1
                continue
            for event in events:
                identity = f, slot, tx['signature'], event['index']
                if identity in economic_ids:
                    raise ValueError('bandwidth_duplicate_economic_identity')
                economic_ids.add(identity)
                economics[f + ':' + event.get('event_type', 'trade')] += 1

    witness = defaultdict(Counter)
    for (family, slot, sig), fact in logs.items():
        prefix = 'failed' if fact['error'] is not None else 'successful'
        native = statuses.get((family, slot, sig))
        witness[family][prefix + '_unique_log_facts'] += 1
        if native is None:
            witness[family][prefix + '_without_native_status'] += 1
        elif native['error'] != fact['error']:
            raise ValueError('bandwidth_ws_native_status_contradiction')
        else:
            witness[family][prefix + '_with_matching_native_status'] += 1
    alternatives = {}
    for family in FAMILIES:
        success = components[family + '_successful']
        failed = components[family + '_failed']
        avoided = success['bytes'] + failed['bytes']
        count = success['messages']
        lower = success['required_success_content_lower_bound_bytes']
        alternatives[family] = dict(
            success_messages=count, replaced_ws_bytes=avoided,
            native_success_content_lower_bound_bytes=lower,
            missing_full_transaction_and_envelope_bytes='UNMEASURED',
            bandwidth_break_even_native_bytes_per_success=avoided / count if count else None,
            residual_full_transaction_budget_bytes=avoided - lower,
            residual_budget_bytes_per_success=(avoided - lower) / count if count else None,
            targeted_getTransaction_requests_if_all_successes_acquired=count,
            targeted_getTransaction_cu_if_all_successes_acquired=count * 40,
            independent_statuses_and_continuity_retained=True,
            provider_savings='UNVERIFIED')
    charged = telemetry['source_delivered_bytes'] if charged_bytes is None else charged_bytes
    if charged < telemetry['source_delivered_bytes']:
        raise ValueError('bandwidth_charged_less_than_capture')
    return dict(schema='pump-provider-bandwidth-audit-v1', provider_calls=0,
                actual_provider_savings_verified_bytes=0, records=ordinal,
                captured_delivery=dict(telemetry), charged_application_bytes=charged,
                charged_but_uncaptured_bytes=charged - telemetry['source_delivered_bytes'],
                components={k: dict(v) for k, v in sorted(components.items())},
                subscription_payload={k: dict(v) for k, v in sorted(by_subscription.items())},
                subscriptions=subscriptions,
                log_native_identity_comparison={k: dict(v) for k, v in witness.items()},
                decoded_complete_source_success_population=dict(economics),
                decoder_failures=dict(decode_errors), alternatives=alternatives,
                limitations=['Application payload excludes HTTP2/WS/TLS framing and NIC traffic.',
                            'Native status matches do not alone prove complete intervals.',
                            'Missing independent witnesses remain incomplete.',
                            'Native subscription counts are RPC streams, not measured TCP connections.',
                            'The protobuf lower bound is NOT a provider-supported log projection.'])


def audit_capture(capture):
    capture = Path(capture)
    result = json.loads((capture / 'result.json').read_text())
    ceilings = json.loads((capture / 'ceilings.json').read_text())
    audit = audit_records(frames(capture / 'provider.frames.zlib'), charged_bytes=ceilings['native_delivery_bytes'])
    # Source identities are preserved; no endpoint credential is read.
    audit['capture'] = dict(path=str(capture), tape_sha256=sha256(capture / 'provider.frames.zlib'),
                            result_sha256=sha256(capture / 'result.json'),
                            endpoint_identity=result['endpoint_identity'],
                            source_commit=result['source_commit'], source_sha256=result['source_sha256'])
    calls = [json.loads(row) for row in zlib.decompress((capture / 'http.ndjson.zlib').read_bytes()).splitlines()]
    # Family labels include shared_source/replay_source; use the captured RPC
    # method inventory rather than accidentally excluding those real calls.
    solana_methods = set(result['logical_RPC_methods'])
    solana_calls = [r for r in calls if r['methods'] and set(r['methods']).issubset(solana_methods)]
    audit['http'] = dict(recorded_successful_batches=len(calls),
                         all_method_elements=dict(Counter(m for row in calls for m in row['methods'])),
                         solana_method_elements=result['logical_RPC_methods'],
                         recorded_solana_rpc=result['rpc'],
                         successful_solana_physical_batches=len(solana_calls),
                         ceilings=ceilings,
                         billed_provider_cu='UNMEASURED',
                         caveat='Governor denied attempts are not sent physical provider requests; planning CU is not billing.')
    audit['native_pressure'] = dict(native_stream_peak=result['transport'].get('peak_native_streams'),
                                    native_status_counts=result['transport'].get('native_status_counts', 'UNRECORDED'),
                                    tcp_connections='UNMEASURED',
                                    account_connection_limit='UNVERIFIED_OFFLINE')
    return audit


def capability_request(from_slot):
    """One replacement candidate Subscribe RPC, reusing existing filter builder.

    This prepares a supported request only. No endpoint calls, connection or
    production configuration switch is implemented or enabled here.
    """
    from meme_machine.solana_rolling_history import program_scope
    addresses = {PROGRAMS[f]: program_scope(f) for f in FAMILIES}
    return candidate_subscription(addresses, from_slot, full_addresses={PROGRAMS['pumpswap']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    from operational.tests import network_guard
    network_guard()
    report = audit_capture(args.capture)
    # Status-route sets are descriptive only; canonical native bytes stay exact.
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True,
                                     default=lambda obj: sorted(obj) if isinstance(obj, set) else str(obj)) + '\n')
    print(json.dumps({key: report[key] for key in ('charged_application_bytes', 'captured_delivery',
                     'log_native_identity_comparison', 'alternatives')}, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
