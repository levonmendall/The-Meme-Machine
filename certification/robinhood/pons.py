"""Pons-specific projection onto the shared candidate registry.

Public logs nominate/update work. Receipt/header-authenticated normalized events
alone populate rolling strategy inputs. No public value supplies a canonical field.
"""
import hashlib
import json
import os
from pathlib import Path
import time
from .plane import Plane, canonical, digest, plane_path


def interpretation(policy):
    from robinhood_research import CHAIN_ID
    from robinhood_research.identity import load
    from robinhood_research.pons import TEMPLATE
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
        from robinhood_research.provider_admission import fingerprint
        self.provider_endpoint=fingerprint(source) if source else None
        self.nominal_deadline_seconds=5.;self.limit=None

    def identity(self,event):
        return 'pons:'+str(self.policy['chain'])+':'+self.policy['factory']+':'+event['address'].lower()

    def enqueue(self,event,*,now=None,needs_work=True):
        from robinhood_research.pons_selective_continuation import ENTRY_THRESHOLDS
        observed=self.clock() if now is None else now
        key=self.identity(event)
        previous=self.plane.get(key)
        priority=2 if previous and previous['priority']<=2 else 4
        obs=event['transactionHash']+':'+event['logIndex']
        order=tuple(int(event[k],16) for k in ('blockNumber','transactionIndex','logIndex'))
        result=self.plane.observe(key,'pons',obs,event,ordering=order,
            watermark=dict(block=order[0],hash=event['blockHash'],log=order[2],finality='confirmed'),
            interpretation=self.policy,observed=observed,
            deadline=observed+ENTRY_THRESHOLDS['max_state_age_seconds'],priority=priority,needs_work=needs_work)
        return result in ('created','updated')

    @property
    def rows(self):
        with self.plane.lock:
            rows=self.plane.db.execute("SELECT * FROM candidates WHERE lane='pons' AND pending=1").fetchall()
        return {r['id']:self._scheduled(dict(r)) for r in rows}

    def _scheduled(self,r):
        return dict(key=r['id'],event=json.loads(r['payload']),queued_at=r['observed'],deadline=r['deadline'],work=r)

    def pop(self,*,now=None,minimum_remaining_seconds=0):
        estimate=self.plane.estimate('pons',provider_interval=.5)
        # Provider admission is authoritative. Read its local outstanding work;
        # no RPC or new ceiling is introduced by this estimate.
        provider=os.environ.get('MM_CERTIFICATION_PROVIDER_DB')
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
        work=self.plane.claim(lane='pons',estimate_seconds=estimate)
        return self._scheduled(work) if work else None

    def finish(self,scheduled,evaluation,elapsed,*,logical=None,physical=None):
        from dataclasses import asdict, is_dataclass
        # Retain the full authenticated candidate, including receipt/header and
        # typed-state fields needed by the frozen paper lifecycle after restart.
        value=json.loads(json.dumps(evaluation,default=lambda x:asdict(x) if is_dataclass(x) else (_ for _ in ()).throw(TypeError(type(x).__name__))))
        return self.plane.finish(scheduled['work'],result=value,seconds=elapsed,logical=logical,physical=physical)

    def committed(self):
        from robinhood_research.pons import CurveState
        from robinhood_research.evidence import Stamp
        for row in self.plane.unconsumed('pons'):
            value=json.loads(row['result'])
            candidate=value['candidate']
            candidate['state']=CurveState(**candidate['state'])
            if 'stamp' in candidate:candidate['stamp']=Stamp(**candidate['stamp'])
            yield self._scheduled(row),value

    def acknowledge(self,scheduled):
        return self.plane.consume(scheduled['key'],scheduled['work']['generation'])

    def failure(self,scheduled,reason):
        state=('superseded' if reason=='candidate_generation_superseded' else
               'freshness_deadline_censored' if any(x in reason for x in ('stale','deadline')) else
               'provider_capacity_defer' if any(x in reason for x in ('429','capacity','budget')) else
               'transient_defer' if any(x in reason for x in ('transport_failure','http_50')) else 'authoritative_evidence_failure')
        return self.plane.finish(scheduled['work'],state=state,reason=reason)

    def telemetry(self):return self.plane.snapshot('pons')

    def close(self):self.plane.close()


