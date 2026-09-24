"""Run one pinned lane once with observation-only instrumentation.

No wrapper retries a lane or changes qualification, clocks, finality, ledger state,
or errors. The original lane entrypoint remains authoritative. Every checkpoint
and public RPC response is retained in a run-local append-only journal/archive.
"""
from __future__ import annotations
import argparse
import dataclasses
import functools
import gzip
import hashlib
import importlib
import json
import os
import re
import resource
from pathlib import Path
import sys
import threading
import time
import uuid
from collections import Counter
from urllib.parse import urlsplit
from certification.journal import Journal, canonical, digest
from certification.governor import Governor

class Observer:
    def __init__(self, root, lane, policy):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.lane,self.policy=lane,policy
        self.lock=threading.RLock();self.sequence=0;self.methods=Counter()
        self.latencies=[];self.errors=Counter();self.started=time.monotonic()
        self.provider_method_errors=Counter();self.local_admission_errors=Counter()
        self.provider_http_status_errors=Counter()
        self.provider_rpc_error_codes=Counter()
        self.journal=Journal(self.root/'telemetry.sqlite')
        self.raw=gzip.open(self.root/'rpc-evidence.jsonl.gz','ab')
        self.archive_ns=0;self.journal_ns=0;self.snapshot_ns=0
        self.requests=0;self.raw_records=0;self.provider_sessions={}
        self.alchemy_methods=Counter()
        self.last_progress=None;self.last_report=None
        self.terminal_phase=None
        self.last_activity_write=0
        self.pons_rows=0;self.pons_qualifiers=0;self.pons_lifecycles=set();self.ramses_screens=0;self.ramses_terminals=0;self.ramses_lifecycles=0
        self.meteora_archived={};self.meteora_rejection_counts=Counter()
        self.public_http_requests=0;self.public_http_errors=Counter()
        self.governor=Governor(os.environ["MM_CERT_GOVERNOR_DB"])
        self.context=threading.local()
        self.causal_events=0;self.causal_event_counts=Counter()

    def event(self, kind, body):
        with self.lock:
            before=time.monotonic_ns()
            self.sequence+=1
            identity=f'{os.getpid()}:{self.sequence}'
            self.journal.append(self.lane,identity,kind,body)
            self.journal_ns+=time.monotonic_ns()-before
            return identity

    def transport_activity(self):
        # A completed real transport is process activity, including an explicit
        # provider failure. It is not a claim of successful market evidence.
        now=time.monotonic()
        if now-self.last_activity_write<5:return
        value=dict(lane=self.lane,pid=os.getpid(),process_nonce=PROCESS_NONCE,
            at_monotonic=now,provider_requests=self.requests,method_counts=dict(self.methods),
            estimated_alchemy=__import__('certification.cu',fromlist=['estimate']).estimate(self.alchemy_methods),
            errors=dict(self.errors),provider_method_errors=dict(self.provider_method_errors),
            local_admission_errors=dict(self.local_admission_errors),
            provider_http_status_errors=dict(self.provider_http_status_errors),
            provider_rpc_error_codes=dict(self.provider_rpc_error_codes),
            provider_session_count=len(self.provider_sessions),
            evidence_qualification_inferred=False)
        before=time.monotonic_ns()
        temporary=self.root/'activity.json.tmp';temporary.write_text(canonical(value))
        os.replace(temporary,self.root/'activity.json');self.last_activity_write=now
        self.snapshot_ns+=time.monotonic_ns()-before

    def checkpoint(self, body, phase):
        # Called by the lane's progress path, never by a timer pretending health.
        self.last_progress=time.monotonic()
        if self.lane=='pons':
            path=Path('pons-selective-continuation-v1-cohort/pons-selective-cohort-capital.sqlite')
            if path.exists():
                from robinhood_research.pons_selective_capital import CohortCapital
                from robinhood_research.pons_selective_paper import STRATEGY_CAPITAL_QUOTE
                body=dict(body,cohort_accounting=CohortCapital(path,STRATEGY_CAPITAL_QUOTE).reconcile())
        self.last_report=body
        self.event('checkpoint', dict(phase=phase,report=body,policy_hash=self.policy))
        self.status(phase,body)

    def pons_progress(self,result,snapshot,phase):
        # The lane already fsyncs candidate/provider/lifecycle JSONL files. Store
        # each completed observation once, rather than copying the entire growing
        # cohort into every progress event. No raw observation is removed.
        for key,attribute,kind in (('rows','pons_rows','candidate_observation'),
                                   ('qualifiers','pons_qualifiers','strategy_qualifier')):
            rows=result.get(key,[]);previous=getattr(self,attribute)
            if len(rows)<previous:raise ValueError('pons_observation_history_regressed')
            for index in range(previous,len(rows)):
                self.event(kind,dict(index=index,policy_hash=self.policy,observation=rows[index]))
            setattr(self,attribute,len(rows))
        for life in result.get('lifecycles',[]):
            identity=digest(life)
            if identity not in self.pons_lifecycles:
                self.event('paper_lifecycle',dict(policy_hash=self.policy,lifecycle=life))
                self.pons_lifecycles.add(identity)
        self.checkpoint(dict(snapshot,lifecycles=result.get('lifecycles',[]),
                             observation_archive=dict(candidate_rows=self.pons_rows,
                                 qualifiers=self.pons_qualifiers,journal='telemetry.sqlite')),phase)

    def ramses_progress(self,result,phase):
        """Archive full Ramses observations once; keep repeating checkpoints bounded."""
        screens=result.get('natural_screens') or []
        terminals=result.get('campaign_terminals') or []
        lifecycles=result.get('natural_lifecycles') or []
        for rows,attribute,kind in (
            (screens,'ramses_screens','ramses_screen_observation'),
            (terminals,'ramses_terminals','ramses_campaign_terminal'),
            (lifecycles,'ramses_lifecycles','ramses_natural_lifecycle'),
        ):
            previous=getattr(self,attribute)
            if len(rows)<previous:raise ValueError('ramses_observation_history_regressed')
            for index in range(previous,len(rows)):
                self.event(kind,dict(index=index,policy_hash=self.policy,observation=rows[index]))
            setattr(self,attribute,len(rows))
        snapshot=dict(result)
        snapshot['natural_screens']=[compact_ramses_screen(row) for row in screens]
        snapshot['observation_archive']=dict(
            ramses_screens=self.ramses_screens,
            campaign_terminals=self.ramses_terminals,
            natural_lifecycles=self.ramses_lifecycles,
            journal='telemetry.sqlite',
            full_screen_detail='append_only_once',
        )
        self.checkpoint(snapshot,phase)
        return snapshot

    def meteora_progress(self,result,phase):
        """Archive growing public observations once, preserving the native report.

        Run 35905479952 wrote the same rejection prefixes 1,441 times (414 MB).
        The append-only journal retains every full row; repeating checkpoints use
        counts and locations. Economic/lifecycle fields retain their native shape.
        """
        snapshot=dict(result)
        archived={}
        for field in ('discovery_api_rejections','discovery_errors','discovery_candidates',
                      'compatibility_rejections'):
            rows=result.get(field)
            if not isinstance(rows,list):continue
            previous=self.meteora_archived.get(field,0)
            if len(rows)<previous:raise ValueError('meteora_observation_history_regressed:'+field)
            for index in range(previous,len(rows)):
                self.event('meteora_observation',dict(field=field,index=index,
                    policy_hash=self.policy,observation=rows[index]))
                if field=='discovery_api_rejections':
                    self.meteora_rejection_counts.update(rows[index].get('failed') or ['unknown'])
            self.meteora_archived[field]=len(rows)
            archived[field]=dict(count=len(rows),journal='telemetry.sqlite',kind='meteora_observation')
            snapshot.pop(field,None)
        if 'frozen_policy' in snapshot:
            frozen=snapshot.pop('frozen_policy');identity=digest(frozen)
            previous=self.meteora_archived.get('frozen_policy')
            if previous is None:self.event('meteora_frozen_policy',dict(policy=frozen,sha256=identity))
            elif previous!=identity:raise ValueError('meteora_frozen_policy_changed')
            self.meteora_archived['frozen_policy']=identity
            snapshot['frozen_policy_sha256']=identity
        snapshot['observation_archive']=archived
        snapshot['discovery_api_rejection_counts']=dict(self.meteora_rejection_counts)
        snapshot['public_http_requests']=self.public_http_requests
        snapshot['public_http_errors']=dict(self.public_http_errors)
        self.checkpoint(snapshot,phase)
        return snapshot

    def observe_public_api(self,module):
        """Capture the existing public Meteora read path without issuing calls."""
        original=module._api
        @functools.wraps(original)
        def observed(path,params=None):
            started=time.monotonic();response=None;error=None
            try:
                response=original(path,params)
                return response
            except Exception as exc:
                error=type(exc).__name__
                raise
            finally:
                with self.lock:
                    self.public_http_requests+=1
                    if error:self.public_http_errors[error]+=1
                self.event('public_http_evidence',dict(provider='meteora_public_data',
                    network='solana',path=path,parameters=params,response=response,
                    error_type=error,duration_seconds=time.monotonic()-started,
                    qualification_inferred=False))
        module._api=observed

    def status(self, phase, body=None):
        with self.lock:
            # A delayed background checkpoint is weaker than process terminal
            # truth. It must not resurrect a finished lane in status.json.
            if self.terminal_phase is not None and phase not in ('returned','failed'):
                return
            if self.terminal_phase=='failed' and phase=='returned':
                return
            if phase in ('returned','failed'):
                self.terminal_phase=phase
            before=time.monotonic_ns()
            if body is None:body=self.last_report
            lat=sorted(self.latencies)
            quant=lambda f: None if not lat else lat[min(len(lat)-1,int((len(lat)-1)*f))]
            data=dict(lane=self.lane,pid=os.getpid(),process_nonce=PROCESS_NONCE,
                      phase=phase,policy_hash=self.policy,wall_time=time.time(),
                      uptime_seconds=time.monotonic()-self.started,
                      last_progress_monotonic=self.last_progress,
                      provider_requests=self.requests,method_counts=dict(self.methods),
                      errors=dict(self.errors),provider_method_errors=dict(self.provider_method_errors),
                      local_admission_errors=dict(self.local_admission_errors),
            provider_http_status_errors=dict(self.provider_http_status_errors),
                      provider_rpc_error_codes=dict(self.provider_rpc_error_codes),
                      provider_session_count=len(self.provider_sessions),
                      rpc_latency_seconds=dict(p50=quant(.5),p95=quant(.95),p99=quant(.99)),
                      telemetry_archive_seconds=self.archive_ns/1e9,
                      telemetry_cost=dict(raw_archive_seconds=self.archive_ns/1e9,
                          journal_append_seconds=self.journal_ns/1e9,
                          snapshot_seconds=self.snapshot_ns/1e9,
                          scope='serialized observer wall time; excludes strategy-native telemetry, lock wait and final snapshot'),
                      runtime_resources=process_resources(),
                      estimated_alchemy=__import__('certification.cu',fromlist=['estimate']).estimate(self.alchemy_methods),
                      report=body,
                      terminal_monotonic=time.monotonic() if phase in ("returned","failed") else None)
            raw=canonical(data);tmp=self.root/'status.json.tmp';tmp.write_text(raw);os.replace(tmp,self.root/'status.json')
            self.snapshot_ns+=time.monotonic_ns()-before

    def install_candidate_context(self):
        # Lane-local thread scope: background discovery threads do not inherit a
        # foreground candidate, and terminal records clear that attribution.
        package='meme_machine' if self.lane in ('pump','meteora') else 'robinhood_research'
        pipeline=importlib.import_module(package+'.pipeline').Pipeline
        original=pipeline.record;observer=self
        @functools.wraps(original)
        def record(instance,candidate,stage,reason=None,classification=None,**details):
            if stage not in ('trigger_started','trigger_terminal'):
                if stage in ('terminal','settled','entry_cancelled','rejected','evidence_not_required'):
                    observer.context.candidate=None
                    observer.context.obligation=None
                else:
                    observer.context.candidate=str(candidate)
                    observer.context.obligation=str(details.get('observation_id') or
                        details.get('decision_at') or details.get('lifecycle_id') or stage)
            return original(instance,candidate,stage,reason,classification,**details)
        pipeline.record=record

    def causal_event(self,kind,body):
        # New detailed reuse telemetry has a fixed storage budget. Exact totals
        # remain available after sampling fills; no authority uses these counters.
        with self.lock:
            self.causal_event_counts[kind]+=1
            if self.causal_events>=2048:return
            self.causal_events+=1
            self.event('candidate_evidence_cause',dict(kind=kind,**body))

    def install_reuse_context(self):
        observer=self
        if self.lane in ('pump','meteora'):
            from meme_machine.solana_evidence_broker import EvidenceBroker
            original=EvidenceBroker.hydrate_transactions
            @functools.wraps(original)
            def hydrate(instance,rpc,signatures,**kwargs):
                result=original(instance,rpc,signatures,**kwargs)
                observer.causal_event('solana_hydration',dict(
                    candidate=getattr(observer.context,'candidate',None),
                    acquisition_candidate=kwargs.get('candidate_id'),owner=kwargs.get('owner'),
                    obligation=kwargs.get('kind'),deadline=kwargs.get('deadline'),
                    result=result[1]))
                return result
            EvidenceBroker.hydrate_transactions=hydrate
        else:
            from robinhood_research.immutable_rpc import Reuse
            original=Reuse.lookup
            @functools.wraps(original)
            def lookup(instance,method,params,*args,**kwargs):
                result=original(instance,method,params,*args,**kwargs)
                observer.causal_event('immutable_reuse',dict(
                    candidate=getattr(observer.context,'candidate',None),
                    obligation=getattr(observer.context,'obligation',None),
                    method=method,endpoint_identity=instance.domain,
                    parameter_identity=digest(params),hit=bool(result[0])))
                return result
            Reuse.lookup=lookup

    def finalize_causal(self):
        from certification.causal import reconcile,native_states
        paths=sorted(Path.cwd().rglob('*.pipeline.sqlite'))
        paths+=sorted(Path.cwd().rglob('opportunity-pipeline.sqlite'))
        summaries=[]
        report=self.last_report
        native_report=Path('robinhood-ramses-extended-market-report.json')
        # Native terminal persistence can be newer than the last observer checkpoint.
        # Bound the optional read; omission is explicit and never invents a settlement.
        native_report_omitted=False
        if self.lane=='ramses' and native_report.is_file():
            if native_report.stat().st_size<=2*1024*1024:
                report=json.loads(native_report.read_text())
            else:native_report_omitted=True
        for index,path in enumerate(dict.fromkeys(paths)):
            summaries.append(dict(source=str(path.relative_to(Path.cwd())),
                **reconcile(path,rows_path=self.root/f'candidate-causal-{index}.jsonl',
                    native_states=native_states(self.lane,report,path))))
        (self.root/'candidate-causal-summary.json').write_text(canonical(dict(
            lane=self.lane,pipelines=summaries,market_authority=False,
            reuse_causal_samples=self.causal_events,reuse_causal_counts=dict(self.causal_event_counts),
            reuse_causal_sample_limit=2048,native_report_omitted=native_report_omitted))+'\n')

    def observe_work(self,module,name,stage):
        original=getattr(module,name)
        @functools.wraps(original)
        def measured(*args,**kwargs):
            started=time.monotonic();outcome='returned';error=None
            try:return original(*args,**kwargs)
            except BaseException as exc:
                outcome='exception';error=type(exc).__name__;raise
            finally:
                self.event('evidence_work',dict(stage=stage,duration_seconds=time.monotonic()-started,
                    outcome=outcome,error_type=error,qualification_inferred=False))
        setattr(module,name,measured)

    def prioritize(self, module, name):
        original=getattr(module,name)
        @functools.wraps(original)
        def run(*args,**kwargs):
            previous=getattr(self.context,'priority',50)
            self.context.priority=0
            try:return original(*args,**kwargs)
            finally:self.context.priority=previous
        setattr(module,name,run)

    def wrap_transport(self, cls, name, *, batch=False, solana=False, local_error_type=TimeoutError):
        original=getattr(cls,name)
        observer=self
        @functools.wraps(original)
        def observed(instance,*args,**kwargs):
            started=time.monotonic_ns();result=None;error=None;http_status=None;rpc_error_codes=[];transport_started=None
            # Use only opaque session identities. Never archive endpoint URLs.
            with observer.lock:
                if not hasattr(instance,'_certification_session_id'):
                    instance._certification_session_id=str(uuid.uuid4())
                session=instance._certification_session_id
                observer.provider_sessions[session]=True
            network="solana" if solana else "robinhood"
            provider=provider_identity(instance,network)
            queue_wait=None
            if solana:
                request=args[0]
                calls=request if isinstance(request,list) else [request]
                methods=[x.get('method','unknown') for x in calls]
                wire=calls
            elif batch:
                wire=list(args[0]);methods=[x[0] for x in wire]
            else:
                methods=[args[0]];wire=[(args[0],args[1])]
            instance.evidence_local_failure=None
            try:
                priority=getattr(observer.context,"priority",10 if solana else 50)
                if priority!=0:priority=getattr(instance,'evidence_priority',priority)
                evidence_deadline=getattr(instance,'evidence_deadline',None)
                remaining=30 if evidence_deadline is None else min(30,evidence_deadline-(time.time() if solana else time.monotonic()))
                if remaining<=0:raise local_error_type('evidence_deadline_before_transport')
                queue_wait=(observer.governor.acquire(
                    network,observer.lane,priority,deadline_seconds=remaining,
                    methods=methods)
                            if solana or not os.environ.get("MM_CERTIFICATION_PROVIDER_DB") else None)
                callback=getattr(instance,'evidence_transport_callback',None)
                if callback is not None:callback()
                transport_started=time.monotonic_ns()
                result=original(instance,*args,**kwargs)
                http_status=200
                if solana:
                    replies=result if isinstance(result,list) else [result]
                    rpc_error_codes=[x['error'].get('code') for x in replies
                                     if isinstance(x,dict) and isinstance(x.get('error'),dict)]
                return result
            except BaseException as exc:
                message=str(exc)
                http_status=getattr(exc,'code',None)
                match=re.fullmatch(r'provider_http_(\d+)',message)
                if match:http_status=int(match[1])
                match=re.fullmatch(r'provider_rpc_(-?\d+)',message)
                if match:rpc_error_codes=[int(match[1])]
                # Only stable code-shaped errors are emitted; no free-form URLs.
                error=message if message.replace('_','').replace('-','').isalnum() and len(message)<160 else type(exc).__name__
                # Admission happens outside the native HTTP error boundary. Keep
                # its lane-native exception contract so one expired consumer
                # cannot terminate the whole observer/cohort process.
                if transport_started is None and isinstance(exc,TimeoutError):
                    raise local_error_type(error) from None
                raise
            finally:
                elapsed=(time.monotonic_ns()-started)/1e9
                with observer.lock:
                    observer.raw_records+=1
                    transport_elapsed=None
                    if transport_started is not None:
                        transport_elapsed=(time.monotonic_ns()-transport_started)/1e9
                        observer.requests+=1;observer.methods.update(methods);observer.latencies.append(transport_elapsed)
                        if provider['provider_kind']=='alchemy':observer.alchemy_methods.update(methods)
                    unique_methods=list(dict.fromkeys(methods))
                    if error:
                        observer.errors[error]+=1
                        for method in unique_methods:
                            target=(observer.provider_method_errors if transport_started is not None
                                    else observer.local_admission_errors)
                            target[f"{method}:{error}"]+=1
                        if transport_started is None:instance.evidence_local_failure=error
                    if http_status is not None and http_status!=200:
                        for method in unique_methods:
                            observer.provider_http_status_errors[
                                f"{method}:{int(http_status)}"]+=1
                            if int(http_status)==429:
                                observer.errors[f"{method}:http_429"]+=1
                    for code in rpc_error_codes:
                        for method in unique_methods:
                            observer.provider_rpc_error_codes[
                                f"{method}:{code}"]+=1
                            if code in (429,-32005):
                                observer.errors[f"{method}:rpc_{code}"]+=1
                    limited=(http_status==429 or 429 in rpc_error_codes or -32005 in rpc_error_codes
                             or (error and "429" in error))
                    if limited and (solana or not os.environ.get("MM_CERTIFICATION_PROVIDER_DB")):
                        observer.governor.rate_limited(network,unique_methods)
                    elif (transport_started is not None and error is None
                          and not rpc_error_codes
                          and (solana or not os.environ.get("MM_CERTIFICATION_PROVIDER_DB"))):
                        observer.governor.succeeded(network,unique_methods)
                    before=time.monotonic_ns()
                    record=dict(sequence=observer.raw_records,lane=observer.lane,session=session,
                                provider=provider,
                                candidate=getattr(observer.context,'candidate',None),
                                candidate_attribution_scope='requesting caller; shared batch consumers remain linked by signature',
                                evidence_obligation=getattr(observer.context,'obligation',None),
                                transport_attempted=transport_started is not None,transport_duration_seconds=transport_elapsed,
                                transport_started_monotonic_ns=transport_started,
                                observed_at_ns=time.time_ns(),duration_seconds=elapsed,
                                request=wire,response=result,error=error,queue_wait_seconds=queue_wait,
                                physical_request_id=f'{session}:{observer.raw_records}',
                                parameter_identity=digest(wire),original_deadline=evidence_deadline,
                                failure_domain=('local_admission' if error and transport_started is None
                                                else 'provider' if error else None),
                                http_status=http_status,json_rpc_error_codes=rpc_error_codes,
                                retry_count=getattr(instance,"retry_count",getattr(instance,"retries",None)),
                                evidence_priority=priority,evidence_kind=getattr(instance,'evidence_kind',None),
                                authentication='raw_transport_response_requires_lane_verification')
                    observer.raw.write((canonical(record)+'\n').encode());observer.raw.flush();os.fsync(observer.raw.fileno())
                    observer.archive_ns+=time.monotonic_ns()-before
                    observer.event('rpc_transport',dict(sequence=observer.raw_records,session=session,transport_attempted=transport_started is not None,
                        provider=provider,
                        methods=methods,duration_seconds=elapsed,transport_duration_seconds=transport_elapsed,error=error,http_status=http_status,
                        json_rpc_error_codes=rpc_error_codes,queue_wait_seconds=queue_wait,raw_hash=digest(record)))
                    if transport_started is not None:observer.transport_activity()
        setattr(cls,name,observed)

