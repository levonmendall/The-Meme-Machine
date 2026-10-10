"""Bounded physical workers for the existing durable Current controllers.

Eight entry workers and eight protected-owner workers are separately bounded.
Native connections never cross threads. The existing durable handoff/recovery
boundary transfers a newly filled owner and its authenticated provider session,
without a new purchase or changed initial monitor deadline. There is no position
count admission rule or additional durable state here.
"""
from concurrent.futures import Future,ThreadPoolExecutor
from contextvars import copy_context
import heapq
import threading
import time

from . import BoundaryError


def held_acquisition_request(endpoint,rpc,history,position,state,gas_units,token):
    """Copy neutral obligations on the native owner's SQLite thread."""
    from copy import deepcopy
    from meme_machine.runtime.journal import digest
    if (history is None or state.transition is None or not state.post_grad_checked
            or state.pending_action is not None or position['status']!='open'):
        return None
    raw=getattr(rpc,'_current',rpc);resources=getattr(raw,'shared_quote_resources',None)
    if not isinstance(resources,dict) or resources.get('validated') is not True:return None
    checkpoint=history.get(position['market'])
    if checkpoint is None:return None
    retained=history.v4_window_candidates(position['market'],max(0,checkpoint['through']-15))
    if len(retained)>2048:return None  # private native path, not an admission veto
    return dict(identity=position['id'],position_hash=digest(position),rpc=raw,endpoint=endpoint,
        provider_fingerprint=getattr(raw,'provider_fingerprint',None),source_generation=history.source_generation,
        key=state.v4_key,pool_id=position['market'],amount=position['tokens'],gas_units=gas_units,token=token,
        checkpoint=deepcopy(checkpoint),retained=deepcopy(retained),preholders=tuple(state.preholders),side='sell')


def exit_acquisition_request(endpoint,rpc,position,key,gas_units):
    """A durable native intent; no worker owns this data across its thread."""
    raw=getattr(rpc,'_current',rpc);resources=getattr(raw,'shared_quote_resources',None)
    if (key is None or position['status']!='exit_pending' or not isinstance(resources,dict)
            or resources.get('validated') is not True):return None
    from meme_machine.runtime.robinhood.pons import shared_evidence_domain
    from .evidence import digest
    return dict(identity=position['id'],position_hash=digest(position),rpc=raw,endpoint=endpoint,
        provider_fingerprint=getattr(raw,'provider_fingerprint',None),provider_session=id(raw),
        source_generation=shared_evidence_domain(endpoint),key=key,pool_id=position['market'],
        amount=int(position['pending_exit_tokens']),gas_units=gas_units,side='sell',execution=True)


def acquire_current_exits(requests,deadline):
    from .provider_admission import position_work
    from meme_machine.runtime.provider_purchases import attributed_work
    @position_work
    @attributed_work('pons_held_protection',consumer='current')
    def acquire():
        from .pons_quotes import shared_v4_quotes
        from meme_machine.runtime.robinhood.pons import shared_evidence_domain
        rpc=requests[0]['rpc'];endpoint=requests[0]['endpoint']
        if any(r['source_generation']!=shared_evidence_domain(endpoint) for r in requests):
            raise BoundaryError('pons_current_shared_source_changed')
        quotes=shared_v4_quotes(rpc,requests,deadline_seconds=5,deadline_at=deadline)
        return {r['identity']:dict(q,position_hash=r['position_hash'],
            provider_fingerprint=r['provider_fingerprint'],source_generation=r['source_generation'],deadline=deadline)
            for r,q in zip(requests,quotes)}
    return acquire()


