"""The finite EXPERIMENT.md executor. Default invocation is an OFFLINE plan.

Only --execute-provider-experiment, an explicit authorization reference and a
current account headroom receipt open transports. No strategy worker, archive
RPC, retry, reconnect, PAPER database or production configuration is started.
The parent process enforces wall/RSS/storage even if a decoder or shutdown stalls.
"""
import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import grpc
from websockets.asyncio.client import connect

from .bandwidth_audit import capability_request
from .capability_evidence import ADDRESSES, FAMILIES, PairedEvidence
from .capability_limits import Budget, CapabilityStop, Limits, MIB, tree_bytes
from .credential_reconciliation import APP_IDS
from .transport_meter import TransportMeter
from meme_machine.solana_candidate_join import candidate_subscription
from meme_machine.solana_provider_config import AlchemyEndpoint, GENESIS
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import SelectiveSource, scout_request, CONTROL_OVERLAP, HOST
from meme_machine.solana_source_intake import candidate_log_message
from meme_machine.yellowstone import geyser_pb2 as pb

STORAGE_SHA256 = '24d4362f465586d08fe8f917dcf69b553d39a2b9b0c87635e5b0ae9200bce87d'
PROTOCOL_SHA256 = '80ee337f361198a0722cb5bdf244fe41838949ab7a3af6d1b182b7fdca9abf02'
STATUS_READY = 'PUMP_ALCHEMY_OPTIMIZATION_READY_FOR_PROVIDER_VALIDATION'


def reason(error):
    value = str(error)
    return value if re.fullmatch('[a-z][a-z0-9_]{0,100}', value) else type(error).__name__


def validate_requests(floor, tip):
    """Validate wire presence against the committed 14.0.1 descriptor/schema."""
    schema = Path(__file__).resolve().parents[2]/'meme_machine/yellowstone/geyser.proto'
    if hashlib.sha256(schema.read_bytes()).hexdigest() != PROTOCOL_SHA256:
        raise CapabilityStop('pinned_protocol_changed')
    if type(tip) is not int or tip < 1:
        raise CapabilityStop('finalized_tip_shape')
    scout = scout_request()
    # The executor must run in the existing operational Pump-only Solana scope.
    if set(scout.accounts) != {'p'} or scout.transactions or scout.transactions_status:
        raise CapabilityStop('scout_scope_not_pump_only')
    scout.from_slot = max(1, tip-CONTROL_OVERLAP)
    control = pb.SubscribeRequest(commitment=pb.FINALIZED, from_slot=scout.from_slot)
    control.blocks_meta['b'].SetInParent()
    control.slots['f'].filter_by_commitment = True
    candidate = capability_request(floor)
    expected = candidate_subscription(ADDRESSES, floor, full_addresses={PROGRAMS['pumpswap']})
    if candidate != expected or len(candidate.transactions) != 1 or len(candidate.transactions_status) != 2:
        raise CapabilityStop('capability_request_identity')
    tx = candidate.transactions['t']
    if not tx.HasField('failed') or tx.failed or not tx.HasField('vote') or tx.vote:
        raise CapabilityStop('successful_body_filter_presence')
    for status in candidate.transactions_status.values():
        if status.HasField('failed') or not status.HasField('vote') or status.vote or status.account_exclude or status.account_required:
            raise CapabilityStop('independent_status_filter_presence')
    if candidate.commitment != pb.FINALIZED or candidate.from_slot != floor:
        raise CapabilityStop('candidate_finality_or_floor')
    return {'pump': scout, 'shared': control, 'pumpswap': candidate}


def offline_plan():
    # No endpoints, credential files, sockets or state are opened here.
    return dict(status=STATUS_READY, provider_calls=0, default_mode='OFFLINE_PLAN',
                limits=asdict(Limits()), provider_execution_authorized=False,
                request_topology='one_channel_three_Subscribe_RPCs_one_WS_two_logsSubscribe',
                live_requirements=['separate_authorization', 'current_account_headroom_receipt',
                                   'configured_pump_credential_matches_app_9bin99s96t7ga5e9',
                                   'existing_shared_governor', 'pinned_engineering_storage_admission'],
                production_configuration_changed=False, verified_provider_savings_bytes=0)


