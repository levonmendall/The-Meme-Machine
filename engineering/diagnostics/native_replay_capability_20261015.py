"""One standalone replay-contract experiment; no economic/canonical owners.

Exactly the published diagnostic: fresh unary/HTTP bounds, two required forms,
then at most one INVALID_ARGUMENT-only commitment discriminator. No reconnect.
"""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

import grpc
from google.protobuf.json_format import MessageToDict

from engineering.diagnostics import yellowstone_replay_contract_20261015 as unary
from engineering.solana_capacity.proof_transport import Stream, NoRedirect
from meme_machine.operational.bounded_provider import Budget, MAX_FRAME, CeilingReached
from meme_machine.runtime.governor import Governor
from meme_machine.runtime.operating_families import enabled
from meme_machine.solana_provider_config import AlchemyEndpoint
from meme_machine.solana_selective_source import HOST, CONTROL_OVERLAP, scout_request
from meme_machine.yellowstone import geyser_pb2 as pb

MAX_MESSAGES=64
MAX_BYTES=32*1024**2
OUTPUT_BYTES=1024**2
RESERVE=5*1024**3
COUNTERS=('rpc_cu','alchemy_rpc_cu','rpc_elements','solana_rpc_elements','http_attempts',
    'http_bytes','http_reserved','http_uncertain_bytes','native_opens','native_bytes',
    'native_reserved','native_uncertain_bytes')


class DiagnosticStop(Exception):pass


class Window:
    def __init__(self,origin=None):self.origin=time.monotonic() if origin is None else origin
    def remaining(self,close=False):
        # Leave 100 ms for final ledger/result publication inside the absolute
        # 45-second boundary; the individual close allowance never increases.
        value=self.origin+(44.9 if close else 44)-time.monotonic()
        if value<=0:raise DiagnosticStop('absolute_diagnostic_deadline')
        return value


def record(output,result):
    if len(json.dumps(result).encode())>OUTPUT_BYTES-4096:
        raise DiagnosticStop('diagnostic_output_limit')
    unary.save(output/'result.json',result)


def requests_at(floor):
    if CONTROL_OVERLAP!=256 or enabled('meteora') or enabled('ramses'):
        raise DiagnosticStop('original_overlap_and_paused_families_required')
    control=pb.SubscribeRequest(commitment=pb.FINALIZED,from_slot=floor)
    control.blocks_meta['b'].SetInParent();control.slots['f'].filter_by_commitment=True
    scout=scout_request();scout.from_slot=floor
    return [('control_finalized',control),('scout_finalized',scout)]


def resource_check(root):
    if min(os.statvfs(p).f_bavail*os.statvfs(p).f_frsize for p in (Path('/'),root))<RESERVE:
        raise DiagnosticStop('original_disk_reserve')
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
        if line.startswith('MemAvailable:')))*1024
    if available<2*1024**3 or resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024>=6*1024**3:
        raise DiagnosticStop('original_memory_reserve')


def http_tip(config,budget,governor,window,*,opener=None):
    row=dict(method='getSlot',commitment='finalized',requested_at=unary.now(),status='PRE_DISPATCH')
    row['admission_wait_seconds']=governor.acquire('solana','pump',50,
        deadline_seconds=min(3,window.remaining()),methods=('getSlot',))
    window.remaining()
    receipt=budget.reserve_http(config.http_url,[dict(method='getSlot')])
    response=None
    try:
        timeout=min(5,window.remaining())
        request=Request(config.http_url,data=json.dumps(dict(jsonrpc='2.0',id=1,
            method='getSlot',params=[dict(commitment='finalized')])).encode(),
            headers={'Content-Type':'application/json'})
        row.update(call_invoked_at=unary.now(),call_invoked_monotonic=time.monotonic())
        try:response=(opener or build_opener(ProxyHandler({}),NoRedirect()).open)(request,timeout=timeout)
        except HTTPError as error:response=error
        raw=response.read(65537);receipt.http_delivery(len(raw))
        if len(raw)>65536:raise DiagnosticStop('http_response_bound')
        receipt.eof=True
        row.update(http_status=response.getcode(),response_payload_bytes=len(raw),
            response_body=unary.safe(raw.decode('utf8',errors='replace'),(config.credential,)))
        if response.getcode()!=200:raise DiagnosticStop('http_provider_rejection')
        value=json.loads(raw)
        if value.get('id')!=1 or value.get('error') is not None or type(value.get('result')) is not int:
            raise DiagnosticStop('http_rpc_failure')
        row.update(status='OK',slot=value['result'])
    except BaseException as error:
        row.update(status='FAILED',exception_type=type(error).__name__)
        setattr(error,'diagnostic_http',row);raise
    finally:
        row['completed_at']=unary.now()
        try:
            if response is not None:response.close()
        finally:receipt.close()
    return row


