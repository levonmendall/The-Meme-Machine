"""Bounded read-only transport smoke using the pinned lane's production adapters.

No discovery campaign, qualification, reservation, signer, or broadcast is called.
HTTP success is not promoted to protocol/lifecycle certification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def solana_genesis_call_kwargs(lane):
    if lane not in ('pump','meteora'):raise ValueError('solana_lane_required')
    return dict(priority=True,**({'fresh':True} if lane=='meteora' else {}))


def solana_subscription_request(lane,program):
    if lane=='pump':
        return dict(jsonrpc='2.0',id=1,method='logsSubscribe',
            params=[{'mentions':[program]},{'commitment':'finalized'}])
    if lane=='meteora':
        return dict(jsonrpc='2.0',id=1,method='programSubscribe',
            params=[program,{'commitment':'finalized','encoding':'base64',
                             'filters':[{'dataSize':904}]}])
    raise ValueError('solana_lane_required')


def probe(lane):
    sys.path.insert(0,os.getcwd())
    rows=[]
    def check(role,callback):
        started=time.time()
        try:detail=callback();rows.append(dict(lane=lane,role=role,result='PROVEN',detail=detail,seconds=time.time()-started))
        except Exception as exc:
            # Provider exception strings can contain credentials. Retain only a
            # machine class plus explicitly sanitized adapter telemetry.
            row=dict(lane=lane,role=role,result='FAILED',
                     error_type=type(exc).__name__,seconds=time.time()-started)
            detail=getattr(exc,'connectivity_safe_detail',None)
            if isinstance(detail,dict):row['detail']=detail
            rows.append(row)
    if lane in ('pump','meteora'):
        from meme_machine import pump
        def http():
            if lane=='pump':
                from meme_machine.solana_read_rpc import new_rpc,primary_rpc_url
                primary_rpc_url(required=True)
                rpc=new_rpc(limit=40)
                adapter='pump_solana_read_rpc'
                try:
                    genesis=rpc.call('getGenesisHash',**solana_genesis_call_kwargs(lane))
                except Exception as exc:
                    try:exc.connectivity_safe_detail=dict(
                        adapter=adapter,
                        provider=(rpc.provider_telemetry() if hasattr(rpc,'provider_telemetry') else None))
                    except Exception:pass
                    raise
                provider=(rpc.provider_telemetry() if hasattr(rpc,'provider_telemetry') else None)
            else:
                # Meteora's authoritative reconstruction path is the dedicated
                # authenticated Alchemy adapter, not the generic Pump HTTP topology.
                from tests import dlmm_alchemy_provider as provider_module
                provider_module.alchemy_rpc_url(required=True)
                rpc=provider_module.new_rpc(limit=40)
                adapter='meteora_dlmm_alchemy_provider'
                try:
                    genesis=rpc.call('getGenesisHash',**solana_genesis_call_kwargs(lane))
                except Exception as exc:
                    try:exc.connectivity_safe_detail=dict(
                        adapter=adapter,
                        provider=(rpc.provider_telemetry() if hasattr(rpc,'provider_telemetry') else None))
                    except Exception:pass
                    raise
                provider=(rpc.provider_telemetry() if hasattr(rpc,'provider_telemetry') else None)
            try:
                if genesis!=pump.MAINNET:raise ValueError('wrong_solana_genesis')
            except Exception as exc:
                try:exc.connectivity_safe_detail=dict(
                    adapter=adapter,
                    provider=(rpc.provider_telemetry() if hasattr(rpc,'provider_telemetry') else None))
                except Exception:pass
                raise
            return dict(network='solana_mainnet',genesis=genesis,adapter=adapter,
                provider=provider,
                authentication='authenticated_endpoint_returned_valid_chain_identity',
                schema='genesis_only',full_protocol_schema_verified=False)
        check('authoritative_http',http)
        def ws():
            from websockets.sync.client import connect
            if lane=='pump':
                from meme_machine.solana_read_rpc import discovery_ws_url
                program=pump.PROGRAM;url=discovery_ws_url()
                request=solana_subscription_request(lane,program)
                expected_method='logsNotification'
            else:
                # Mirror ProgramAccountWakeStream exactly: Meteora wakes on
                # finalized 904-byte DLMM program-account changes.
                from meme_machine import dlmm
                from tests.solana_dlmm_independent_v1 import DLMM_DISCOVERY_WS_URL
                program=dlmm.PROGRAM;url=DLMM_DISCOVERY_WS_URL
                request=solana_subscription_request(lane,program)
                expected_method='programNotification'
            with connect(url,open_timeout=5,close_timeout=2,max_size=2_000_000) as socket:
                socket.send(json.dumps(request))
                response=json.loads(socket.recv(timeout=5))
                if response.get('id')!=1 or type(response.get('result')) is not int:raise ValueError('subscription_schema')
            return dict(subscription_acknowledged=True,finalized_requested=True,
                subscription_method=request['method'],expected_notification=expected_method,
                event_normalization_verified=False,market_events_required=False)
        check('public_discovery_websocket',ws)
    else:
        from robinhood_research.provider_topology import configured_rpc,configured_discovery_rpc,configured_dlmm_rpc
        def http(factory):
            rpc=factory(limit=8,per_scope=8,retries=0,timeout=4)
            rpc.verify_chain()
            header=rpc.call('eth_getBlockByNumber',['finalized',False])
            if not isinstance(header,dict) or len(header.get('hash',''))!=66:raise ValueError('header_schema')
            height=int(header['number'],16);stamp=int(header['timestamp'],16)
            if height<=0 or stamp>int(time.time())+5:raise ValueError('header_time')
            return dict(network='robinhood',chain_id=4663,finalized_height=height,
                finalized_hash=header['hash'],finalized_age_seconds=int(time.time())-stamp,
                provider=rpc.telemetry(),protocol_normalization_verified=False)
        if lane=='pons':
            check('authoritative_http',lambda:http(configured_rpc))
            check('discovery_http',lambda:http(configured_discovery_rpc))
            def sequencer():
                from robinhood_research.sequencer_feed import SequencerBlockClock
                feed=SequencerBlockClock(timeout=4)
                try:
                    sequence=feed.wait_for_range_after(-1,timeout=4)
                    if sequence is None or sequence<0:raise ValueError('no_sequencer_message')
                    return dict(sequence=sequence,feed_schema_verified=True,rpc_handoff_verified=False)
                finally:feed.close()
            check('sequencer_websocket',sequencer)
        else:check('dlmm_http',lambda:http(configured_dlmm_rpc))
    return dict(lane=lane,checks=rows,passed=all(r['result']=='PROVEN' for r in rows),
        scope='bounded_transport_smoke_only',paper_positions_created=0,
        full_connectivity_certification=False,
        remaining='Protocol schemas, authenticated WS-to-HTTP handoff, and all method/fallback combinations require separate evidence.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--lane',required=True,choices=('pump','pons','meteora','ramses'))
    parser.add_argument('--output',required=True);args=parser.parse_args()
    result=probe(args.lane);Path(args.output).write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'lane':args.lane,'passed':result['passed']}));sys.exit(0 if result['passed'] else 1)