def provider_identity(instance,network):
    endpoint=getattr(instance,'_endpoint',None) or getattr(instance,'url',None)
    if not isinstance(endpoint,str):endpoint=''
    host=(urlsplit(endpoint).hostname or '').lower()
    kind=('alchemy' if host=='alchemy.com' or host.endswith('.alchemy.com')
          else 'robinhood_public' if host=='rpc.mainnet.chain.robinhood.com'
          else 'solana_public' if host=='api.mainnet-beta.solana.com'
          else 'configured_provider' if host else 'unknown')
    return dict(network=network,endpoint_identity=hashlib.sha256(endpoint.encode()).hexdigest() if endpoint else None,
                provider_kind=kind,role=getattr(instance,'role',None))


def compact_ramses_screen(screen):
    """Bounded public/checkpoint projection; full screen is retained in telemetry.sqlite."""
    if not isinstance(screen,dict):raise ValueError('ramses_screen_shape')
    rows=[]
    for row in screen.get('rows') or []:
        if not isinstance(row,dict):continue
        cost=row.get('cost_evidence') or {}
        rows.append(dict(
            pool=row.get('pool'),swaps=row.get('swaps'),
            turnover_bps=row.get('turnover_bps'),
            turnover_percentile_bps=row.get('turnover_percentile_bps'),
            fee_percentile_bps=row.get('fee_percentile_bps'),
            volume_acceleration_milli=row.get('volume_acceleration_milli'),
            chop_ratio_milli=row.get('chop_ratio_milli'),
            flow_imbalance_bps=row.get('flow_imbalance_bps'),
            mode=row.get('mode'),qualified=row.get('qualified'),
            reasons=row.get('reasons'),
            evidence_status=row.get('evidence_status'),
            cost_evidence=dict(
                available=cost.get('available'),
                source=cost.get('source'),
                reason=cost.get('reason'),
            ),
        ))
    provider=screen.get('provider') or {}
    return dict(
        finalized_block=screen.get('finalized_block'),
        finalized_timestamp=screen.get('finalized_timestamp'),
        factory_pool_count=screen.get('factory_pool_count'),
        pools_with_recent_swaps=screen.get('pools_with_recent_swaps'),
        state_complete_pools=screen.get('state_complete_pools'),
        qualified=screen.get('qualified'),
        rows=rows,
        cost_model=screen.get('cost_model'),
        pools_with_automatic_cost_evidence=screen.get('pools_with_automatic_cost_evidence'),
        elapsed_seconds=screen.get('elapsed_seconds'),
        frontier_poll_index=screen.get('frontier_poll_index'),
        provider=dict(
            requests=provider.get('requests'),
            transport_requests=provider.get('transport_requests'),
            logical_requests=provider.get('logical_requests'),
            retries=provider.get('retries'),
            failures=provider.get('failures'),
            sessions=provider.get('sessions'),
            max_sessions=provider.get('max_sessions'),
            rate_limit_events=provider.get('rate_limit_events'),
        ),
        full_detail_archive='telemetry.sqlite:ramses_screen_observation',
    )


