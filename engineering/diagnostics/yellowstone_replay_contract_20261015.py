"""Two authorized unary capability reads; no subscription or application owner.

Usage accounting reuses Budget.change/HTTPReceipt and the existing shared
Governor. HTTP counters include these HTTP/2 unary attempts/payload bytes. The
explicit diagnostic-only price list does not extend production RPC authority.
"""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import uuid

import grpc

from meme_machine.operational.bounded_provider import Budget, HTTPReceipt, MAX_FRAME
from meme_machine.solana_provider_config import AlchemyEndpoint
from meme_machine.solana_selective_source import HOST
from meme_machine.yellowstone import geyser_pb2 as pb

METHODS = ('SubscribeReplayInfo', 'GetSlot')
UNARY_CU = 10  # Alchemy's current published geyser.Geyser unary schedule.
RESPONSE_BOUND = 64 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    # One private parent; no economic state or credentials are published here.
    target = Path(path)
    temporary = target.with_suffix('.tmp')
    with temporary.open('w', encoding='utf8') as file:
        os.chmod(temporary, 0o600)
        json.dump(value, file, indent=2, sort_keys=True)
        file.write('\n');file.flush();os.fsync(file.fileno())
    temporary.replace(target)


def safe(text, secrets):
    text = str(text)
    for secret in secrets:
        if secret:text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'https?://[^\s]+/v2/[^\s]+', '[REDACTED_URL]', text)
    return ''.join(c for c in text if c.isprintable())[:8192]


def metadata(items, secrets):
    allowed = {'server', 'date', 'request-id', 'x-request-id', 'x-alchemy-request-id',
               'retry-after', 'grpc-status', 'grpc-message'}
    return {key: safe(value, secrets)[:512] for key, value in (items or ()) if key in allowed}


async def probe(config, token, budget, governor, output, *, channel_factory=None):
    """Fixed two-call sequence; unsupported methods are retained, never retried."""
    output = Path(output)
    output.mkdir(mode=0o700)  # An existing run is never reused or overwritten.
    secrets = (config.credential, token)
    before = budget.snapshot()
    result = dict(started_at=now(), source='two_unary_calls_no_stream',
        endpoint_host=HOST, endpoint_identity=config.identity,
        token_binding_matches_http_credential=(token == config.credential),
        same_channel=True, same_backend_node='UNVERIFIED_LOAD_BALANCING_POSSIBLE',
        maximum_calls=2, per_call_transport_seconds=5, per_call_admission_seconds=3,
        subscription_calls=0, paper_starts=0, calls=[], usage_before={k:before[k]
            for k in ('rpc_cu','alchemy_rpc_cu','rpc_elements','solana_rpc_elements',
                      'http_attempts','http_bytes','http_reserved','http_uncertain_bytes',
                      'native_opens','native_bytes')})
    save(output/'result.json', result)
    factory = channel_factory or grpc.aio.secure_channel
    channel = factory(HOST, grpc.ssl_channel_credentials(), options=(
        ('grpc.enable_retries', 0), ('grpc.max_receive_message_length', RESPONSE_BOUND)))
    try:
        for method in METHODS:
            row = dict(method='geyser.Geyser/'+method, requested_at=now(),
                status='PRE_DISPATCH', accounted_cu=0, response_payload_bytes=0)
            result['calls'].append(row);save(output/'result.json', result)
            # No production pacer/profile is altered; diagnostics have ordinary
            # low priority and cannot outrank position work.
            row['admission_wait_seconds'] = governor.acquire('solana','pump',50,
                deadline_seconds=3, methods=(row['method'],))
            request = (pb.SubscribeReplayInfoRequest() if method == 'SubscribeReplayInfo'
                       else pb.GetSlotRequest(commitment=pb.FINALIZED))
            response_type = (pb.SubscribeReplayInfoResponse if method == 'SubscribeReplayInfo'
                             else pb.GetSlotResponse)
            identity = budget.prefix + uuid.uuid4().hex
            # Same durable pre-dispatch reservation and closure as existing
            # unary HTTP requests. Only these two read-only diagnostic methods
            # are admitted; PUBLISHED and production transports stay unchanged.
            budget.change(dict(rpc_cu=UNARY_CU, alchemy_rpc_cu=UNARY_CU,
                rpc_elements=1, solana_rpc_elements=1, http_attempts=1,
                http_reserved=MAX_FRAME), receipt=identity)
            receipt = HTTPReceipt(budget, identity)
            def decode(raw):
                receipt.http_delivery(len(raw))
                row['response_payload_bytes'] += len(raw)
                return response_type.FromString(raw)
            call = None
            try:
                row.update(accounted_cu=UNARY_CU, status='DISPATCH_READY')
                save(output/'result.json', result)
                unary = channel.unary_unary('/geyser.Geyser/'+method,
                    request_serializer=lambda value:value.SerializeToString(),
                    response_deserializer=decode)
                # Invocation timestamps, not a claim about HTTP/2 wire time.
                row.update(call_invoked_at=now(),call_invoked_monotonic=time.monotonic(),
                           status='DISPATCHING')
                call = unary(request, metadata=(('x-token',token),), timeout=5,
                             wait_for_ready=False)
                response = await call
                receipt.eof = True
                row.update(status='OK', initial_metadata=metadata(await call.initial_metadata(), secrets),
                    trailing_metadata=metadata(await call.trailing_metadata(), secrets))
                if method == 'SubscribeReplayInfo':
                    row['first_available'] = response.first_available if response.HasField('first_available') else None
                else:row.update(slot=response.slot, commitment='FINALIZED')
            except grpc.aio.AioRpcError as error:
                # Preserve terminal status/details; never dispatch a replacement.
                # Status/trailers alone do not prove that no unread application
                # payload existed. Retain the existing conservative reservation
                # accounting for every unsuccessful transport result.
                row.update(status=error.code().name, details=safe(error.details(), secrets),
                    details_truncated=len(error.details() or '')>8192,
                    initial_metadata=metadata(error.initial_metadata(), secrets),
                    trailing_metadata=metadata(error.trailing_metadata(), secrets))
            except BaseException as error:
                row.update(status='LOCAL_FAILURE',exception_type=type(error).__name__)
                raise
            finally:
                row.update(completed_at=now(), completed_monotonic=time.monotonic())
                if call is not None and not call.done():call.cancel()
                receipt.close()
                save(output/'result.json', result)
    finally:
        await channel.close(grace=None)
        after = budget.snapshot()
        result.update(completed_at=now(), usage_after={k:after[k] for k in result['usage_before']})
        result['usage_delta'] = {k:int(after[k])-int(before[k]) for k in result['usage_before']}
        result['provider_invoice'] = 'UNAVAILABLE'
        save(output/'result.json', result)
    return result