async def stream_once(channel,name,request,token,config,budget,governor,window,output,result):
    row=dict(name=name,status='PRE_DISPATCH',request=MessageToDict(request,preserving_proto_field_name=True),
        request_protobuf_base64=base64.b64encode(request.SerializeToString()).decode(),
        request_sha256=hashlib.sha256(request.SerializeToString()).hexdigest(),
        requested_at=unary.now(),messages=[],messages_delivered=0,bytes_delivered=0,
        reservation_closed=False)
    result['streams'].append(row);record(output,result)
    if len(result['streams'])>3:raise DiagnosticStop('subscription_attempt_limit')
    row['admission_wait_seconds']=governor.acquire('solana','pump',50,
        deadline_seconds=min(3,window.remaining()),methods=('geyser.Geyser/Subscribe',))
    window.remaining()
    reserve=budget.stream_open('yellowstone')  # Counts the physical attempt once.
    stream=None;call=None
    try:
        def decode(raw):
            # Sequential SDK reads only: no prefetch or second consumer. The
            # next read is issued only with a full MAX_FRAME of unused credit.
            budget.native('yellowstone',len(raw),token=reserve)
            result['delivered_protobuf_bytes']+=len(raw)
            row['messages_delivered']+=1;row['bytes_delivered']+=len(raw)
            if len(raw)>MAX_FRAME or result['delivered_protobuf_bytes']>MAX_BYTES or row['messages_delivered']>MAX_MESSAGES:
                raise DiagnosticStop('delivered_resource_bound')
            return raw
        factory=channel.stream_stream('/geyser.Geyser/Subscribe',
            request_serializer=lambda value:value.SerializeToString(),response_deserializer=decode)
        row.update(call_invoked_at=unary.now(),call_invoked_monotonic=time.monotonic(),status='WRITING')
        call=factory(metadata=(('x-token',token),),timeout=min(4,window.remaining()),wait_for_ready=False)
        stream=Stream(call,SimpleNamespace(budget=budget,disconnect_receipt=None,disconnect=False),reserve)
        async with asyncio.timeout(min(3,window.remaining())):
            await stream.write(request)
            row.update(status='READING',write_completed_at=unary.now())
            while row['messages_delivered']<MAX_MESSAGES:
                if MAX_BYTES-result['delivered_protobuf_bytes']<MAX_FRAME:
                    row['status']='BYTE_CREDIT_STOP';break
                raw=await stream.read()
                if raw is grpc.aio.EOF:
                    row['status']='EOF';break
                update=pb.SubscribeUpdate.FromString(raw)
                event=dict(received_at=unary.now(),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
                    protobuf_base64=base64.b64encode(raw).decode(),kind=update.WhichOneof('update_oneof'),
                    filters=list(update.filters))
                if len(json.dumps(event).encode())+len(json.dumps(result).encode())>OUTPUT_BYTES-8192:
                    row['uncaptured_frame']=dict(bytes=len(raw),sha256=event['sha256'])
                    raise DiagnosticStop('exact_response_output_bound')
                row['messages'].append(event);record(output,result)
            else:row['status']='MESSAGE_LIMIT'
    except TimeoutError:
        row['status']=('WRITE_TIMEOUT' if row['status']=='WRITING' else
            'WINDOW_COMPLETE' if row['messages_delivered'] else 'NO_MATCHING_MESSAGES')
    except grpc.aio.AioRpcError as error:
        row.update(status=error.code().name,details=unary.safe(error.details(),(config.credential,token)),
            initial_metadata=unary.metadata(error.initial_metadata(),(config.credential,token)),
            trailing_metadata=unary.metadata(error.trailing_metadata(),(config.credential,token)))
    except BaseException as error:
        row.update(status='LOCAL_FAILURE',exception_type=type(error).__name__)
        raise
    finally:
        try:
            if stream is not None:stream.cancel()
            else:budget.stream_close(reserve,unread_possible=True)
            row['reservation_closed']=True
            if call is not None:
                async with asyncio.timeout(min(1,window.remaining(close=True))):
                    row['rpc_final_status']=(await call.code()).name
                    initial=unary.metadata(await call.initial_metadata(),(config.credential,token))
                    trailing=unary.metadata(await call.trailing_metadata(),(config.credential,token))
                    # Optional post-cancel probes must never replace the
                    # original rejection headers/status, including Retry-After.
                    if 'initial_metadata' not in row:row['initial_metadata']=initial
                    elif initial!=row['initial_metadata']:row['cleanup_initial_metadata']=initial
                    if 'trailing_metadata' not in row:row['trailing_metadata']=trailing
                    elif trailing!=row['trailing_metadata']:row['cleanup_trailing_metadata']=trailing
        except BaseException as error:
            row['cleanup_failure']=type(error).__name__
        row.update(completed_at=unary.now(),completed_monotonic=time.monotonic())
        record(output,result)
    return row