class CaptureMeter(TransportMeter):
    """Reuse the archive format and totals without parsing before raw retention.

    Invalid payloads and stopping frames must survive even when decoding fails.
    Per-message latency/duplicate telemetry is stored in bounded SQLite, rather
    than adding an unbounded Python raw-frame or telemetry list.
    """
    def __init__(self, path, budget=None):
        super().__init__(path)
        self.budget = budget
        self.phase = 'paired'
        self.phase_bytes = Counter()
        self.phase_messages = Counter()
        self.archive_lock = threading.RLock()

    def write(self, metadata, raw=b''):
        with self.archive_lock:
            super().write(metadata, raw)

    def capture(self, stream_id, family, transport, raw, size, trailing, seen, mono):
        self.delivery[transport, family] += size
        self.messages[transport, family] += 1
        phase = 'shutdown' if trailing else self.phase
        if phase == 'paired' and self.budget and self.budget.clock()-self.budget.started >= self.budget.limits.paired_seconds:
            phase = 'transition'
        self.phase_bytes[phase, transport, family] += size
        self.phase_messages[phase, transport, family] += 1
        metadata = dict(kind='delivery', id=stream_id, family=family, transport=transport,
                        seen=seen, received_monotonic=mono, bytes=size, shutdown=trailing, phase=phase)
        if raw is None:
            metadata.update(kind='oversized_delivery', captured=False)
        self.write(metadata, raw or b'')


class NativeCall:
    def __init__(self, call, budget, meter, sid, family, expected):
        self.call, self.budget, self.meter = call, budget, meter
        self.sid, self.family, self.expected = sid, family, expected
        self.written = False
        self.reading = False
        self.cancelled = False

    async def write(self, request):
        if request.HasField('ping'):
            if not self.written or request != pb.SubscribeRequest(ping=pb.SubscribeRequestPing(id=1)):
                self.budget.fail('native_unplanned_write')
            self.budget.claim('ping_writes')
        else:
            if self.written or request != self.expected:
                self.budget.fail('filter_rebuild_forbidden')
            self.budget.claim('native_writes')
            self.written = True
        await self.call.write(request)

    async def read(self):
        if self.reading:
            self.budget.fail('native_outstanding_read_bound')
        self.reading = True
        try:
            raw = await self.call.read()
            if raw is not grpc.aio.EOF:
                seen, mono = time.time(), time.monotonic()
                self.budget.receive('yellowstone', raw, lambda payload, size, trailing:
                    self.meter.capture(self.sid, self.family, 'yellowstone', payload, size, trailing, seen, mono))
                self.budget.resources(shutdown=self.budget.stop.is_set())
            return raw
        finally:
            self.reading = False

    def cancel(self):
        if self.cancelled:
            return False
        self.budget.counts['native_cancellations'] += 1
        result = self.call.cancel()
        self.cancelled = True
        return result


class NativeChannel:
    def __init__(self, channel, budget, meter, requests):
        self.channel, self.budget, self.meter, self.requests = channel, budget, meter, requests
        self.current = None
        self.calls = []

    def stream_stream(self, method, **options):
        if method != '/geyser.Geyser/Subscribe' or self.current is None:
            self.budget.fail('native_method_forbidden')
        sid, family = self.current
        self.current = None
        expected = self.requests[family]

        def initiate(**kwargs):
            self.budget.claim('native_rpcs', physical=True)
            call = self.channel.stream_stream(method, **options)(**kwargs)
            wrapped = NativeCall(call, self.budget, self.meter, sid, family, expected)
            self.calls.append(wrapped)
            return wrapped
        return initiate


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise CapabilityStop('http_redirect_forbidden')