def installed_environment():
    values = {}
    for name in ('paper.shared-1000.env','volume-quality-service.observation.env'):
        for line in (Path('/etc/meme-machine')/name).read_text().splitlines():
            match = re.match(r'^\s*([A-Z][A-Z0-9_]*)=(.*)$', line)
            if match:
                parts = shlex.split(match[2], comments=True)
                if len(parts)>1:raise ValueError('environment_shape')
                values[match[1]] = parts[0] if parts else ''
    return values


def main():
    import argparse
    from meme_machine.runtime.governor import Governor
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);args=parser.parse_args()
    state=subprocess.check_output(['systemctl','show','meme-machine-paper.service',
        '-p','MainPID','-p','ActiveState','-p','UnitFileState','-p','Restart'],text=True)
    if ('MainPID=0\n' not in state or 'Restart=no\n' not in state
            or 'UnitFileState=disabled\n' not in state
            or not any('ActiveState='+s+'\n' in state for s in ('failed','inactive'))):
        raise ValueError('paper_must_remain_stopped_disabled')
    env=installed_environment()
    if env.get('MM_PROVIDER_OPERATION_MODE')!='CONTINUOUS':raise ValueError('existing_continuous_profile_required')
    # Do not inherit an old observation's recorder paths or start any actor.
    for key in ('MM_PROVIDER_OPERATION_MODE','MM_CONTINUOUS_PROVIDER_ENVELOPE',
                'MM_PAPER_POLICY_REVISION'):
        if key in env:os.environ[key]=env[key]
    config=AlchemyEndpoint.parse(env['MM_SOLANA_READ_RPC_URL'])
    budget=Budget(env['MM_PROVIDER_USAGE_DB']);budget.preflight_file(env['MM_CONTINUOUS_PROVIDER_ENVELOPE'])
    if budget.snapshot().get('new_risk_ready')!='false':raise ValueError('funding_must_remain_closed')
    root=Path(env['MM_STATE_ROOT'])
    if not (root/'shared/solana-provider.sqlite').is_file():raise ValueError('existing_governor_required')
    governor=Governor(root/'shared/solana-provider.sqlite')
    if governor.solana_interval != .5:raise ValueError('preserve_existing_solana_2rps')
    asyncio.run(probe(config,env.get('MM_SOLANA_YELLOWSTONE_TOKEN') or config.credential,
        budget,governor,args.output))
    print(json.dumps(dict(output=args.output,paper_started=False,maximum_calls=2)))


if __name__=='__main__':main()