async def experiment(config,token,budget,governor,output,*,channel_factory=None,http=None,
                     window=None,resources=None):
    window=window or Window();output=Path(output);output.mkdir(mode=0o700)
    before=budget.snapshot();origin_cpu=time.process_time()
    result=dict(started_at=unary.now(),origin_monotonic=window.origin,status='STARTING',
        endpoint_host=HOST,endpoint_identity=config.identity,same_channel=True,
        same_backend_node='UNVERIFIED_LOAD_BALANCING_POSSIBLE',calls=[],streams=[],
        delivered_protobuf_bytes=0,paper_starts=0,economic_history_writes=0,
        standing_authority='owner issue134; per-experiment bounds unchanged',
        usage_before={k:before[k] for k in COUNTERS})
    record(output,result);channel=None
    async def work():
        nonlocal channel
        channel=(channel_factory or grpc.aio.secure_channel)(HOST,grpc.ssl_channel_credentials(),options=(
            ('grpc.enable_retries',0),('grpc.max_receive_message_length',MAX_FRAME),
            ('grpc.http2.bdp_probe',0),('grpc.http2.initial_stream_window_size',MAX_FRAME),
            ('grpc.http2.initial_connection_window_size',MAX_FRAME)))
        for method in unary.METHODS:
            row=await unary.unary_call(channel,method,config,token,budget,governor,output,result,
                transport_timeout=min(5,window.remaining()),admission_timeout=min(3,window.remaining()),
                remaining=window.remaining)
            if row['status']!='OK':raise DiagnosticStop('required_unary_failed')
        try:
            row=await asyncio.to_thread(http or http_tip,config,budget,governor,window)
        except BaseException as error:
            if hasattr(error,'diagnostic_http'):result['http_tip']=error.diagnostic_http
            raise
        result['http_tip']=row
        first=result['calls'][0]['first_available'];native=result['calls'][1]['slot']
        floor=row['slot']-256;result.update(native_finalized_slot=native,first_available=first,
            http_finalized_slot=row['slot'],from_slot=floor,http_minus_native_slots=row['slot']-native)
        record(output,result)
        if type(first) is not int or not first<=floor<=native or floor<1:
            raise DiagnosticStop('original_cursor_outside_advertised_native_bounds')
        required=requests_at(floor);rejected=[]
        for name,request in required:
            row=await stream_once(channel,name,request,token,config,budget,governor,window,output,result)
            if row.get('cleanup_failure') or not row['reservation_closed']:raise DiagnosticStop('stream_cleanup_unverified')
            if row['status']=='INVALID_ARGUMENT':rejected.append((name,request))
            elif row['status'] not in ('WINDOW_COMPLETE','MESSAGE_LIMIT'):
                raise DiagnosticStop('required_stream_terminal_or_resource_stop')
        if rejected:
            name,request=rejected[0];comparison=pb.SubscribeRequest();comparison.CopyFrom(request)
            comparison.commitment=pb.CONFIRMED
            row=await stream_once(channel,name+'_confirmed_discriminator',comparison,token,config,
                budget,governor,window,output,result)
            if row.get('cleanup_failure') or not row['reservation_closed']:raise DiagnosticStop('stream_cleanup_unverified')
            if row['status'] not in ('INVALID_ARGUMENT','WINDOW_COMPLETE','MESSAGE_LIMIT'):
                raise DiagnosticStop('comparison_terminal_or_resource_stop')
        result['status']='CAPABILITY_SAMPLE_COMPLETE_NOT_COVERAGE_PROOF'
    task=asyncio.create_task(work())
    try:
        async with asyncio.timeout(window.remaining()):
            while not task.done():
                if resources:resources()
                if time.monotonic()-window.origin>=30 and (time.process_time()-origin_cpu)/(time.monotonic()-window.origin)>1.8:
                    raise DiagnosticStop('original_cpu_limit')
                await asyncio.wait({task},timeout=min(.25,window.remaining()))
            await task
    except BaseException as error:
        result.update(status='STOPPED',stop_type=type(error).__name__,
            stop_reason=(error.reason if isinstance(error,CeilingReached) else
                str(error) if isinstance(error,DiagnosticStop) else type(error).__name__))
    finally:
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        try:
            if channel is not None:
                # Even a pre-dispatch expiry must attempt local channel teardown.
                # No new request is made, and lateness remains a reported failure.
                close_timeout=max(.001,min(1,window.origin+44.9-time.monotonic()))
                await asyncio.wait_for(channel.close(grace=None),close_timeout)
            result['channel_closed']=True
        except BaseException as error:result['channel_closed']=False;result['close_error']=type(error).__name__
        after=budget.snapshot();result.update(completed_at=unary.now(),elapsed_seconds=time.monotonic()-window.origin,
            usage_after={k:after[k] for k in COUNTERS},provider_invoice='UNAVAILABLE')
        result['usage_delta']={k:int(after[k])-int(before[k]) for k in COUNTERS}
        result['absolute_boundary_met']=result['elapsed_seconds']<=45
        try:record(output,result)
        except BaseException as error:
            unary.save(output/'terminal.json',dict(status='STOPPED',error=type(error).__name__,
                elapsed_seconds=result['elapsed_seconds'],source_result='result.json may be partial',
                economic_history_writes=0,paper_starts=0))
    return result