PROCESS_NONCE=str(uuid.uuid4())


def process_resources():
    usage=resource.getrusage(resource.RUSAGE_SELF)
    return dict(cpu_user_seconds=usage.ru_utime,cpu_system_seconds=usage.ru_stime,
        maximum_resident_bytes=usage.ru_maxrss*(1024 if sys.platform!='darwin' else 1),
        available_logical_cpus=len(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else os.cpu_count(),
        scope='lane process including all threads; CPU cumulative, RSS high-water mark')


def persist_pons_terminal(path,result):
    # Native cohort __main__ uses 12 MB for its final report. Its _atomic_json
    # helper is a different, 4 MB progress-checkpoint contract.
    raw=json.dumps(result,sort_keys=True,separators=(',',':')).encode()
    if len(raw)>12_000_000:raise ValueError('selective_cohort_report_capacity')
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    with temporary.open('wb') as handle:
        handle.write(raw);handle.flush();os.fsync(handle.fileno())
    os.replace(temporary,path)

def policy_for(lane):
    if lane=='pump':
        from meme_machine.pump_acceleration_strategy import policy_hash
        return policy_hash()
    if lane=='meteora':
        path=Path('SOLANA_DLMM_INDEPENDENT_V1.json')
        source=json.loads((Path(__file__).parent/'sources.json').read_text())['lanes']['meteora']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=source['file_hashes'][path.name]:
            raise ValueError('frozen_source_file_drift:meteora')
        # The execution policy embeds a label predating its description/duplicate-field
        # synchronization. Bind the label to exact source bytes, never trust it alone.
        return source['policy_hash']
    name='pons_selective_continuation' if lane=='pons' else 'ramses_strategy'
    return importlib.import_module('robinhood_research.'+name).POLICY_HASH


def main():
    p=argparse.ArgumentParser();p.add_argument('--lane',required=True);p.add_argument('--output',required=True)
    p.add_argument('--campaign',action='store_true');p.add_argument('--policy-hash',required=True);p.add_argument('--seconds',type=int,required=True)
    args=p.parse_args()
    # Lane source precedes the certification repository, including its tests package.
    sys.path.insert(0,os.getcwd())
    actual=policy_for(args.lane)
    if actual!=args.policy_hash:raise ValueError('frozen_policy_hash_changed')
    observer=Observer(args.output,args.lane,actual)
    from certification.decision_conformance import install as install_conformance
    conformance=install_conformance(args.output,args.lane,actual)
    observer.install_candidate_context()
    observer.install_reuse_context()
    observer.checkpoint(dict(source_sha=os.environ['MM_CERT_SOURCE_SHA']),'initializing')
    if args.lane in ('pump','meteora'):
        from meme_machine.solana_read_rpc import _ReadOnlyFailoverMixin
        observer.wrap_transport(_ReadOnlyFailoverMixin,'_http',solana=True)
    else:
        from robinhood_research import BoundaryError
        from robinhood_research.provider import Rpc
        observer.wrap_transport(Rpc,'_http',local_error_type=BoundaryError)
        observer.wrap_transport(Rpc,'_http_batch',batch=True,local_error_type=BoundaryError)
    try:
        if args.lane=='pump':
            os.environ['MM_PUMP_ACCELERATION_DISCOVERY_SECONDS']=str(args.seconds)
            module=importlib.import_module('tests.pump_acceleration_natural_prospective')
            observer.prioritize(module,"_fill_pending")
            observer.prioritize(module,"_monitor_positions")
            observer.observe_work(module,'_refresh_pool_events','pumpswap_candidate_or_position_window')
            observer.observe_work(module,'_postgrad_concentration','pumpswap_concentration')
            original=module._save
            def save(report):
                original(report);observer.checkpoint(report,'lane_checkpoint')
            module._save=save;module.main(campaign=args.campaign,discovery_seconds=args.seconds)
        elif args.lane=='meteora':
            module=importlib.import_module('tests.solana_dlmm_independent_v1')
            from certification.lifecycle_timing import install_meteora
            install_meteora(module)
            observer.observe_public_api(module)
            observer.prioritize(module,"_lifecycle")
            observer.observe_work(module,'_triggered_warmup','fresh_trigger_and_exact_warmup')
            observer.observe_work(module,'_await_fresh_swap_trigger','dlmm_fresh_swap_trigger')
            observer.observe_work(module,'_observe_window','dlmm_window_reconstruction')
            observer.observe_work(module,'_complete_signature_census','dlmm_signature_census')
            original=module._atomic_checkpoint
            def checkpoint(report,stage,*a,**kw):
                result=original(report,stage,*a,**kw)
                observer.meteora_progress(report,stage);return result
            module._atomic_checkpoint=checkpoint
            module.run_live(target=6,max_attempted=48,max_runtime_seconds=args.seconds,campaign=args.campaign)
        elif args.lane=='pons':
            os.environ['MM_PONS_SELECTIVE_DISCOVERY_SECONDS']=str(args.seconds)
            module=importlib.import_module('robinhood_research.pons_selective_cohort')
            observer.prioritize(module,"run_lifecycle")
            observer.observe_work(module,'evaluate_candidate','pons_candidate_evidence_and_evaluation')
            original=module._checkpoint
            def checkpoint(result,**kw):
                value=original(result,**kw);observer.pons_progress(result,value,kw['phase']);return value
            module._checkpoint=checkpoint
            result=module.run(os.environ.get('MM_ROBINHOOD_READ_RPC_URL',''),campaign=args.campaign)
            result=module.persist_terminal(result)
            observer.checkpoint(result,'lane_result')
        else:
            module=importlib.import_module('robinhood_research.ramses_extended_test')
            from certification.lifecycle_timing import install_ramses
            install_ramses(module)
            # Observe completed authentic scans and frontier checks without replacing
            # the discovery or lifecycle algorithm. Startup/scan stalls stay visible.
            observer.prioritize(module,"run_connected")
            observer.prioritize(module,"_forced_machinery")
            observer.observe_work(module,'scan','ramses_finalized_pool_scan')
            # Only the complete native checkpoint can replace the aggregate view.
            # Gate-only/scan-only dictionaries used to erase completed scans and
            # durable capital books on every frontier poll.
            os.environ['MM_ROBINHOOD_RAMSES_EXTENDED_DISCOVERY_SECONDS']=str(args.seconds)
            original_persist=module._persist_public_result
            def persist(result):
                snapshot=observer.ramses_progress(result,'campaign_checkpoint')
                original_persist(snapshot)
            module._persist_public_result=persist
            module.main(campaign=args.campaign)
        observer.finalize_causal()
        observer.event('process_terminal',dict(status='returned',policy_hash=policy_for(args.lane)))
        observer.status('returned')
    except BaseException as exc:
        terminal=dict(status='failed',exception_type=type(exc).__name__,policy_hash=policy_for(args.lane))
        if args.lane=='ramses' and type(exc).__name__=='BoundaryError':
            message=str(exc)
            terminal['boundary']=(message if re.fullmatch(r'[A-Za-z0-9_.:\\-]+',message) and len(message)<160
                                  else 'non_code_boundary')
        observer.event('process_terminal',terminal)
        report=observer.last_report
        if args.lane=='ramses' and isinstance(report,dict):
            report=dict(report,process_terminal=terminal)
        observer.status('failed',report)
        raise
    finally:
        conformance.close()
        observer.raw.close();observer.journal.close()

if __name__=='__main__':main()
