"""Native Current/Survivor observation and qualification, with no monetary authority."""
import time
from .certify import safe_reason

def completed_observation(row,finished):
    """A skipped/failed hydration is a disposition, never qualification readiness."""
    row['disposition_finished']=finished
    if row.get('full_hydration') and 'qualification' in row and not row.get('error'):
        row['qualification_ready']=finished
    return row

class PumpCandidates:
    def __init__(self,cert):
        from meme_machine.lanes.pump import runner
        from meme_machine.runtime.candidate_history import open_candidate_history
        from meme_machine.runtime.survivor_history import History
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime,POLICY_HASH
        self.cert=cert;self.plane=runner.RuntimeEvidence(owner='capacity:pump-candidate')
        self.tape=runner.LocalPumpTape(self.plane);self.confirmations=runner.ConfirmationBook.from_files()
        self.history=open_candidate_history();runner.CANDIDATE_HISTORY=self.history
        self.sequence=0;self.last_eval={};self.rows=[];self.errors=[]
        # Observation-only members of the actual Survivor runtime. Its constructor
        # opens capital/account books, which are deliberately never instantiated.
        self.survivor=Runtime.__new__(Runtime);self.survivor.history=History(str(cert.out/'survivor.sqlite'),policy=POLICY_HASH)
        self.survivor.confirmations=self.confirmations;self.survivor.plane=runner.RuntimeEvidence(owner='capacity:survivor-candidate')
        self.survivor.candidate_history=self.history;self.survivor.rpc=None;self.survivor.current=None
    def tick(self):
        from meme_machine.lanes.pump import runner
        from meme_machine.lanes.pump.pumpswap_survivor import POLICY as survivor_policy,evaluate_entry
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Quotes
        from meme_machine.runtime.candidate_history import economic_event_cursor
        now=int(time.time())
        try:fresh,self.sequence=self.tape.events_since(self.sequence)
        except Exception as exc:self.errors.append(dict(at=now,stage='history',reason=safe_reason(exc)));return
        for source in self.tape.candidate_history_rows:
            event=source['event']
            if event.get('event_type')=='create':self.confirmations.observe_creation(event)
            elif event.get('event_type')=='migration':self.confirmations.observe_graduation(event['mint'],event['available_time'])
        for event in fresh:
            mint=event['mint']
            if now-self.last_eval.get(mint,0)<5:continue
            creation=self.tape.creation(mint)
            if creation is None:continue
            self.last_eval[mint]=now;start=time.time();row=dict(candidate=mint,lane='pump',first_observed=creation['market_time'],
                evidence_available=event['available_time'],queue_entry=start,worker_claim=start,hydration_start=start,
                hydration_class='NO_RICH_HYDRATION_REQUIRED',full_hydration=False)
            token=self.cert.family_context.set('pump_hydration');before=len(self.cert.meter.rows)
            try:
                progress=runner.curve_progress_bps(creation['initial_real_token_reserves'],event['real_token_reserves'])
                if progress<runner.POLICY.min_curve_progress_bps or event['real_token_reserves']==0:continue
                events=[e for e in self.tape.window(mint,event['market_time'],max_slot=event['slot']) if economic_event_cursor(e)<=economic_event_cursor(event)]
                signal,trajectory,confirmation=runner._late_stream_signal(creation,events,event,self.confirmations)
                optimistic,reasons=runner._late_stream_prospect(signal);row['prospect_reasons']=reasons
                original=self.history.candidate('pump',mint)
                row['original_decision_deadline']=None if original is None else original['decision_deadline']
                if not reasons:
                    rpc,pacer=self.cert.native_rpc('pump',row['original_decision_deadline']);rpc.evidence_priority=3
                    snapshot=runner.PumpAdapter(rpc).snapshot(mint,now,True);row['hydration_class']='ACCOUNT_ONLY_HYDRATION';row['full_hydration']=True
                    events=self.tape.window(mint,snapshot['market_time'],max_slot=snapshot['slot'])
                    signal,_,_=runner._late_signal(creation,events,snapshot,0,self.confirmations);q=runner.qualify(signal)
                    if q.qualified:
                        concentration,_=runner.ConcentrationReader(rpc).read(mint,snapshot,priority=True)
                        signal,_,_=runner._late_signal(creation,events,snapshot,concentration,self.confirmations);q=runner.qualify(signal)
                    row['qualification']=dict(qualified=q.qualified,reasons=q.reasons)
                    self.history.record_decision('pump',mint,mode=runner.MODE_LATE_CURVE,observed_at=signal.observed_at,qualified=q.qualified,decision=row['qualification'])
            except Exception as exc:row.update(error=type(exc).__name__,reason=safe_reason(exc))
            finally:
                rows=[r for r in self.cert.meter.rows[before:] if r['family']=='pump_hydration'];finish=time.time()
                completed_observation(row,finish)
                row.update(seconds=finish-start,calls=sum(r['calls'] for r in rows),cu=sum(r['cu'] for r in rows),bytes=sum(r['bytes'] for r in rows),bodies=sum(r['transaction_bodies'] for r in rows),blocks=sum(r['blocks'] for r in rows))
                if row.get('original_decision_deadline') is not None:row['deadline_margin']=row['original_decision_deadline']-finish
                self.rows.append(row);self.cert.family_context.reset(token)
        # The actual incremental, non-lossy Survivor path retains all graduations;
        # its existing minimum age controls hydration, never Current rejection.
        try:
            self.survivor.discover()
            rows=self.survivor.history.rows()
            if not rows:return
            candidate=min(rows,key=lambda r:(r.get('last_checked',0),r['graduation']['at'],r['id']))
            candidate['last_checked']=now;self.survivor.history.save(candidate)
            age=now-candidate['graduation']['at'];start=time.time();token=self.cert.family_context.set('pumpswap_hydration');before=len(self.cert.meter.rows)
            row=dict(candidate=candidate['id'],lane='pumpswap',first_observed=candidate['graduation']['at'],queue_entry=start,worker_claim=start,
                original_decision_deadline=candidate['graduation']['at']+survivor_policy['maximum_age_seconds'],hydration_class='NO_RICH_HYDRATION_REQUIRED',full_hydration=False)
            try:
                top=self.survivor.plane.frontier(runner.SWAP_SCOPE);at=self.survivor.plane.block_time(top)
                self.survivor._increment(candidate,at,top)
                if survivor_policy['minimum_age_seconds']<=age<=survivor_policy['maximum_age_seconds']:
                    state=self.survivor.fresh_state(candidate['id'],priority=3)
                    decision=evaluate_entry(self.survivor.reconstruct(state,Quotes(state,now)));row.update(qualification=decision,hydration_class='ACCOUNT_ONLY_HYDRATION',full_hydration=True)
                    self.history.record_decision('pump',candidate['id'],mode='survivor',observed_at=state['market_time'],qualified=decision['candidate'],decision=decision)
            except Exception as exc:row.update(error=type(exc).__name__,reason=safe_reason(exc))
            finally:
                finished=time.time();requests=[r for r in self.cert.meter.rows[before:] if r['family']=='pumpswap_hydration'];completed_observation(row,finished);row.update(seconds=finished-start,calls=sum(r['calls'] for r in requests),cu=sum(r['cu'] for r in requests),bytes=sum(r['bytes'] for r in requests),bodies=sum(r['transaction_bodies'] for r in requests),blocks=sum(r['blocks'] for r in requests));self.rows.append(row);self.cert.family_context.reset(token)
        except Exception as exc:self.errors.append(dict(at=now,stage='survivor',reason=safe_reason(exc)))
    def close(self):
        self.plane.close();self.survivor.plane.close();self.survivor.history.close();self.history.close()