def main():
    import argparse
    window=Window()
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);args=parser.parse_args()
    state=subprocess.check_output(['systemctl','show','meme-machine-paper.service','-p','MainPID',
        '-p','ActiveState','-p','UnitFileState','-p','Restart'],text=True)
    if not all(value in state for value in ('MainPID=0\n','UnitFileState=disabled\n','Restart=no\n')) or not any(
            'ActiveState='+value+'\n' in state for value in ('failed','inactive')):
        raise DiagnosticStop('paper_must_remain_stopped_disabled')
    env=unary.installed_environment()
    for key in ('MM_PROVIDER_OPERATION_MODE','MM_CONTINUOUS_PROVIDER_ENVELOPE','MM_PAPER_POLICY_REVISION'):
        if key in env:os.environ[key]=env[key]
    os.environ['MM_OPERATIONAL_PHASE']='OBSERVATION'
    if env.get('MM_PROVIDER_OPERATION_MODE')!='CONTINUOUS':raise DiagnosticStop('existing_continuous_profile_required')
    config=AlchemyEndpoint.parse(env['MM_SOLANA_READ_RPC_URL']);root=Path(env['MM_STATE_ROOT'])
    budget=Budget(env['MM_PROVIDER_USAGE_DB']);budget.preflight_file(env['MM_CONTINUOUS_PROVIDER_ENVELOPE'])
    if budget.snapshot()['new_risk_ready']!='false':raise DiagnosticStop('funding_must_remain_closed')
    if not (root/'shared/solana-provider.sqlite').is_file():raise DiagnosticStop('existing_governor_required')
    governor=Governor(root/'shared/solana-provider.sqlite')
    if governor.solana_interval!=.5:raise DiagnosticStop('preserve_solana_2rps')
    resource_check(root)
    async def run():
        owner=asyncio.current_task();loop=asyncio.get_running_loop()
        for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,owner.cancel)
        return await experiment(config,env.get('MM_SOLANA_YELLOWSTONE_TOKEN') or config.credential,
            budget,governor,args.output,window=window,resources=lambda:resource_check(root))
    result=asyncio.run(run());print(json.dumps(dict(status=result['status'],output=args.output)))


if __name__=='__main__':main()