class HTTPBoundary:
    """RepairRPC stays single-attempt; count actual POSTs/responses pre-decode."""
    def __init__(self, config, budget, meter, opener=None):
        self.config, self.budget, self.meter = config, budget, meter
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.previous = None

    def open(self, request, *args, **kwargs):
        if not isinstance(request, urllib.request.Request) or request.full_url != self.config.http_url or request.get_method() != 'POST':
            self.budget.fail('http_endpoint_or_method_forbidden')
        body = json.loads(request.data)
        if not isinstance(body, dict) or set(body) != {'jsonrpc', 'id', 'method', 'params'} or body['jsonrpc'] != '2.0' or body['id'] != 1:
            self.budget.fail('http_batch_or_envelope_forbidden')
        self.budget.http(body['method'], body['params'])
        boundary = self

        class Response:
            def __init__(self, response):
                self.response = response
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                self.response.close()
            def read(self, maximum):
                # At most one bounded response is held by the existing RepairRPC.
                chunks = bytearray()
                while len(chunks) < min(maximum, boundary.budget.limits.frame_bytes+1):
                    raw = self.response.read(min(65536, maximum-len(chunks)))
                    if not raw:
                        break
                    seen, mono = time.time(), time.monotonic()
                    boundary.budget.receive('http', raw, lambda payload, size, trailing:
                        boundary.meter.capture('http-'+str(body['id']), body['method'], 'http', payload, size, trailing, seen, mono))
                    chunks.extend(raw)
                if len(chunks) > boundary.budget.limits.frame_bytes:
                    boundary.budget.fail('http_response_frame_bound')
                return bytes(chunks)
        try:
            response = self.opener.open(request, timeout=min(float(kwargs.get('timeout', 0.75)), 0.75))
        except urllib.error.HTTPError as error:
            with Response(error) as response:
                response.read(self.budget.limits.frame_bytes+1)
            self.budget.fail('http_admission_or_transport_error')
        return Response(response)

    def __enter__(self):
        self.previous = urllib.request.urlopen
        urllib.request.urlopen = self.open
        return self

    def __exit__(self, *exc):
        urllib.request.urlopen = self.previous


def validate_headroom(receipt, endpoint_identity, authorization, *, now=time.time):
    if type(receipt) is not dict:
        raise CapabilityStop('current_account_headroom_required')
    expected = dict(native_channels=1, native_subscribe_rpcs=3, websocket_connections=1,
                    websocket_subscriptions=2, candidate_filters=5)
    if (not authorization or receipt.get('authorization_reference') != authorization or
            receipt.get('endpoint_identity') != endpoint_identity or
            receipt.get('app_id') != APP_IDS['pump'] or
            receipt.get('credential_app_binding_verified') is not True or
            receipt.get('additional_experiment_topology') != expected or
            receipt.get('headroom_verified') is not True or
            receipt.get('production_changes_required') is not False or
            type(receipt.get('checked_at')) not in (int, float) or
            type(receipt.get('expires_at')) not in (int, float) or
            not receipt['checked_at'] <= now() < receipt['expires_at'] or
            receipt['expires_at']-receipt['checked_at'] > 300):
        raise CapabilityStop('current_account_headroom_required')


