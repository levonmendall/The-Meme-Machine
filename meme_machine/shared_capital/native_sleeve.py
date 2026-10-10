"""Native sizing and attribution with shared funding, using existing journals."""
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path
from collections import deque
from functools import wraps
import json
import os
import time

from meme_machine.exact_money import amount, money, exact
from meme_machine.runtime.sleeve_reservations import SleeveReservations
from .model import CapitalError, CapitalRequest, Valuation, digest, canonical
from .runtime import connection, selected, FIELDS


class FundingDenied(ValueError):
    """Authentically qualified native opportunity lacking executable funding."""


_LATENCIES={}


def measured_grant(fn):
    @wraps(fn)
    def measured(self,*args,**kwargs):
        start=time.monotonic();r=self.identity['lane']+('_survivor' if 'survivor' in kwargs['strategy'] else '_current')
        try:return fn(self,*args,**kwargs)
        finally:
            from meme_machine.runtime import status
            with status.lock:
                samples=_LATENCIES.setdefault(r,deque(maxlen=128));samples.append(int((time.monotonic()-start)*1000000))
                rows={}
                for regime,values in _LATENCIES.items():
                    ordered=sorted(values);n=len(ordered)
                    rows[regime]=dict(samples=n,median_us=ordered[n//2],p95_us=ordered[min(n-1,int(n*.95))],
                        p99_us=ordered[min(n-1,int(n*.99))],above_5s_observation_threshold=sum(t>5000000 for t in ordered))
                status.state['shared_capital_metrics']=dict(state='MEASURED',scope='last_128_requests_per_regime_this_process',
                    includes='durable_queue_and_allocation',regimes=rows)
    return measured


def authority_for(book):
    if getattr(book,'_shared_authority',None):return book._shared_authority
    path=Path(book.db.execute('PRAGMA database_list').fetchone()[2]).resolve()
    for root in path.parents:
        portfolio=root/'portfolio.sqlite'
        if portfolio.is_file():
            shared=selected(portfolio)
            if shared:
                book._shared_authority=connection(shared)
                return book._shared_authority
            return None
    return None


def receipt(book,identity,*,scale=False):
    authority=authority_for(book)
    if authority is None:return None
    state=authority.ledger()
    strategy=book.identity['lane'];lane='pump' if 'pump' in strategy else 'pons'
    key=lane+':'+identity+(':scale' if scale else '')
    req_id=state.get('runtime_native_requests',{}).get(key)
    req=state['requests'].get(req_id)
    if not req or req['status'] not in ('RESERVED','COMMITTED','CONSUMED'):
        raise CapitalError('native_spending_requires_shared_grant')
    return dict(epoch_id=state['epoch_id'],request_id=req_id,
        maximum_native_units=req['value']['native_requested_units'])


def verify_receipt(book,value,units):
    # Cache only immutable, already-verified historical grant facts. Actual
    # reservation/consumption still reads live cash and holds in its transaction.
    key=digest(value)
    cache=getattr(book,'_shared_verified_receipts',set())
    if key in cache:
        if units>value['maximum_native_units']:raise CapitalError('native_shared_funding_receipt_invalid')
        return True
    authority=authority_for(book)
    if authority is None:raise CapitalError('native_shared_funding_authority_missing')
    state=authority.ledger();req=state['requests'].get(value.get('request_id'))
    if (value.get('epoch_id')!=state['epoch_id'] or not req or not req.get('decision')
            or req['decision']['status']!='RESERVED' or req['value']['native_requested_units']!=value.get('maximum_native_units')
            or units>value['maximum_native_units']):
        raise CapitalError('native_shared_funding_receipt_invalid')
    cache.add(key);book._shared_verified_receipts=cache
    return True


def funded(book,identity,units,*,scale=False):
    value=receipt(book,identity,scale=scale)
    if value:verify_receipt(book,value,units)
    return value


def legacy_backing(book,identity,units):
    """Historical journals stay unchanged; only a verified migration can back them."""
    authority=authority_for(book)
    if authority is None:return False
    state=authority.ledger();lane='pump' if 'pump' in book.identity['lane'] else 'pons'
    key=lane+':'+identity;life=state['native_aliases'].get(key)
    meta=state['migration_mapping']['position_meta'].get(life)
    if not meta or type(meta.get('original_native_basis')) is not int:return False
    maximum=meta['original_native_basis']
    if meta['scale_committed']:maximum+=maximum//2
    else:
        req=state['requests'].get(state.get('runtime_native_requests',{}).get(key+':scale'))
        if req and req.get('decision',{}).get('status')=='RESERVED':maximum+=req['value']['native_requested_units']
    return units<=maximum


class SharedSleeve(SleeveReservations):
    def __init__(self,*args,**kwargs):
        database=os.environ.get('MM_PORTFOLIO_ACCOUNTING_DB')
        path=selected(database) if database else None
        if path is None:raise CapitalError('shared_authority_not_selected')
        self.authority=connection(path)
        super().__init__(*args,**kwargs)

    @measured_grant
    @exact
    def _grant(self,identity,*,strategy,units,at,asset,evidence,generation=1,kind='new',scale_state=None,scale_facts=None):
        from meme_machine.runtime.usd_valuation import native_reader
        lane=self.identity['lane'];r=lane+('_survivor' if 'survivor' in strategy else '_current')
        from meme_machine.operational.admission import available
        reason=available(self.authority.ledger(),max(at,int(time.time())),live=True)
        if reason:raise FundingDenied(reason)
        value=native_reader(lane)(at)
        unit=value.amount(1,at)
        state=self.authority.ledger()
        with localcontext() as context:
            context.prec=80
            equity=max(0,int(self._family_equity(state,r)/unit))
        target=equity*(250 if kind=='scale' else 500)//10000
        principal=min(units,target) if kind=='new' else units
        if principal<=0:raise CapitalError('POSITION_SIZING_BASIS')
        req_id='native-'+digest([state['epoch_id'],lane,identity,kind])
        key=lane+':'+identity+(':scale' if kind=='scale' else '')
        prior=state.get('runtime_native_requests',{}).get(key)
        if prior:
            req=state.get('requests',{}).get(prior) or state.get('runtime_inbox',{}).get(prior)
            if req and (req.get('value',req)['native_requested_units']!=units):raise CapitalError('native_funding_amount_conflict')
        else:
            candidate='candidate:'+digest([lane,asset,identity,kind])
            q=CapitalRequest(req_id,state['epoch_id'],'queued',r,candidate,generation,'0'*64,
                amount(Decimal(principal)*unit),amount(Decimal(principal)*unit),amount(Decimal(principal)*unit),
                amount(Decimal(principal)*unit),amount(Decimal(principal)*unit),amount(Decimal(units-principal)*unit),'0',
                Valuation(value.evidence_id,value.evidence_hash,value.observed_at,value.valid_until),
                native_sizing=dict(realized_equity_units=equity,usd_per_native_unit=amount(unit),journal_sha256=digest(evidence)),
                kind=kind,lifecycle_id=state['native_aliases'].get(lane+':'+identity) if kind=='scale' else None,
                scale_state=scale_state,scale_facts=scale_facts)
            # The extra native amount is an accounting identity, not a sizing input.
            owner=os.environ.get('MM_LANE_PROCESS_INSTANCE')
            # Keep the original valuation expiry. Native qualification and
            # execution deadlines still gate the later native fill.
            self.authority.queue(q,native_id=identity,economic_keys=[self.asset_key(asset)],
                evidence=dict(native_qualification_json=canonical(evidence),native_requested_units=units,
                    funding_deadline=value.valid_until),
                policy_hash=self.identity['policies'][strategy],token=owner,at=at)
        # One event-driven fixed round; unrelated management never waits here.
        for attempt in range(3):
            try:self.authority.drain(at=max(at,int(time.time())));break
            except CapitalError as error:
                if str(error).startswith('missing_active_manifest:'):
                    raise FundingDenied(str(error)) from error
                if str(error)!='allocation_inbox_frontier_changed' or attempt==2:raise
        req=self.authority.ledger()['requests'][req_id]
        if req['status'] not in ('RESERVED','COMMITTED','CONSUMED'):
            raise FundingDenied(req.get('reason') or 'shared_capital_unavailable')
        return dict(epoch_id=state['epoch_id'],request_id=req_id,maximum_native_units=units)

    @staticmethod
    def _family_equity(state,r):
        from .authority import _size_equity
        return _size_equity(state,r)

    def reserve(self,identity,*,strategy,amount,at,candidate=None,generation=None,regime=None,asset=None,funding_evidence=None):
        if candidate is not None:
            row=self.candidate(candidate)
            if not row or row['state']!='qualified' or row['generation']!=generation:raise ValueError('superseded_reservation')
            evidence=row['evidence']
            asset=asset or row.get('asset')
        else:
            evidence=funding_evidence
            if not evidence:raise CapitalError('authentic_native_qualification_required')
        grant=self._grant(identity,strategy=strategy,units=amount,at=at,asset=asset or candidate,
            evidence=evidence,generation=generation or 1)
        self._grant_receipt=grant
        try:return super().reserve(identity,strategy=strategy,amount=amount,at=at,candidate=candidate,
            generation=generation,regime=regime,asset=asset)
        finally:self._grant_receipt=None

    def reserve_scale(self,identity,*,amount,original_basis,at,request,scale_state=None,scale_facts=None):
        row=self.get(identity)
        if not row or row['status']!='filled' or row.get('scale_committed'):raise ValueError('scale_lifecycle_state')
        if scale_state is None or scale_facts is None:raise CapitalError('verified_scale_evidence_required')
        grant=self._grant(identity,strategy=row['strategy'],units=amount,at=at,asset=row['asset'],
            evidence=dict(request=request,scale_state=scale_state,scale_facts=scale_facts),kind='scale',
            scale_state=scale_state,scale_facts=scale_facts)
        self._grant_receipt=grant
        try:return super().reserve_scale(identity,amount=amount,original_basis=original_basis,at=at,request=request)
        finally:self._grant_receipt=None

    def recover_scale(self,identity,*,request,committed,native_verified):
        if native_verified is not True:raise CapitalError('scale_recovery_proof')
        if not committed:
            state=self.authority.ledger()
            key=self.identity['lane']+':'+identity+':scale'
            req_id=state.get('runtime_native_requests',{}).get(key)
            req=state['requests'].get(req_id)
            if req and req['status'] in ('RESERVED','COMMITTED'):
                self.authority.command('scale-absence:'+req_id,'runtime_cancel',dict(request_id=req_id,at=state['at'],
                    proof_sha256=digest([identity,request,'native_verified_absence']),proof_kind='VERIFIED_NATIVE_ABSENCE'),state['at'])
        return super().recover_scale(identity,request=request,committed=committed,native_verified=native_verified)

    def release(self,identity,**kwargs):
        if kwargs.get('native_verified') is not True:raise ValueError('native_terminal_required')
        state=self.authority.ledger();key=self.identity['lane']+':'+identity
        req_id=state.get('runtime_native_requests',{}).get(key)
        req=state['requests'].get(req_id);life=state['native_aliases'].get(key)
        if req and req['status'] in ('RESERVED','COMMITTED'):
            self.authority.command('native-absence:'+req_id,'runtime_cancel',dict(request_id=req_id,at=state['at'],
                proof_sha256=kwargs['terminal_hash'],proof_kind='VERIFIED_NATIVE_ABSENCE'),state['at'])
        elif life in state['positions'] and state['positions'][life]['status']=='OPEN':
            raise CapitalError('shared_terminal_requires_settlement')
        return super().release(identity,**kwargs)

    def _shared_reserved(self,identity,units):
        grant=getattr(self,'_grant_receipt',None)
        return bool(grant and units<=grant['maximum_native_units'])

    def recover_unmaterialized(self,native_ids,*,strategy,verified):
        """Startup-only absence proof, before this regime admits any workers."""
        if verified is not True:raise CapitalError('native_replay_required')
        state=self.authority.ledger();family=self.identity['lane']
        r=family+('_survivor' if 'survivor' in strategy else '_current')
        for key,req_id in state.get('runtime_native_requests',{}).items():
            req=state['requests'].get(req_id)
            queued=state.get('runtime_inbox',{}).get(req_id)
            if not key.startswith(family+':') or not (req or queued):continue
            if (req['value'] if req else queued)['regime']!=r:continue
            scale=key.endswith(':scale');native=key[len(family)+1:]
            if scale:native=native[:-6]
            held=self.get(native)
            absent=(native not in native_ids if not scale else
                not (held or {}).get('scale_reservation') and family+':'+native not in state.get('runtime_pending',{}))
            if absent and (queued or req['status'] in ('RESERVED','COMMITTED')):
                proof=digest([native,sorted(native_ids),'verified_startup_native_absence'])
                self.authority.command('startup-absence:'+req_id,'runtime_cancel',dict(request_id=req_id,at=state['at'],
                    proof_sha256=proof,proof_kind='VERIFIED_NATIVE_ABSENCE'),state['at'])

    def _shared_attribution(self,positions,available):
        state=self.authority.ledger()
        for row in positions.values():
            if not row['held']:continue
            value=row.get('shared_funding')
            life=state['native_aliases'].get(self.identity['lane']+':'+row['id'])
            if value is None:
                if life not in state['positions'] and life not in {h.get('lifecycle_id') for h in state['reservations'].values()}:
                    raise CapitalError('unbacked_native_family_attribution')
            else:
                req=state['requests'].get(value['request_id'])
                if not req or req.get('decision',{}).get('status')!='RESERVED':raise CapitalError('unbacked_native_family_attribution')
        return True

    def sizing_basis(self,target_bps,*,minimum_bps=0):
        # The existing native sizing bridge reads this epoch's verified realized
        # base. Shared cash remains the separate funding component in both models.
        result=super().sizing_basis(target_bps,minimum_bps=minimum_bps)
        from meme_machine.runtime.usd_valuation import native_reader
        at=int(time.time());unit=native_reader(self.identity['lane'])(at).amount(1,at)
        from .authority import capital_view
        state=self.authority.ledger()
        result['available']=int(money(capital_view(state)['free_cash'])/unit)
        result['allocatable_target']=min(result['target'],result['available'])
        result['sizing_basis']=state['policy']['sizing_basis']
        return result


def cohort_receipt(db,identity,units):
    from types import SimpleNamespace
    authority=authority_for(SimpleNamespace(db=db))
    if authority is None:return None
    state=authority.ledger();req_id=state.get('runtime_native_requests',{}).get('pons:'+identity)
    req=state['requests'].get(req_id)
    if not req or req['status'] not in ('RESERVED','COMMITTED','CONSUMED') or units>req['value']['native_requested_units']:
        raise CapitalError('native_spending_requires_shared_grant')
    return dict(epoch_id=state['epoch_id'],request_id=req_id,maximum_native_units=req['value']['native_requested_units'])


def cohort_backing(db,rows):
    from types import SimpleNamespace
    active=[r for r in rows if r['reserved']]
    if not active:return False
    for row in active:
        value=row.get('shared_funding')
        if value is None:
            if not legacy_backing(SimpleNamespace(db=db,identity=dict(lane='pons')),row['id'],row['reserved']):return False
            continue
        verify_receipt(SimpleNamespace(db=db),value,row['reserved'])
    return True