def durable_cache(plane,domain):
    from robinhood_research.pons_selective_acquisition import ImmutableEvidenceCache
    class Cache(ImmutableEvidenceCache):
        def __init__(self):super().__init__();self.plane=plane;self.domain=domain
        def _load(self,kind,key):
            row=plane.evidence(domain+':'+kind,canonical(key))
            return row[0] if row else None
        def _save(self,kind,key,value):
            plane.put(domain+':'+kind,canonical(key),value,dict(authority='authenticated_alchemy',schema=1,finality='confirmed'))
        def immutable_curve(self,curve,block):
            row=self._load('compiled_create2_curve',curve.lower())
            return row if row and int(block)>=row['origin_block'] else None
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
        def receipt(self,tx,bh):return super().receipt(tx,bh) or self._load('receipt',[tx,bh])
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
    from robinhood_research.pons_selective_continuation import ENTRY_THRESHOLDS
    cache.plane.rolling_put(key,identity,row['event_at'],int(event['blockNumber'],16),row,proof,limit=ENTRY_THRESHOLDS['max_market_events'])
    return row


def save_cohort_checkpoint(result,cursor,phase):
    path=result.get('candidate_plane_path')
    if not path:return
    from .plane import process_identity
    plane=Plane(path)
    try:
        # Native append-only archives are fsynced before this checkpoint. Keep
        # the controller checkpoint bounded instead of rewriting every old row.
        archives=result.get('native_archive_paths',{})
        counts={k:len(result.get(k,[])) for k in archives}
        metadata={k:v for k,v in result.items() if k not in archives}
        metadata.update({k:[] for k in archives})
        plane.checkpoint('pons_cohort',dict(result=metadata,archive_counts=counts,
            cursor=cursor,phase=phase,owner=process_identity()))
    finally:plane.close()


def recover_cohort(path,policy):
    from .plane import alive
    from robinhood_research import BoundaryError
    if not Path(path).is_file():raise BoundaryError('selective_existing_run_requires_explicit_recovery')
    plane=Plane(path)
    try:
        saved=plane.checkpoint_read('pons_cohort')
        if not saved or saved['result'].get('policy_hash')!=policy:
            raise BoundaryError('selective_existing_run_requires_explicit_recovery')
        if saved['phase']=='finalizing':raise BoundaryError('selective_completed_run_cannot_restart')
        if alive(saved['owner']):raise BoundaryError('selective_cohort_owner_still_alive')
        result=saved['result']
        for key,name in result.get('native_archive_paths',{}).items():
            file=Path(name);expected=saved.get('archive_counts',{}).get(key,0)
            if not file.exists():
                if expected:raise BoundaryError('candidate_archive_missing')
                result[key]=[];continue
            try:rows=[json.loads(line) for line in file.read_text().splitlines() if line]
            except (ValueError,OSError):raise BoundaryError('candidate_archive_unproven') from None
            if len(rows)<expected:raise BoundaryError('candidate_archive_regression')
            result[key]=rows
        return result
    finally:plane.close()


def restore_position_needs(path,capital_path):
    """Restore safety needs from native authority before any fresh admission.

    This does not recreate a paper controller from incomplete process memory.
    A reserved native position keeps the existing fail-closed recovery boundary.
    """
    import sqlite3
    db=sqlite3.connect('file:'+str(Path(capital_path).resolve())+'?mode=ro',uri=True)
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
    finally:db.close();plane.close()


def provider_totals(context):
    telemetry=context.telemetry()
    sessions=list(telemetry.get('completed_sessions',[]))
    if telemetry.get('current_session'):sessions.append(telemetry['current_session'])
    if not sessions:return (0,0)
    if any('logical_requests' not in r or 'transport_requests' not in r for r in sessions):return (None,None)
    logical=sum(r['logical_requests'] for r in sessions)
    physical=sum(r['physical_http_requests'] for r in sessions) if all('physical_http_requests' in r for r in sessions) else None
    return logical,physical