class Executor:
    def __init__(self, out, config, governor, rpc, *, limits=Limits(), ws_connect=connect,
                 channel_factory=None, live=False, clock=time.monotonic, started=None):
        self.out, self.config, self.governor, self.rpc = Path(out), config, governor, rpc
        self.live = live
        if live and clock is not time.monotonic:
            raise CapabilityStop('live_clock_override_forbidden')
        self.budget = Budget(out, limits=limits, clock=clock)
        if started is not None:
            if type(started) not in (int, float) or not 0 < started <= clock():
                raise CapabilityStop('experiment_start_clock_invalid')
            self.budget.started = started
        self.meter = CaptureMeter(self.out/'provider.frames.zlib', self.budget)
        self.evidence = PairedEvidence(self.out, config.identity, self.budget, mono=time.monotonic)
        self.ws_connect = ws_connect
        self.channel_factory = channel_factory or self.secure_channel
        self.source = SelectiveSource(config, rpc)
        self.source.stop = self.budget.stop
        self.source.delivered = self.delivered
        self.source.observer = self.observe
        self.native = None
        self.ws = None
        self.ws_ids = {}
        self.frontiers = {}
        self.acks = asyncio.Event()
        self.logs_ready = asyncio.Event()
        self.tasks = []
        self.unsubscribe_sent = False
        self.unsubscribe_acked = False
        self.paired = None
        self.suppressed = False
        self.cleanup = {}
        self.cpu_started = time.process_time()
        self.io_started = self.process_io()

    @staticmethod
    def process_io():
        return {k: int(v) for k, v in (line.split(':') for line in Path('/proc/self/io').read_text().splitlines())}

    async def delivered(self, *args, **kwargs):
        # Raw accounting was already performed BEFORE the collector decoded it.
        return None

    @staticmethod
    def secure_channel():
        return grpc.aio.secure_channel(HOST, grpc.ssl_channel_credentials(), options=[
            ('grpc.max_receive_message_length', 16*MIB), ('grpc.max_send_message_length', 4*MIB),
            ('grpc.http2.bdp_probe', 0), ('grpc.enable_retries', 0)])

    def observe(self, kind, value):
        if kind == 'subscribe':
            if self.native.current is not None:
                self.budget.fail('native_subscription_race')
            self.native.current = value['stream_id'], value['family']
        if kind == 'delivery':
            # Preserve the existing collector's original receipt clock as well
            # as the earlier raw-meter boundary; never silently replay one as
            # the other. One outstanding read gives an exact per-stream ordinal.
            self.meter.write(dict(kind='collector_delivery_clock', id=value['stream_id'],
                family=value['family'], transport=value['transport'],
                record_ordinal=self.meter.messages[value['transport'], value['family']],
                seen=value['seen'], received_monotonic=value['received_monotonic']))
            return  # NativeCall measured/archived before parsing or routing.
        self.meter(kind, value)
        if kind == 'native_error':
            self.budget.fail('native_admission_or_transport_error')

    async def admission(self, methods):
        # Existing shared provider controls; no private replacement governor live.
        remaining = self.budget.limits.wall_seconds-(self.budget.clock()-self.budget.started)
        if remaining <= 0:
            self.budget.fail('wall_deadline')
        try:
            await asyncio.to_thread(self.governor.acquire, 'solana', 'pump', 50,
                                    deadline_seconds=min(8, remaining), methods=methods)
        except Exception:
            self.budget.fail('shared_admission_error')
        self.budget.resources()

    async def http(self, method, params):
        # Call exactly once. SelectiveSource.measured_rpc would automatically retry.
        result, _ = await asyncio.to_thread(self.rpc.call_delivered, method, params, 4)
        return result

    async def ws_loop(self):
        await self.admission(('websocket_connection',))
        self.budget.claim('ws_connections')
        async with self.ws_connect(self.config.stream_url, max_size=16*MIB, max_queue=1,
                                   ping_interval=None, ping_timeout=None, close_timeout=0.25,
                                   open_timeout=2, compression=None) as ws:
            self.ws = ws
            self.meter('websocket_open', dict(stream_id='capability-ws', addresses=[PROGRAMS[f] for f in FAMILIES]))
            for number, family in enumerate(FAMILIES, 1):
                await self.admission(('logsSubscribe',))
                self.budget.claim('ws_subscribes', physical=True)
                await ws.send(json.dumps(dict(jsonrpc='2.0', id=number, method='logsSubscribe',
                    params=[dict(mentions=[PROGRAMS[family]]), dict(commitment='finalized')])))
            while True:
                raw = await ws.recv()
                raw = raw.encode() if isinstance(raw, str) else raw
                seen, mono = time.time(), time.monotonic()
                self.budget.receive('websocket', raw, lambda payload, size, trailing:
                    self.meter.capture('capability-ws', 'candidate_logs', 'websocket', payload, size, trailing, seen, mono))
                if self.budget.stop.is_set():
                    continue  # Observable cancellation overlap is still charged.
                decode_started = time.monotonic()
                value = candidate_log_message(raw, max_bytes=16*MIB)
                self.meter('decode_timing', dict(transport='websocket', bytes=len(raw), seconds=time.monotonic()-decode_started))
                if 'id' in value:
                    if 'error' in value:
                        self.budget.fail('websocket_admission_error')
                    number = value['id']
                    if number in (1, 2) and type(value.get('result')) is int and number not in self.ws_ids:
                        if value['result'] in self.ws_ids.values():
                            self.budget.fail('websocket_subscription_identity')
                        self.ws_ids[number] = value['result']
                        if len(self.ws_ids) == 2:
                            self.acks.set()
                    elif number == 3 and self.unsubscribe_sent and value.get('result') is True:
                        self.unsubscribe_acked = True
                    else:
                        self.budget.fail('websocket_ack_identity')
                    self.evidence.traffic('websocket', 'ack:'+str(number), None, len(raw), seen)
                    continue
                params = value['params']
                reverse = {v: FAMILIES[k-1] for k, v in self.ws_ids.items()}
                family = reverse.get(params['subscription'])
                if family is None:
                    self.budget.fail('unknown_ws_subscription')
                result = params['result']
                slot = result['context']['slot']
                self.frontiers.setdefault(family, slot)
                if len(self.frontiers) == 2:
                    self.logs_ready.set()
                tx = result['value']
                # The existing intake deliberately leaves failed logs in the
                # native parser. Decode their exact log hash for this audit only;
                # neither join receives failed economic content.
                logs = tx.get('logs') if tx['err'] is None else json.loads(raw)['params']['result']['value']['logs']
                self.evidence.ws(family, slot, tx['signature'], logs, tx['err'], len(raw), seen)
                self.budget.resources()

    async def native_loop(self, request, family):
        await self.admission(('Subscribe',))
        async def handle(update, size, seen):
            if not self.budget.stop.is_set():
                self.evidence.native(family, update, size, seen)
        await self.source.stream(self.native, request, handle, family)
        if not self.budget.stop.is_set():
            self.budget.fail('native_stream_ended_early')

    async def guarded(self, coroutine):
        try:
            return await coroutine
        except BaseException as error:
            if not isinstance(error, asyncio.CancelledError):
                self.budget.shutdown()
                code = reason(error)
                if code not in self.budget.failures:
                    self.budget.failures.append(code)
            raise

    def check_tasks(self):
        for task in self.tasks:
            if task.done() and not task.cancelled():
                exc = task.exception()
                if exc:
                    raise exc
                if not self.budget.stop.is_set():
                    self.budget.fail('transport_ended_early')

    async def until(self, event, seconds):
        deadline = time.monotonic()+seconds
        while not event.is_set():
            self.check_tasks()
            self.budget.resources()
            if self.budget.stop.is_set():
                raise CapabilityStop('startup_cancelled')
            if time.monotonic() >= deadline:
                self.budget.fail('original_ws_frontier_timeout')
            await asyncio.sleep(0.01)

    async def execute(self):
        channel = None
        try:
            if await self.http('getGenesisHash', []) != GENESIS:
                self.budget.fail('solana_genesis_mismatch')
            tip = await self.http('getSlot', [{'commitment': 'finalized'}])
            # Validate all fixed filters before opening a provider stream.
            requests = validate_requests(1, tip)
            control_floor = requests['shared'].from_slot
            for side in (self.evidence.reference, self.evidence.alternative):
                side.control = __import__('meme_machine.solana_candidate_join', fromlist=['CandidateTransactionJoin']).CandidateTransactionJoin(
                    {}, set(), clock=time.monotonic, filtered_from_slot=control_floor, max_join_seconds=120)
            await self.admission(('native_channel',))
            self.budget.claim('channels')
            channel = self.channel_factory()
            self.native = NativeChannel(channel, self.budget, self.meter, requests)
            self.tasks.append(asyncio.create_task(self.guarded(self.ws_loop())))
            for family in ('pump', 'shared'):
                self.tasks.append(asyncio.create_task(self.guarded(self.native_loop(requests[family], family))))
            await self.until(self.acks, 8)
            tip = await self.http('getSlot', [{'commitment': 'finalized'}])
            await self.until(self.logs_ready, 8)
            floor = max(self.frontiers.values())+1
            self.evidence.start(floor, tip, control_floor)
            requests['pumpswap'] = validate_requests(floor, tip)['pumpswap']
            self.tasks.append(asyncio.create_task(self.guarded(self.native_loop(requests['pumpswap'], 'pumpswap'))))
            next_http = self.budget.limits.paired_seconds
            while not self.budget.stop.is_set():
                self.check_tasks()
                self.budget.resources()
                elapsed = self.budget.clock()-self.budget.started
                if self.paired is None and elapsed >= self.budget.limits.paired_seconds:
                    self.paired = self.evidence.compare()
                    if not self.paired['complete']:
                        break
                    await self.admission(('logsUnsubscribe',))
                    self.budget.claim('ws_unsubscribes', physical=True)
                    self.unsubscribe_sent = True
                    await self.ws.send(json.dumps(dict(jsonrpc='2.0', id=3, method='logsUnsubscribe', params=[self.ws_ids[2]])))
                    self.suppressed = True
                    self.evidence.phase = 'suppressed'
                    self.meter.phase = 'suppressed'
                    self.evidence.suppression_floor = max(
                        self.evidence.reference.join.completed, self.evidence.alternative.join.completed)+1
                    tip = await self.http('getSlot', [{'commitment': 'finalized'}])
                    next_http = self.budget.limits.wall_seconds-1
                if self.suppressed and elapsed >= next_http:
                    await self.http('getSlot', [{'commitment': 'finalized'}])
                    next_http = float('inf')
                await asyncio.sleep(0.01)
        except BaseException as error:
            if isinstance(error, asyncio.CancelledError):
                self.budget.failures.append('executor_cancelled')
            else:
                self.budget.failures.append(reason(error))
        finally:
            self.budget.shutdown()
            start = time.monotonic()
            # Cancel gRPC synchronously before awaiting ANY shutdown task. Leave
            # the WS reader active during close to count ACKs/trailing delivery.
            close_failures = []
            if self.native:
                for call in self.native.calls:
                    if not call.cancelled:
                        try:
                            call.cancel()
                        except BaseException:
                            close_failures.append('native_cancel')
            if self.ws:
                try:
                    await asyncio.wait_for(self.ws.close(), 0.5)
                except BaseException:
                    close_failures.append('websocket_close')
            for task in self.tasks:
                task.cancel()
            try:
                await asyncio.wait_for(asyncio.gather(*self.tasks, return_exceptions=True), 0.5)
            except BaseException:
                close_failures.append('task_join')
            if channel:
                try:
                    await asyncio.wait_for(channel.close(grace=0), 0.5)
                except BaseException:
                    close_failures.append('channel_close')
            self.cleanup.update(completed=not close_failures, failed_steps=close_failures,
                                seconds=time.monotonic()-start,
                                native_cancelled=all(c.cancelled for c in self.native.calls) if self.native else True)
            if close_failures:
                self.budget.failures.append('bounded_shutdown_failure')
            self.meter.close()
            try:
                self.budget.resources(shutdown=True)
            except CapabilityStop:
                pass  # Keep the explicit violation and publish an invalid receipt.
            for side in (self.evidence.reference, self.evidence.alternative):
                side.writer.db.set_progress_handler(None, 0)
        # The comparison already taken at the phase boundary retains the exact
        # original timestamps. Shutdown must not perform an unbounded replay.
        paired = self.paired or dict(complete=False, reasons=['paired_window_not_completed'])
        report = dict(schema='pump-alchemy-capability-v1', classification='MEASURED_PROVIDER_APPLICATION' if self.live else 'OFFLINE_SYNTHETIC_TRANSPORT',
            status='INCONCLUSIVE', paired=paired, suppression_attempted=self.suppressed,
            suppression_acknowledged=self.unsubscribe_acked, shutdown=self.cleanup,
            suppression_evidence=self.evidence.suppression_result(),
            budget=self.budget.snapshot(), traffic=self.evidence.traffic_report(paired, self.meter.phase_bytes),
            all_received_components=[dict(phase=p,transport=t,family=f,bytes=n,messages=self.meter.phase_messages[p,t,f])
                                     for (p,t,f),n in sorted(self.meter.phase_bytes.items())],
            native_streams=self.source.stream_telemetry(), production_configuration_changed=False,
            local_decode=dict(self.meter.decode),
            verified_provider_savings_bytes=0,
            blockers=['combined_position_and_candidate_provider_latency_not_certified'],
            engineering_resources=dict(cpu_seconds=time.process_time()-self.cpu_started,
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                sqlite_changes=sum(s.writer.db.total_changes for s in (self.evidence.reference,self.evidence.alternative))+self.evidence.db.total_changes,
                process_io_delta={k:v-self.io_started[k] for k,v in self.process_io().items()}),
            limitations=['No protocol/TLS overhead or vendor invoice measurement.',
                         'No funded positions, long-horizon recovery or market acceptance in this probe.',
                         'Missing/late native facts and original clock differences cannot be normalized away.'])
        self.evidence.close()
        write_receipt(self.out/'result.json', report)
        try:
            self.budget.resources(shutdown=True)
        except CapabilityStop:
            pass
        report['budget'] = self.budget.snapshot()
        write_receipt(self.out/'result.json', report)
        return report