def acquire_current_owners(requests,deadline):
    """The existing quote/range adapters, without moving native connections."""
    from .provider_admission import position_work
    from meme_machine.runtime.provider_purchases import attributed_work
    @position_work
    @attributed_work('pons_held_protection',consumer='current')
    def acquire():
        from .pons_quotes import shared_v4_quotes
        from .pons_selective_v4 import collect_v4_activities
        from .pons_selective_acquisition import SelectiveEvidenceContext
        from meme_machine.runtime.robinhood.pons import shared_evidence_domain
        rpc=requests[0]['rpc'];endpoint=requests[0]['endpoint'];prepared={}
        def history(header,state_calls):
            top=int(header['number'],16);at=int(header['timestamp'],16);cutoff=max(0,at-15)
            expected={top:header['hash']}
            for r in requests:
                old=r['checkpoint']
                if (r['source_generation']!=shared_evidence_domain(endpoint)
                        or not old['from_time']<=cutoff<old['through']
                        or not 0<=top-old['block']<=40):
                    raise BoundaryError('pons_current_shared_history_incomplete')
                if old['block'] in expected and expected[old['block']]!=old['block_hash']:
                    raise BoundaryError('pons_current_shared_checkpoint_conflict')
                expected[old['block']]=old['block_hash']
                older=[e for e in r['retained'] if e['event_at']<=cutoff]
                boundary=max((e['block'] for e in older),default=None)
                if boundary is not None and boundary<top:expected.setdefault(boundary+1,None)
            context=SelectiveEvidenceContext(endpoint);context.rpc=rpc;context.deadline=rpc.evidence_deadline
            start=min(r['checkpoint']['block'] for r in requests)+1;values=[]
            if start>top:
                values=rpc.batch(state_calls,scope='pons_paper')
                pins=getattr(rpc,'evidence_pins',{});rpc.evidence_pins={}
                try:members=rpc.batch([('eth_getBlockByNumber',[hex(n),False])
                    for n in sorted(expected)],scope='pons_selective_v4')
                finally:rpc.evidence_pins=pins
                headers=dict(zip(sorted(expected),members))
                if len(headers)!=len(expected) or any(h.get('number')!=hex(n) or not h.get('hash') or
                        expected[n] is not None and h.get('hash')!=expected[n] for n,h in headers.items()):
                    raise BoundaryError('pons_current_shared_membership')
                tapes={r['token']:dict(swaps=[],provider_sessions=[]) for r in requests}
            else:
                tapes,headers=collect_v4_activities(endpoint,markets=[dict(pool_id=r['pool_id'],
                    key=r['key'],token=r['token'],preholder_groups=r['preholders']) for r in requests],
                    start_block=start,end_block=top,evidence_context=context,canonical_targets=expected,
                    return_headers=True,initial_calls=state_calls,initial_values=values)
            for r in requests:
                tape=dict(tapes[r['token']]);old=r['checkpoint']
                tape['swaps']=[e for e in tape['swaps'] if e['block']>old['block']]
                if any(e['event_at']<old['through'] for e in tape['swaps']):
                    raise BoundaryError('pons_current_shared_history_time_regression')
                # Physical purchase telemetry belongs to the acquisition owner,
                # not N logical consumers; it is never summed N times.
                tape['provider_sessions']=[]
                prepared[r['identity']]=dict(checkpoint=old,source_generation=r['source_generation'],
                    headers=headers,header=header,tape=tape)
            return headers,values
        quotes=shared_v4_quotes(rpc,requests,deadline_seconds=5,prepare_history=history,deadline_at=deadline)
        for r,q in zip(requests,quotes):
            prepared[r['identity']]['acquired']=q['acquired']
            q.update(position_hash=r['position_hash'],provider_fingerprint=r['provider_fingerprint'],
                source_generation=r['source_generation'],history=prepared[r['identity']],deadline=deadline)
        return dict(zip((r['identity'] for r in requests),quotes))
    return acquire()


