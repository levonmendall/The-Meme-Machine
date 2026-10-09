"""Pons-specific projection onto the shared candidate registry.

Public logs nominate/update work. Receipt/header-authenticated normalized events
alone populate rolling strategy inputs. No public value supplies a canonical field.
"""
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import time
from .plane import Plane, canonical, digest, plane_path


def interpretation(policy):
    from meme_machine.lanes.pons import CHAIN_ID
    from meme_machine.lanes.pons.identity import load
    from meme_machine.lanes.pons.pons import TEMPLATE
    return dict(schema=1,chain=CHAIN_ID,policy=policy,
        factory=load('pons_v2_factory')['address'].lower(),
        factory_runtime=load('pons_v2_factory')['runtime_sha256'],
        deployer_source=load('pons_deployer')['compiler_input_sha256'],
        adapter_source=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        curve_template=hashlib.sha256(TEMPLATE.read_bytes()).hexdigest())


class Broker:
    def __init__(self,path,policy,*,on_terminal=None,clock=time.time,source=None,config=None):
        self.plane=Plane(path,clock=clock);self.clock=clock
        self.policy=interpretation(policy);self.on_terminal=on_terminal
        self.policy.update(source=digest(source or "authenticated_alchemy"),config=config)
        from meme_machine.lanes.pons.provider_admission import fingerprint
        self.provider_endpoint=fingerprint(source) if source else None
        self.nominal_deadline_seconds=5.;self.limit=None
        with self.plane.lock:
            self.plane.db.execute('''CREATE TABLE IF NOT EXISTS pons_current_watch(
                candidate TEXT PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL,
                next_at REAL NOT NULL,attempt INTEGER NOT NULL DEFAULT 0)''')
        # Repair the projection after a crash between raw observation and watch
        # insertion. Retained buys are sufficient; no provider or new clock is
        # needed to restore the original nomination and observation time.
        from meme_machine.lanes.pons.abi import topic
        from meme_machine.lanes.pons.pons_selective_continuation import ENTRY_THRESHOLDS
        buy=topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)')
        with self.plane.transaction():
            for row in self.plane.db.execute("SELECT * FROM candidates WHERE lane='pons'").fetchall():
                event=json.loads(row['payload'])
                old=self.plane.db.execute('SELECT body FROM pons_current_watch WHERE candidate=?',(row['id'],)).fetchone()
                if old and row['interpretation']==canonical(self.policy):
                    self._sync_watch_order(row['id'],dict(row))
                if row['reason']=='strategy_horizon_expired':continue
                retained=json.loads(row['result']) if row['result'] else {}
                stamp=retained.get('candidate',{}).get('stamp') or {}
                if (retained.get('candidate',{}).get('state',{}).get('graduated') or
                        retained.get('launch_at') is not None and stamp.get('event_at',0)>
                        retained['launch_at']+ENTRY_THRESHOLDS['max_token_age_seconds']):continue
                if (row['pending'] or (event.get('topics') or [None])[0]==buy) and row['interpretation']==canonical(self.policy):
                    if not self.plane.db.execute('SELECT 1 FROM pons_current_watch WHERE candidate=?',(row['id'],)).fetchone():
                        self._remember_watch(row['id'],event,row['observed'],row['generation'])

    @staticmethod
    def observation_id(event):
        return event['transactionHash']+':'+event['logIndex']+':'+digest(event)

    def identity(self,event):
        return 'pons:'+str(self.policy['chain'])+':'+self.policy['factory']+':'+event['address'].lower()

    def _remember_watch(self,key,event,observed,generation):
        old=self.plane.db.execute('SELECT body,hash FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()
        if old and digest(json.loads(old[0]))!=old[1]:raise ValueError('pons_current_watch_corruption')
        first=(json.loads(old[0])['first_observed_at'] if old else
            self.plane.db.execute('SELECT MIN(at) FROM observations WHERE candidate=?',(key,)).fetchone()[0])
        watch=dict(event=event,first_observed_at=observed if first is None else first,
            last_buy_observed_at=observed,interpretation=self.policy,generation=generation)
        row=self.plane._row(key)
        watch.update(latest_ordering=json.loads(row['ordering']),latest_id=row['latest_id'])
        self.plane.db.execute('''INSERT INTO pons_current_watch VALUES(?,?,?,?,0)
            ON CONFLICT(candidate) DO UPDATE SET body=excluded.body,hash=excluded.hash,next_at=excluded.next_at''',
            (key,canonical(watch),digest(watch),observed+self.nominal_deadline_seconds))

    def _sync_watch_order(self,key,row):
        old=self.plane.db.execute('SELECT body,hash FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()
        if old:
            watch=json.loads(old[0])
            if digest(watch)!=old[1]:raise ValueError('pons_current_watch_corruption')
            watch.update(generation=row['generation'],latest_ordering=json.loads(row['ordering']),latest_id=row['latest_id'])
            self.plane.db.execute('UPDATE pons_current_watch SET body=?,hash=? WHERE candidate=?',
                (canonical(watch),digest(watch),key))

    def enqueue(self,event,*,now=None,needs_work=True,canonical_refresh=False):
        # Live and startup workers share this broker. Serialize nomination,
        # watch and cold-refresh projection without changing shared Plane code.
        with self.plane.lock:
            return self._enqueue(event,now=now,needs_work=needs_work,canonical_refresh=canonical_refresh)

    def _enqueue(self,event,*,now=None,needs_work=True,canonical_refresh=False):
        from meme_machine.lanes.pons.pons_selective_continuation import ENTRY_THRESHOLDS
        observed=self.clock() if now is None else now
        key=self.identity(event)
        previous=self.plane.get(key)
        priority=2 if previous and previous['priority']<=2 else 4
        # Public variants are nominations, never an immutable authority conflict.
        # Bind their full raw body/hash; canonical receipt authentication still
        # decides which (if any) is valid. A bad nomination cannot tombstone a
        # curve and suppress every later independently authenticated generation.
        obs=self.observation_id(event)
        order=tuple(int(event[k],16) for k in ('blockNumber','transactionIndex','logIndex'))
        if previous and previous['reason']=='conflicting_observation':
            with self.plane.transaction():
                old=self.plane._row(key)
                if old['reason']=='conflicting_observation':
                    self.plane._audit(old,'watching','pons_public_conflict_requires_fresh_canonical_evidence')
                    self.plane.db.execute("UPDATE candidates SET reason='pons_public_conflict_awaiting_canonical' WHERE id=?",(key,))
        result=self.plane.observe(key,'pons',obs,event,ordering=order,
            watermark=dict(block=order[0],hash=event['blockHash'],log=order[2],finality='confirmed'),
            interpretation=self.policy,observed=observed,
            deadline=observed+ENTRY_THRESHOLDS['max_state_age_seconds'],priority=priority,needs_work=needs_work)
        if needs_work and result in ('created','updated'):
            with self.plane.transaction():
                self._remember_watch(key,event,observed,self.plane.get(key)['generation'])
                if canonical_refresh:
                    watch=json.loads(self.plane.db.execute('SELECT body FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()[0])
                    target=dict(kind='pons_canonical_current_recheck',source='cold_start_nomination',
                        original_nomination=event,first_observed_at=watch['first_observed_at'])
                    self.plane.db.execute('UPDATE candidates SET desired=? WHERE id=?',(canonical(target),key))
                    self.plane._audit(self.plane._row(key),'watching','pons_cold_start_requires_fresh_canonical_state')
        elif result in ('created','updated'):
            with self.plane.transaction():self._sync_watch_order(key,self.plane._row(key))
        return result in ('created','updated')

    @property
    def rows(self):
        with self.plane.lock:
            rows=self.plane.db.execute("SELECT * FROM candidates WHERE lane='pons' AND pending=1").fetchall()
        return {r['id']:self._scheduled(dict(r)) for r in rows}

    def _scheduled(self,r):
        refresh=json.loads(r['desired']).get('kind')=='pons_canonical_current_recheck'
        return dict(key=r['id'],event=json.loads(r['payload']),queued_at=r['observed'],deadline=r['deadline'],work=r,
            canonical_refresh=refresh)

    def reactivate_one(self):
        """A timer requests new canonical state; it never renews old evidence.

        Raw ordering stays at the last real event so a later buy can supersede
        the probe. Original nominee/timing stay durable. One fair bounded probe
        also breaks a stale service-estimate deadlock; actual admission and the
        new observation's original five-second deadline still fail closed.
        """
        now=self.clock();deadline=now+self.nominal_deadline_seconds
        with self.plane.transaction():
            rows=self.plane.db.execute('''SELECT w.*,c.generation,c.state,c.pending,c.claim,c.result
                FROM pons_current_watch w LEFT JOIN candidates c ON c.id=w.candidate
                WHERE w.next_at<=? AND (c.id IS NULL OR c.pending=0 AND c.claim IS NULL
                    AND c.state NOT IN ('entry_confirmation','entry_reserved'))
                AND NOT EXISTS (SELECT 1 FROM runtime n WHERE n.key LIKE 'native_position:pons:%'
                    AND json_extract(n.body,'$.candidate')=w.candidate
                    AND json_extract(n.body,'$.position.status')<>'settled')
                ORDER BY w.attempt,w.next_at,w.candidate''',(now,)).fetchall()
            for row in rows:
                if row['result'] is not None and not self.plane.db.execute(
                        'SELECT 1 FROM result_consumption WHERE candidate=? AND generation=?',
                        (row['candidate'],row['generation'])).fetchone():continue
                watch=json.loads(row['body'])
                if digest(watch)!=row['hash']:raise ValueError('pons_current_watch_corruption')
                if watch['interpretation']!=self.policy:raise ValueError('pons_current_watch_interpretation_changed')
                if row['generation'] is None:
                    event=watch['event'];order=watch['latest_ordering']
                    self.plane.db.execute('''INSERT INTO candidates(id,lane,generation,interpretation,latest_id,
                        observed,ordering,desired,payload,state,pending,priority,rank,deadline,queued)
                        VALUES(?,'pons',?,?,?,?,?,?,?,'watching',0,4,0,?,?)''',
                        (row['candidate'],watch['generation'],canonical(self.policy),watch['latest_id'],
                        now,canonical(order),canonical({}),canonical(event),deadline,now))
                sequence=(self.plane.checkpoint_read('pons_current_recheck_sequence') or 0)+1
                self.plane.db.execute('INSERT INTO runtime VALUES(?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body',
                    ('pons_current_recheck_sequence',canonical(sequence)))
                target=dict(kind='pons_canonical_current_recheck',sequence=sequence,
                    original_nomination=watch['event'],first_observed_at=watch['first_observed_at'])
                self.plane.db.execute('''UPDATE candidates SET generation=generation+1,desired=?,payload=?,observed=?,
                    deadline=?,queued=?,state='watching',reason=NULL,pending=1,result=NULL,priority=MAX(2,priority) WHERE id=?''',
                    (canonical(target),canonical(watch['event']),now,deadline,now,row['candidate']))
                watch['generation']=self.plane.get(row['candidate'])['generation']
                self.plane.db.execute('UPDATE pons_current_watch SET next_at=?,attempt=?,body=?,hash=? WHERE candidate=?',
                    (deadline,sequence,canonical(watch),digest(watch),row['candidate']))
                self.plane._audit(self.plane._row(row['candidate']),'watching',
                    'pons_timer_requires_fresh_canonical_current_state',first_observed_at=watch['first_observed_at'])
                return row['candidate']
        return None

    def release_entry_guard(self,curve):
        key='pons:'+str(self.policy['chain'])+':'+self.policy['factory']+':'+curve.lower()
        with self.plane.transaction():
            row=self.plane._row(key)
            live=self.plane.db.execute("SELECT 1 FROM runtime WHERE key LIKE 'native_position:pons:%' "
                "AND json_extract(body,'$.candidate')=? AND json_extract(body,'$.position.status')<>'settled'",(key,)).fetchone()
            if live:return
            if row and row['state'] in ('entry_confirmation','entry_reserved') and not row['pending'] and row['claim'] is None:
                self.plane.db.execute("UPDATE candidates SET state='watching' WHERE id=?",(key,))
                self.plane._audit(self.plane._row(key),'watching','pons_native_attempt_complete_recheck_preserved')

    def defer_execution_worker(self,key,generation,*,worker_limit):
        """Retain the native watch when physical lifecycle workers are busy.

        This disposition grants no entry, resets no clock and creates no terminal
        lifecycle. The existing timer/new-event path must reacquire canonical
        qualification before a later worker can execute it.
        """
        with self.plane.transaction():
            row=self.plane._row(key)
            watch=self.plane.db.execute('SELECT body,hash FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()
            if not row or row['generation']!=generation or row['completed']!=row['desired']:
                return False
            if not watch or digest(json.loads(watch[0]))!=watch[1]:
                raise ValueError('pons_current_watch_corruption')
            self.plane.db.execute("UPDATE candidates SET state='worker_deferred',reason='physical_lifecycle_workers_busy' WHERE id=?",(key,))
            self.plane._audit(row,'worker_deferred','physical_lifecycle_workers_busy',
                worker_limit=worker_limit,original_observed_at=row['observed'],
                original_deadline=row['deadline'],requires_fresh_canonical_qualification=True)
            return True

    def release_orphan_entry_guards(self,active_curves):
        """After native restart reconciliation, a pre-submit crash owns no entry.

        Live native reservations/controllers and unconsumed decisions remain
        protected. A released guard grants only a fresh canonical probe.
        """
        with self.plane.lock:
            keys=[r[0] for r in self.plane.db.execute("SELECT id FROM candidates WHERE lane='pons' AND state IN ('entry_confirmation','entry_reserved')")]
        active={c.lower() for c in active_curves}
        for key in keys:
            curve=key.rsplit(':',1)[-1]
            if curve not in active:self.release_entry_guard(curve)

    def pop(self,*,now=None,minimum_remaining_seconds=0):
        estimate=self.plane.estimate('pons',provider_interval=.5)
        # Provider admission is authoritative. Read its local outstanding work;
        # no RPC or new ceiling is introduced by this estimate.
        provider=os.environ.get('MM_PROVIDER_DB')
        if not provider and os.environ.get('MM_ROBINHOOD_READ_RPC_URL'):
            from .provider_authority import paths
            provider=str(paths()['provider'])
        if provider and self.provider_endpoint and Path(provider).exists():
            import sqlite3
            db=sqlite3.connect('file:'+provider+'?mode=ro',uri=True)
            try:
                n=db.execute('SELECT COUNT(*) FROM queue WHERE deadline>? AND endpoint=?',(time.monotonic(),self.provider_endpoint)).fetchone()[0]
                row=db.execute('SELECT interval,cooldown FROM limits WHERE endpoint=?',(self.provider_endpoint,)).fetchone()
                if row and row[0] is not None:
                    estimate=self.plane.estimate('pons',provider_interval=row[0],queued_transports=n,cooldown_seconds=max(0,(row[1] or 0)-time.monotonic()))
            finally:db.close()
        # Alternate eligible raw nominations with retained quiet-market probes.
        # Continuous new buys cannot indefinitely starve a recoverable identity.
        probe_turn=self.plane.checkpoint_read('pons_current_probe_turn') is not False
        work=None
        if probe_turn:
            key=self.reactivate_one()
            if key is not None:work=self.plane.claim(lane='pons',key=key,estimate_seconds=.5)
        if work is None:work=self.plane.claim(lane='pons',estimate_seconds=estimate)
        if work is None:
            key=self.reactivate_one()
            if key is not None:work=self.plane.claim(lane='pons',key=key,estimate_seconds=.5)
        if work is not None:
            self.plane.checkpoint('pons_current_probe_turn',
                json.loads(work['desired']).get('kind')!='pons_canonical_current_recheck')
        return self._scheduled(work) if work else None

    def finish(self,scheduled,evaluation,elapsed,*,logical=None,physical=None):
        from dataclasses import asdict, is_dataclass
        # Retain the full authenticated candidate, including receipt/header and
        # typed-state fields needed by the frozen paper lifecycle after restart.
        value=json.loads(json.dumps(evaluation,default=lambda x:asdict(x) if is_dataclass(x) else (_ for _ in ()).throw(TypeError(type(x).__name__))))
        finished=self.plane.finish(scheduled['work'],result=value,seconds=elapsed,logical=logical,physical=physical)
        if finished:
            from meme_machine.lanes.pons.pons_selective_continuation import ENTRY_THRESHOLDS
            stamp=value.get('candidate',{}).get('stamp') or {}
            with self.plane.transaction():
                row=self.plane._row(scheduled['key'])
                if row['generation']!=scheduled['work']['generation']:return finished
                if (value.get('candidate',{}).get('state',{}).get('graduated') or
                        value.get('launch_at') is not None and stamp.get('event_at',0)>
                        value['launch_at']+ENTRY_THRESHOLDS['max_token_age_seconds']):
                    self.plane.db.execute('DELETE FROM pons_current_watch WHERE candidate=?',(scheduled['key'],))
                else:
                    old=self.plane.db.execute('SELECT body FROM pons_current_watch WHERE candidate=?',(scheduled['key'],)).fetchone()
                    if old:
                        watch=json.loads(old[0]);watch['failures']=0
                        candidate=value.get('candidate',{})
                        nomination=candidate.get('nomination_header') or candidate.get('header') or {}
                        buy_at=int(nomination['timestamp'],16) if nomination.get('timestamp') else None
                        age=(value.get('vector') or {}).get('token_age_seconds')
                        delay=self.nominal_deadline_seconds
                        if age is not None and age<ENTRY_THRESHOLDS['min_token_age_seconds']:
                            delay=min(delay,ENTRY_THRESHOLDS['min_token_age_seconds']-age)
                        # Once authenticated buying is outside the positive 15s
                        # demand window, only another real buy can restore it.
                        # Keep the identity/history but cease quiet RPC probes.
                        next_at=(1e100 if buy_at is not None and stamp.get('event_at',0)>buy_at+15
                            else self.clock()+delay)
                        self.plane.db.execute('UPDATE pons_current_watch SET body=?,hash=?,next_at=? WHERE candidate=?',
                            (canonical(watch),digest(watch),next_at,scheduled['key']))
        return finished

    def committed(self):
        from meme_machine.lanes.pons.pons import CurveState
        from meme_machine.lanes.pons.evidence import Stamp
        for row in self.plane.unconsumed('pons'):
            value=json.loads(row['result'])
            candidate=value['candidate']
            candidate['state']=CurveState(**candidate['state'])
            if 'stamp' in candidate:candidate['stamp']=Stamp(**candidate['stamp'])
            yield self._scheduled(row),value

    def acknowledge(self,scheduled):
        return self.plane.consume(scheduled['key'],scheduled['work']['generation'])

    def failure(self,scheduled,reason,*,screen=None,evidence=None):
        from meme_machine.lanes.pons.pons_selective_continuation import ENTRY_THRESHOLDS
        state=('superseded' if reason=='candidate_generation_superseded' else
               'freshness_deadline_censored' if any(x in reason for x in ('stale','deadline')) else
               'provider_capacity_defer' if any(x in reason for x in ('429','capacity','budget')) else
               'transient_defer' if any(x in reason for x in ('transport_failure','http_50')) else 'authoritative_evidence_failure')
        if screen is not None:
            from .accounting import screen_outcome
            state=screen_outcome(screen)
        horizon=(reason=='strategy_horizon_expired' and scheduled['canonical_refresh'] and evidence
            and evidence.get('boundary')==reason and evidence.get('authentication_complete') is True
            and evidence.get('identity') and evidence['asof']>evidence['launch_at']+ENTRY_THRESHOLDS['max_token_age_seconds'])
        if horizon:state='strategy_rejected'
        finished=self.plane.finish(scheduled['work'],state=state,reason=reason,
            accounting_details={'authenticated_evidence':evidence} if horizon else
                {'authenticated_evidence':screen['authenticated_evidence']} if screen else None)
        if horizon:
            with self.plane.transaction():
                row=self.plane._row(scheduled['key'])
                if row['generation']==scheduled['work']['generation'] and row['reason']==reason:
                    self.plane.db.execute('DELETE FROM pons_current_watch WHERE candidate=?',(scheduled['key'],))
        else:
            with self.plane.transaction():
                row=self.plane._row(scheduled['key'])
                old=self.plane.db.execute('SELECT body FROM pons_current_watch WHERE candidate=?',(scheduled['key'],)).fetchone()
                if old and row['generation']==scheduled['work']['generation'] and row['reason']==reason:
                    watch=json.loads(old[0]);watch['failures']=watch.get('failures',0)+1
                    delay=min(60,self.nominal_deadline_seconds*2**min(4,watch['failures']-1))
                    # A complete canonical empty census cannot pass demand;
                    # await a real event rather than repeatedly buying absence.
                    next_at=1e100 if reason=='pons_current_recheck_no_recent_canonical_buy' else self.clock()+delay
                    self.plane.db.execute('UPDATE pons_current_watch SET body=?,hash=?,next_at=? WHERE candidate=?',
                        (canonical(watch),digest(watch),next_at,scheduled['key']))
        return finished

    def report_to(self,pipeline,*,drain=False):
        from .accounting import project,high_water
        through=high_water(self.plane)
        while project(self.plane,pipeline,through=through)==256:
            if not drain:break
        self.plane.maintain()

    def telemetry(self):return self.plane.snapshot('pons')

    def close(self):self.plane.close()


def shared_evidence_domain(endpoint):
    """Provider and interpretation generation; independent of strategy cursors."""
    from meme_machine.lanes.pons.provider_admission import fingerprint
    return 'pons:shared:'+fingerprint(endpoint)+':'+digest(interpretation(None))


def durable_cache(plane,domain):
    from meme_machine.lanes.pons.pons_selective_acquisition import ImmutableEvidenceCache
    class Cache(ImmutableEvidenceCache):
        def __init__(self):super().__init__();self.plane=plane;self.domain=domain;self.receipt_scope=None
        def _optional(self,function,*args):
            if not domain.startswith('pons:shared:'):return function(*args)
            # Optional retention never waits behind another consumer or writer.
            # Native history/position commits retain their original durability.
            if not plane.lock.acquire(blocking=False):
                self.counts['durable_busy_fallback']+=1;return None
            previous=None
            try:
                if plane.db.in_transaction:
                    self.counts['durable_busy_fallback']+=1;return None
                previous=plane.db.execute('PRAGMA busy_timeout').fetchone()[0]
                plane.db.execute('PRAGMA busy_timeout=0')
                return function(*args)
            except sqlite3.OperationalError as exc:
                code=getattr(exc,'sqlite_errorcode',0)&255
                if code not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):raise
                self.counts['durable_busy_fallback']+=1;return None
            finally:
                if previous is not None:plane.db.execute('PRAGMA busy_timeout='+str(previous))
                plane.lock.release()
        def _load(self,kind,key):
            row=self._optional(plane.evidence,domain+':'+kind,canonical(key))
            return row[0] if row else None
        def _save(self,kind,key,value):
            proof=dict(authority='authenticated_alchemy',schema=1,finality='confirmed')
            if kind=='receipt' and domain.startswith('pons:shared:'):
                retained=self._optional(plane.put_receipt,domain+':receipt',canonical(key),value,proof,self.receipt_scope)
                self.counts['durable_receipt_retained' if retained else 'durable_receipt_admission_fallback']+=1
            else:self._optional(plane.put,domain+':'+kind,canonical(key),value,proof)
        def begin_receipts(self,consumer,owner,generation):
            self._optional(plane.receipt_scope,domain+':receipt',consumer,owner,generation)
            self.receipt_scope=(consumer,owner,generation)
        def acknowledge_receipts(self):
            if self.receipt_scope:
                self._optional(lambda:plane.receipt_scope(domain+':receipt',*self.receipt_scope,acknowledge=True))
                self.receipt_scope=None
        def immutable_curve(self,curve,block):
            row=self._load('compiled_create2_curve',curve.lower())
            return row if row and int(block)>=row['origin_block'] else None
        def numeric_tip(self):
            with plane.lock:
                row=plane.db.execute('SELECT body FROM evidence WHERE namespace=? ORDER BY length(key) DESC,key DESC LIMIT 1',
                    (domain+':header_number',)).fetchone()
            durable=json.loads(row[0]) if row else None
            memory=super().numeric_tip()
            return max((h for h in (memory,durable) if h),key=lambda h:int(h['number'],16),default=None)
        def invalidate_canonical_aliases(self):
            super().invalidate_canonical_aliases()
            self.receipt_scope=None
            with plane.transaction():
                kinds=('header_number','launch','real_quote','compiled_create2_curve')
                plane.db.executemany('DELETE FROM evidence WHERE namespace=?',((domain+':'+kind,) for kind in kinds))
                plane.db.execute('DELETE FROM receipt_obligations WHERE namespace=?',(domain+':receipt',))
                plane._immutable.clear();plane._immutable_bytes=0
        def remember_compiled(self,curve,token,code,block,header,auth):
            # Verified CREATE2 deployer + exact non-proxy runtime; token() is
            # initialized once. Current factory record remains a fresh read.
            value=dict(curve=curve.lower(),token=token.lower(),code=code,
                origin_block=int(block),origin_hash=header['hash'],
                runtime_sha256=auth['runtime_sha256'],interpretation=interpretation(None))
            old=self._load('compiled_create2_curve',curve.lower())
            if old:
                if any(old[k]!=value[k] for k in ('curve','token','code','runtime_sha256','interpretation')):
                    raise ValueError('immutable_curve_conflict')
                return
            self._save('compiled_create2_curve',curve.lower(),value)
        def header_by_hash(self,key):
            return super().header_by_hash(key) or self._load('header_hash',key)
        def header_by_number(self,key):
            # Number mappings retain the original conflict-fail-closed behavior.
            value=super().header_by_number(key) or self._load('header_number',int(key))
            if value:super().remember_header(value)
            return value
        def remember_header(self,value):
            super().remember_header(value)
            self._save('header_hash',value['hash'],value)
            self._save('header_number',int(value['number'],16),value)
            return value
        def receipt(self,tx,bh):
            memory=super().receipt(tx,bh)
            value=memory or self._load('receipt',[tx,bh])
            if value is not None:
                self.counts['durable_receipt_hit' if memory is None else 'memory_receipt_hit']+=1
                if self.receipt_scope:self._save('receipt',[tx,bh],value)
            return value
        def remember_receipt(self,tx,bh,value):
            super().remember_receipt(tx,bh,value);self._save('receipt',[tx,bh],value);return value
        def launch(self,curve):
            value=super().launch(curve)
            return self._load('launch',curve.lower()) if value is None else value
        def remember_launch(self,curve,value):
            super().remember_launch(curve,value);self._save('launch',curve.lower(),value);return value
        def real_quote_at(self,curve,block):
            value=super().real_quote_at(curve,block)
            return self._load('real_quote',[curve.lower(),block]) if value is None else value
        def remember_real_quote(self,curve,block,value):
            super().remember_real_quote(curve,block,value);self._save('real_quote',[curve.lower(),block],value);return value
    return Cache()


def normalized_cached(ctx,event,build):
    cache=ctx.cache
    if not hasattr(cache,'plane'):return build()
    # Full raw identity is covered, not just transaction/log. Conflict is fatal.
    proof=dict(authority='authenticated_receipt_header',raw_digest=digest(event),
        block_hash=event['blockHash'],schema=1,finality='confirmed',domain=cache.domain)
    key=cache.domain+':'+event['address'].lower()
    identity=event['transactionHash']+':'+event['logIndex']
    row=cache.plane.rolling_get(key,identity,proof)
    if row is not None:return row
    row=build()
    from meme_machine.lanes.pons.pons_selective_continuation import ENTRY_THRESHOLDS
    cache.plane.rolling_put(key,identity,row['event_at'],int(event['blockNumber'],16),row,proof,limit=ENTRY_THRESHOLDS['max_market_events'])
    return row


def save_cohort_checkpoint(result,cursor,phase):
    path=result.get('candidate_plane_path')
    if not path:return
    from .plane import process_identity
    plane=Plane(path)
    try:
        # Recovery authority is this atomic SQLite checkpoint. Old observer
        # JSONL is a bounded projection and cannot suppress fresh evaluation.
        rows=result.get('rows',[])
        if len(rows)>4096:
            drop=rows[:-4096];fold=result.setdefault('archived_observations',{})
            fold['count']=fold.get('count',0)+len(drop)
            reasons=fold.setdefault('rejections',{})
            for row in drop:
                for reason in (row.get('vector') or {}).get('all_rejections') or []:reasons[reason]=reasons.get(reason,0)+1
            result['rows']=rows[-4096:]
            result['autonomous_observation_offset']=max(0,result.get('autonomous_observation_offset',0)-len(drop))
        for kind in ('discovery_sessions','sequencer_recoveries'):
            result[kind]=result.get(kind,[])[-64:]
        result.pop('native_archive_paths',None)
        plane.checkpoint('pons_cohort',dict(result=result,cursor=cursor,phase=phase,
            owner=process_identity(),checkpoint_at=time.time()))
    finally:plane.close()


def coalesce_lifecycle_rows(rows):
    """Retain append-only recovery receipts without counting a lifecycle twice."""
    from meme_machine.lanes.pons import BoundaryError
    result=[];indices={}
    for row in rows:
        index=row.get('index')
        if index is None or index not in indices:
            if index is not None:indices[index]=len(result)
            result.append(row);continue
        previous=result[indices[index]]
        position=row.get('final_position') or {}
        if (row.get('recovery_replaces_index')!=index or row.get('entry_authority') is not False
                or not row.get('lifecycle_id') or position.get('id')!=row['lifecycle_id']
                or (previous.get('lifecycle_id') and previous['lifecycle_id']!=row['lifecycle_id'])
                or (previous.get('curve') and previous['curve']!=row.get('curve'))
                or (previous.get('status') in ('settled','entry_failed')
                    and previous.get('final_position')!=position)):
            raise BoundaryError('selective_recovery_lifecycle_identity')
        result[indices[index]]=row
    return result


def recover_cohort(path,policy):
    from .plane import alive
    from meme_machine.lanes.pons import BoundaryError
    if not Path(path).is_file():raise BoundaryError('selective_existing_run_requires_explicit_recovery')
    plane=Plane(path)
    try:
        saved=plane.checkpoint_read('pons_cohort')
        if not saved or saved['result'].get('policy_hash')!=policy:
            raise BoundaryError('selective_existing_run_requires_explicit_recovery')
        rollover=saved['phase']=='finalizing'
        if alive(saved['owner']):raise BoundaryError('selective_cohort_owner_still_alive')
        result=saved['result']
        from meme_machine.runtime.pons_terminal_archive import controller_anchor
        controller_anchor(result)
        if rollover:
            result['started_at']=time.time()
            result.pop('ended_at',None);result.pop('summary',None)
            # The same native trial/qualifier history and sleeve continue, but
            # this verified successor has its own unchanged observation budget.
            result['autonomous_observation_offset']=len(result.get('rows',[]))
        return result
    finally:plane.close()


def restore_position_needs(path,capital_path):
    """Restore safety needs from native authority before any fresh admission.

    This does not recreate a paper controller from incomplete process memory.
    A reserved native position keeps the existing fail-closed recovery boundary.
    """
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect('file:'+str(Path(capital_path).resolve())+'?mode=ro',uri=True)) as db:
        plane=Plane(path)
        try:
            rows=[json.loads(r[0]) for r in db.execute('SELECT body FROM capital_positions')]
            for row in rows:
                if row['status']=='settled':continue
                position=row.get('native_position') or {}
                plane.checkpoint('position_safety:'+row['id'],dict(priority=0,lane='pons',
                    position_id=row['id'],native_version=position.get('version'),
                    trial_path=row['trial_path'],policy=row['policy_hash'],
                    authority='native_paper_ledger_replay_required',
                    state='open_position_recovery_required',reservation=row))
            return sum(row['status']!='settled' for row in rows)
        finally:plane.close()


def provider_totals(context):
    telemetry=context.telemetry()
    sessions=list(telemetry.get('completed_sessions',[]))
    if telemetry.get('current_session'):sessions.append(telemetry['current_session'])
    if not sessions:return (0,0)
    if any('logical_requests' not in r or 'transport_requests' not in r for r in sessions):return (None,None)
    logical=sum(r['logical_requests'] for r in sessions)
    physical=sum(r['physical_http_requests'] for r in sessions) if all('physical_http_requests' in r for r in sessions) else None
    return logical,physical