def write_receipt(path, value):
    raw = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode()+b'\n'
    if len(raw) > MIB:
        raise CapabilityStop('receipt_size_bound')
    Path(path).write_bytes(raw)


def load_storage(path):
    path = Path(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != STORAGE_SHA256:
        raise CapabilityStop('existing_engineering_storage_source_required')
    spec = importlib.util.spec_from_file_location('pump_existing_artifact_storage', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def process_rss(pid):
    values = {}
    for line in (Path('/proc')/str(pid)/'status').read_text().splitlines():
        if line.startswith(('VmRSS:', 'VmHWM:')):
            key, n, _ = line.split()
            values[key] = int(n)*1024
    return max(values.values(), default=0)


def supervisor_reason(elapsed, rss, storage, limits=Limits()):
    if elapsed >= limits.wall_seconds:
        return 'supervisor_wall_deadline'
    if rss > limits.rss_bytes:
        return 'supervisor_rss_budget'
    if storage > limits.storage_bytes:
        return 'supervisor_storage_hard_budget'
    if storage >= limits.storage_stop:
        return 'supervisor_storage_stop_threshold'
    return None


def supervise(command, out, *, limits=Limits(), environ=None, started=None):
    started = time.monotonic() if started is None else started
    failure = None
    peak_rss = peak_storage = 0
    stopped_at = None
    killed = False
    def send(child, sig):
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            pass

    with (out/'child.log').open('wb') as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                 env=environ, start_new_session=True)
        try:
            while child.poll() is None:
                elapsed = time.monotonic()-started
                violation = None
                try:
                    peak_rss = max(peak_rss, process_rss(child.pid))
                    peak_storage = max(peak_storage, tree_bytes(out))
                except FileNotFoundError:
                    pass  # Process exit races are handled by poll, never a retry.
                except (CapabilityStop, OSError) as error:
                    violation = reason(error)
                violation = violation or supervisor_reason(elapsed, peak_rss, peak_storage, limits)
                if violation and failure is None:
                    failure, stopped_at = violation, time.monotonic()
                    send(child, signal.SIGTERM)
                # Reserve time inside the two-second deadline for the hard kill
                # and reap. A blocked decoder/governor cannot extend the probe.
                reserve = min(0.05, limits.shutdown_seconds/4)
                if stopped_at is not None and time.monotonic()-stopped_at >= limits.shutdown_seconds-reserve:
                    send(child, signal.SIGKILL)
                    killed = True
                    child.wait(timeout=max(0.001, stopped_at+limits.shutdown_seconds-time.monotonic()))
                    break
                time.sleep(0.005)
        except BaseException:
            send(child, signal.SIGKILL)
            child.wait(timeout=limits.shutdown_seconds)
            raise
    try:
        peak_storage = max(peak_storage, tree_bytes(out))
    except (CapabilityStop, OSError) as error:
        failure = failure or reason(error)
    if peak_storage >= limits.storage_stop:
        failure = failure or supervisor_reason(0, 0, peak_storage, limits)
    receipt = dict(exit_code=child.returncode, reason=failure, hard_kill=killed,
                   wall_seconds=time.monotonic()-started, peak_rss_bytes=peak_rss,
                   peak_storage_bytes=peak_storage, limits=asdict(limits),
                   shutdown_seconds=time.monotonic()-stopped_at if stopped_at is not None else None,
                   shutdown_deadline_exceeded=bool(stopped_at is not None and time.monotonic()-stopped_at > limits.shutdown_seconds),
                   application_bytes_not_observable_after_forced_kill='UNKNOWN' if killed else None,
                   billed_traffic_cap='UNVERIFIED', production_changed=False)
    write_receipt(out/'supervisor.json', receipt)
    return receipt


def main(argv=None):
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-provider-experiment', action='store_true')
    parser.add_argument('--authorization-reference')
    parser.add_argument('--headroom-receipt', type=Path)
    parser.add_argument('--storage-policy-source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.execute_provider_experiment:
        print(json.dumps(offline_plan(), indent=2, sort_keys=True))
        return 0
    if not all((args.authorization_reference, args.headroom_receipt, args.storage_policy_source, args.output)):
        parser.error('live execution requires separate authorization, current headroom, admitted disposable output and the existing storage policy')
    try:
        storage = load_storage(args.storage_policy_source)
        config_env = {k: v for k, v in os.environ.items() if k in ('MM_SOLANA_READ_RPC_URL', 'MM_SOLANA_YELLOWSTONE_TOKEN', 'MM_PROVIDER_GOVERNOR_DB')}
        if args.env_file:
            # Existing credential loader; never print or archive its result.
            from .certify import environment
            config_env.update({k:v for k,v in environment(args.env_file).items()
                               if k in ('MM_SOLANA_READ_RPC_URL', 'MM_SOLANA_YELLOWSTONE_TOKEN')})
        config = AlchemyEndpoint.parse(config_env.get('MM_SOLANA_READ_RPC_URL'))
        if args.headroom_receipt.stat().st_size > 16384:
            raise CapabilityStop('headroom_receipt_bound')
        validate_headroom(json.loads(args.headroom_receipt.read_text()), config.identity, args.authorization_reference)
        governor_path = Path(config_env.get('MM_PROVIDER_GOVERNOR_DB', ''))
        if not governor_path.is_absolute() or not governor_path.is_file():
            raise CapabilityStop('existing_shared_governor_required')
        out = args.output.absolute()
        if out.parent.resolve() != out.parent or out.is_symlink() or not out.name.startswith('mm-engineering-pump-capability-'):
            raise CapabilityStop('new_disposable_engineering_path_required')
        storage.headroom(out.parent, Limits().storage_bytes)
        if not args.child:
            policy = storage.Policy.environment()
            retained = storage.Scratch(out.parent).retained_bytes()
            if retained+Limits().storage_bytes > policy.scratch_total_bytes:
                raise CapabilityStop('existing_engineering_retained_quota')
            out.mkdir(exist_ok=False)
            write_receipt(out/'engineering-artifact.json', dict(classification='DISPOSABLE_PROVIDER_CAPABILITY_ENGINEERING',
                          purpose='Pump/PumpSwap finite probe; no PAPER or portfolio authority', max_bytes=Limits().storage_bytes,
                          supervisor_pid=os.getpid(), started_monotonic=started))
            env = dict(os.environ, **config_env, MM_OPERATIONAL_PHASE='BOUNDED_PUMP_CAPABILITY')
            # Prevent inherited state paths from ever opening a production owner.
            for key in tuple(env):
                if key.startswith('MM_') and key not in config_env and key not in ('MM_OPERATIONAL_PHASE',):
                    env.pop(key)
            env.update(TMPDIR=str(out), SQLITE_TMPDIR=str(out), PYTHONDONTWRITEBYTECODE='1')
            command = [sys.executable, '-m', 'engineering.solana_capacity.capability_executor',
                       *(argv if argv is not None else sys.argv[1:]), '--child']
            receipt = supervise(command, out, environ=env, started=started)
            print(json.dumps(dict(output=str(out), supervisor=receipt), sort_keys=True))
            return int(receipt['hard_kill'] or receipt['shutdown_deadline_exceeded'] or receipt['exit_code'] != 0 or
                       receipt['reason'] not in (None, 'supervisor_wall_deadline'))
        from meme_machine.runtime.governor import Governor
        from meme_machine.runtime.evidence_worker import RepairRPC
        marker = json.loads((out/'engineering-artifact.json').read_text())
        if (marker.get('supervisor_pid') != os.getppid() or marker.get('classification') != 'DISPOSABLE_PROVIDER_CAPABILITY_ENGINEERING'
                or marker.get('started_monotonic') is None):
            raise CapabilityStop('supervised_disposable_child_required')
        governor = Governor(governor_path)
        rpc = RepairRPC(config.http_url, governor)
        executor = Executor(out, config, governor, rpc, live=True, started=marker.get('started_monotonic'))
        executor.source.token = config_env.get('MM_SOLANA_YELLOWSTONE_TOKEN') or config.credential
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: executor.budget.shutdown())
        with HTTPBoundary(config, executor.budget, executor.meter):
            report = asyncio.run(executor.execute())
        return int(bool(set(report['budget']['failures'])-{'wall_deadline'}))
    except Exception as error:
        print(json.dumps(dict(status='INCONCLUSIVE', failure=reason(error), provider_savings_verified_bytes=0)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