class LifecyclePool:
    def __init__(self,*,max_workers=8,clock=None,wait_for_due=None):
        if not 1<=max_workers<=8:raise ValueError('current_physical_worker_limit')
        self.max_workers=max_workers;self.clock=clock or time.monotonic;self.lock=threading.Condition()
        self.wait_for_due=wait_for_due or (lambda seconds:self.lock.wait(min(.05,seconds)))
        self.workers=[dict(queue=[],owners=0,running=False) for _ in range(max_workers)]
        self.executor=ThreadPoolExecutor(max_workers=max_workers,thread_name_prefix='pons-current')
        self.entry_executor=ThreadPoolExecutor(max_workers=max_workers,thread_name_prefix='pons-current-entry')
        self.started=set();self.sequence=0;self.entries=0;self.closing=False
        self.counts=dict(owners=0,peak_owners=0,active_physical_workers=0,peak_physical_workers=0,
            protection_turns=0,late_protection_turns=0,max_queue_age_seconds=0.,
            active_entry_workers=0,peak_entry_workers=0,entry_owner_handoffs=0,
            shared_acquisitions=0,shared_consumers=0,shared_failures=0)

    def entry_capacity_available(self):
        with self.lock:
            # Sleeping held owners do not consume entry-processing tickets.
            # Due protective work is always dispatched before a queued entry.
            return not self.closing and self.entries<self.max_workers

    def submit(self,function,*args,**kwargs):
        from .pons_selective_paper import run_lifecycle,run_lifecycle_steps
        from .pons_selective_recovery import _resume_receipt,_resume_receipt_steps
        entry=function is run_lifecycle
        if entry:factory=run_lifecycle_steps
        elif function is _resume_receipt:factory=_resume_receipt_steps
        else:raise ValueError('current_native_controller_required')
        with self.lock:
            if self.closing:raise RuntimeError('current_workers_closed')
            if entry and self.entries>=self.max_workers:
                raise BoundaryError('current_entry_workers_temporarily_busy')
            index=min(range(self.max_workers),key=lambda i:(self.workers[i]['owners'],i))
            future=Future();self.sequence+=1
            owner=dict(future=future,factory=factory,args=args,kwargs=kwargs,iterator=None,
                context=None,entry=entry,started=False,sequence=self.sequence,due=self.clock(),pending_exit=False,prior=None)
            self.counts['owners']+=1
            self.counts['peak_owners']=max(self.counts['peak_owners'],self.counts['owners'])
            if entry:
                self.entries+=1
                self.entry_executor.submit(self._entry,owner)
                return future
            self.workers[index]['owners']+=1;self.entries+=int(entry)
            self._enqueue(index,owner)
            if index not in self.started:
                self.started.add(index);self.executor.submit(self._worker,index)
            self.lock.notify_all()
            return future

    def _entry(self,owner):
        """Entry probing never occupies a thread servicing a held position."""
        from .pons_selective_recovery import resume_lifecycle_steps
        transferred=False;value=None;error=None
        with self.lock:
            self.counts['active_entry_workers']+=1
            self.counts['peak_entry_workers']=max(self.counts['peak_entry_workers'],self.counts['active_entry_workers'])
        try:
            if self.closing:raise BoundaryError('current_entry_deferred_for_handoff')
            if not owner['future'].set_running_or_notify_cancel():return
            owner['started']=True;owner['context']=copy_context()
            owner['iterator']=owner['context'].run(owner['factory'],*owner['args'],**owner['kwargs'])
            wait=owner['context'].run(next,owner['iterator'])
            if wait.get('kind')!='monitor_wait' or wait.get('seconds')!=5:
                raise BoundaryError('current_native_monitor_schedule_changed')
            original_due=self.clock()+wait['seconds']
            session=wait['continued_session']
            # Finish/reconcile/close entry's SQLite objects on their original
            # thread before reopening the same durable native owner elsewhere.
            try:owner['context'].run(owner['iterator'].send,'handoff')
            except StopIteration as result:value=result.value
            else:raise BoundaryError('current_native_entry_handoff_incomplete')
            if (value.get('status')!='handoff_required'
                    or value.get('final_position',{}).get('id')!=session['position']):
                raise BoundaryError('current_native_entry_handoff_identity')
            owner.update(iterator=None,factory=resume_lifecycle_steps,args=(owner['args'][0],),
                kwargs=dict(db_path=owner['kwargs']['db_path'],capital_path=owner['kwargs'].get('capital_path'),
                    exceptional_context=owner['kwargs'].get('exceptional_context'),
                    _continued_session=session,_first_monitor_due=original_due),
                entry=False,prior=value,due=self.clock(),pending_exit=wait.get('pending_exit',False))
            with self.lock:
                index=min(range(self.max_workers),key=lambda i:(self.workers[i]['owners'],i))
                self.workers[index]['owners']+=1;self.counts['entry_owner_handoffs']+=1
                self._enqueue(index,owner)
                if index not in self.started:
                    self.started.add(index);self.executor.submit(self._worker,index)
                self.lock.notify_all();transferred=True
        except StopIteration as result:value=result.value
        except BaseException as exc:error=exc
        finally:
            if not transferred and owner['iterator'] is not None:
                try:owner['context'].run(owner['iterator'].close)
                except BaseException as exc:
                    if error is None:error=exc
            with self.lock:
                self.entries-=1;self.counts['active_entry_workers']-=1
                if not transferred:
                    self.counts['owners']-=1
                    if not owner['future'].cancelled():
                        if error is not None:owner['future'].set_exception(error)
                        else:owner['future'].set_result(value)
                self.lock.notify_all()

    def _enqueue(self,index,owner):
        heapq.heappush(self.workers[index]['queue'],
            (owner['due'],0 if owner['pending_exit'] else 1,owner['sequence'],owner))

    def _claim_acquisition(self,owner,now):
        """Called under the pool lock; never waits to form a cohort."""
        if owner.get('acquisition_future') is not None:return owner['acquisition_future'],None
        request=owner.get('acquisition_request')
        execution=bool(request and request.get('execution'))
        if request is None or owner['pending_exit'] and not execution:return None,None
        key=(request['provider_fingerprint'],request['source_generation'])
        selected=[owner]
        for worker in self.workers:
            for due,_,_,other in sorted(worker['queue'],key=lambda row:row[:3]):
                r=other.get('acquisition_request')
                if (due<=now and r is not None and bool(r.get('execution'))==execution
                        and (not other['pending_exit'] or execution)
                        and other.get('acquisition_future') is None
                        and (r['provider_fingerprint'],r['source_generation'])==key
                        and r['pool_id'] not in {x['acquisition_request']['pool_id'] for x in selected}):
                    selected.append(other)
                    if len(selected)==20:break
            if len(selected)==20:break
        future=Future()
        for other in selected:other['acquisition_future']=future
        self.counts['shared_acquisitions']+=int(len(selected)>1)
        self.counts['shared_consumers']+=len(selected) if len(selected)>1 else 0
        return future,selected

    def _worker(self,index):
        worker=self.workers[index]
        while True:
            with self.lock:
                while not worker['queue']:
                    # An in-flight entry may still need to hand its newly
                    # filled native owner back. Keep the existing protected
                    # worker alive until that durable handoff is complete.
                    if self.closing and self.entries==0:return
                    self.lock.wait(.05)
                due,_,_,owner=worker['queue'][0];now=self.clock()
                if not self.closing and due>now:
                    self.wait_for_due(due-now);continue
                # Among ready work, protection precedes entry; original release
                # times remain unchanged. Sequence breaks equal-deadline ties.
                ready=[]
                while worker['queue'] and (self.closing or worker['queue'][0][0]<=now):
                    ready.append(heapq.heappop(worker['queue']))
                chosen=min(range(len(ready)),key=lambda j:(ready[j][3]['entry'],
                    ready[j][0],ready[j][1],ready[j][2]))
                _,_,_,owner=ready.pop(chosen)
                for row in ready:heapq.heappush(worker['queue'],row)
                age=max(0.,now-owner['due'])
                self.counts['max_queue_age_seconds']=max(self.counts['max_queue_age_seconds'],age)
                if owner['iterator'] is not None and owner.get('wait_kind','monitor_wait')=='monitor_wait':
                    self.counts['protection_turns']+=int(not self.closing)
                    self.counts['late_protection_turns']+=int(not self.closing and age>1e-6)
                worker['running']=True;self.counts['active_physical_workers']+=1
                self.counts['peak_physical_workers']=max(self.counts['peak_physical_workers'],
                    self.counts['active_physical_workers'])
                acquisition,cohort=(None,None) if self.closing else self._claim_acquisition(owner,now)
            done=False;value=None;error=None
            try:
                if owner['iterator'] is None:
                    if not owner['started'] and not owner['future'].set_running_or_notify_cancel():done=True
                    else:
                        # ContextVar history/provider attribution is isolated
                        # between controllers sharing this physical thread.
                        owner['started']=True
                        if owner['context'] is None:owner['context']=copy_context()
                        owner['iterator']=owner['context'].run(owner['factory'],*owner['args'],**owner['kwargs'])
                        value=owner['context'].run(next,owner['iterator'])
                else:
                    command='handoff' if self.closing else None
                    if acquisition is not None:
                        if cohort is not None:
                            try:
                                acquire=(acquire_current_exits if owner['acquisition_request'].get('execution') else acquire_current_owners)
                                result=owner['context'].run(acquire,
                                    [x['acquisition_request'] for x in cohort],min(x['due'] for x in cohort)+5)
                                acquisition.set_result(result)
                            except Exception as exc:
                                acquisition.set_exception(exc)
                                with self.lock:self.counts['shared_failures']+=1
                        try:
                            remaining=max(0.,owner['due']+5-self.clock())
                            result=acquisition.result(timeout=remaining)
                            command=dict(acquisition=result[owner['acquisition_request']['identity']])
                        except Exception as exc:
                            command=dict(acquisition_failed=True,
                                boundary=str(exc) if isinstance(exc,BoundaryError) else 'provider_transport_failure')
                    value=owner['context'].run(owner['iterator'].send,command)
                if not done and (not isinstance(value,dict) or value.get('kind') not in ('monitor_wait','exit_wait')
                        or value['kind']=='monitor_wait' and value.get('seconds')!=5
                        or value['kind']=='exit_wait' and not 0<=value.get('seconds',-1)<=20):
                    raise BoundaryError('current_native_monitor_schedule_changed')
            except StopIteration as result:done=True;value=result.value
            except BaseException as exc:done=True;error=exc
            finally:
                if done and owner['iterator'] is not None:
                    try:owner['context'].run(owner['iterator'].close)
                    except BaseException as exc:
                        if error is None:error=exc
                with self.lock:
                    worker['running']=False;self.counts['active_physical_workers']-=1
                    if owner['entry']:
                        owner['entry']=False;self.entries-=1
                    if done:
                        worker['owners']-=1;self.counts['owners']-=1
                        if not owner['future'].cancelled():
                            if error is not None:owner['future'].set_exception(error)
                            else:
                                if owner['prior']:
                                    value=dict(owner['prior'],**value)
                                    value['qualification_vector']=owner['prior'].get('qualification_vector',value.get('qualification_vector'))
                                owner['future'].set_result(value)
                    else:
                        # The native controller's original wait begins after
                        # its previous turn, exactly as in the synchronous path.
                        owner['due']=value.get('due_at',self.clock()+value['seconds'])
                        owner['pending_exit']=bool(value.get('pending_exit'))
                        owner['acquisition_request']=value.get('acquisition_request')
                        owner['wait_kind']=value['kind']
                        owner['acquisition_future']=None
                        self._enqueue(index,owner)
                    self.lock.notify_all()

    def telemetry(self):
        with self.lock:return dict(self.counts,physical_worker_limit=self.max_workers,
            entry_worker_limit=self.max_workers,total_physical_worker_limit=2*self.max_workers,
            entry_tasks=self.entries,position_count_limit=None)

    def request_handoff(self):
        with self.lock:self.closing=True;self.lock.notify_all()

    def shutdown(self,wait=True,*,cancel_futures=False):
        self.request_handoff()
        self.entry_executor.shutdown(wait=True,cancel_futures=False)
        self.executor.shutdown(wait=wait,cancel_futures=False)

    def __enter__(self):return self
    def __exit__(self,*exc):self.shutdown()
