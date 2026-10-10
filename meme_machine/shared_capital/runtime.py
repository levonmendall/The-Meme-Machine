"""Native PAPER bridge using the preserved allocator and its single SQLite journal.

Owner manifests describe durable producer inboxes, including explicit empties.
Only actual native requests enter an allocation round. Safety delivery does not
wait for owners, candidates or round completion. No provider I/O occurs here.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import json
import os
import sqlite3
import threading
import time

from meme_machine.exact_money import amount, exact, money
from meme_machine.portfolio_lane_integration import LaneEvent
from .authority import capital_view, _size_equity
from .model import CapitalError, CapitalRequest, Valuation, FAMILIES, digest, wire
from .operational_candidate import PumpPonsCapital, ACTIVE_REGIMES

FIELDS = ('requested_basis','minimum_basis','liquidity_capacity','execution_capacity',
    'strategy_capacity','cost_headroom','settlement_headroom','kind','lifecycle_id',
    'native_quality_bps','expected_holding_seconds','scale_state','scale_facts','native_sizing')
_LOCAL = threading.local()


def seconds(value):
    return int(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp())


def process_identity(pid):
    # PID plus kernel start time fences process replacement and PID reuse.
    raw = Path('/proc',str(pid),'stat').read_text()
    fields = raw[raw.rfind(')')+2:].split()
    if fields[0] == 'Z': raise CapitalError('active_manifest_owner_dead')
    return fields[19]


def selected(database):
    """Read the durable authority selection; no environment switch can reseed it."""
    path=Path(database).resolve()
    if not path.is_file():return None
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='portfolio_funding_authority'").fetchone():return None
        row=db.execute('SELECT body FROM portfolio_funding_authority WHERE id=1').fetchone()
        if row is None:raise CapitalError('incomplete_authority_cutover')
        value=json.loads(row[0])
        if value['state']!='SHARED':raise CapitalError('incomplete_authority_cutover')
        shared=path.parent/'shared-capital.sqlite'
        if not shared.is_file() or shared.is_symlink():raise CapitalError('selected_shared_authority_missing')
        with sqlite3.connect(shared.as_uri()+'?mode=ro',uri=True) as ledger:
            row=ledger.execute('SELECT body,hash FROM shared_capital_projection WHERE id=1').fetchone()
            if row is None:raise CapitalError('selected_shared_authority_incomplete')
            state=json.loads(row[0])
            if (digest(state)!=row[1] or state['epoch_id']!=value['epoch_id']
                    or state['inception_sha256']!=value['inception_sha256']
                    or digest(state['policy'])!=value['policy_sha256']):
                raise CapitalError('selected_shared_authority_identity_mismatch')
        return shared


def connection(path):
    path=Path(path).resolve();key=str(path)
    pool=getattr(_LOCAL,'pool',None)
    if pool is None:pool=_LOCAL.pool={}
    inode=(path.stat().st_dev,path.stat().st_ino)
    cached=pool.get(key)
    if cached and cached[0]!=inode:
        cached[1].close();cached=None
    if cached is None:
        cached=(inode,RuntimeCapital(path));pool[key]=cached
    return cached[1]


class RuntimeCapital(PumpPonsCapital):
    def ledger(self):
        # Read the validated durable projection without a portfolio valuation
        # scan. A spending operation still takes its own fresh writer snapshot.
        with self._transaction(write=False):return self._read()

    def command(self,op,action,data,at):
        # Live process/transport checks stay outside the deterministic replay
        # reducer. Journal replay must remain valid after every process dies.
        from meme_machine.operational.admission import available,require_normal
        if action=='runtime_admission' and data['mode'] in ('NORMAL','AUTONOMY'):require_normal()
        if action in ('runtime_queue','runtime_allocate') or (action=='runtime_prepare' and data['kind'] in ('enter','rebalance')):
            reason=available(self.ledger(),max(at,int(time.time())),live=True)
            if reason:raise CapitalError(reason)
        return self._write(op,action,at,wire(data))

    def _duplicate_matches(self,previous,current):
        prior,new=json.loads(previous),json.loads(current)
        if new['action'].startswith('runtime_'):
            # The retry clock is not economic identity. Check inside the same
            # SQLite writer transaction even when independent clients race.
            prior.pop('at');new.pop('at')
            return prior==new
        return super()._duplicate_matches(previous,current)

    def owner(self,r,token,pid,*,ready,at):
        from .model import regime
        regime(r)
        if r not in ACTIVE_REGIMES:raise CapitalError('paused_family_capital_admission:'+r)
        data=dict(regime=r,token=token,pid=pid,start=process_identity(pid),ready=bool(ready))
        # An actual readiness transition is durable. Unchanged heartbeats do not
        # append events or trigger another allocation.
        state=self.ledger()
        if state.get('runtime_owners',{}).get(r)==data:return
        return self.command('owner:'+digest([data,state.get('runtime_owner_version',0)]),'runtime_owner',data,at)

    def queue(self,request,*,native_id,economic_keys,evidence,policy_hash,token,at):
        if request.regime not in ACTIVE_REGIMES:raise CapitalError('paused_family_capital_admission:'+request.regime)
        return self.command('queue:'+request.request_id,'runtime_queue',dict(request=request.value(at),
            native_id=native_id,economic_keys=economic_keys,evidence=evidence,policy_hash=policy_hash,token=token),at)

    def drain(self,*,at):
        state=self.ledger();queued=state.get('runtime_inbox',{})
        if not queued:return {'decisions':{},'order':[]}
        owners=state.get('runtime_owners',{})
        for r in ACTIVE_REGIMES:
            owner=owners.get(r)
            if not owner or not owner['ready']:raise CapitalError('missing_active_manifest:'+r)
            try:alive=process_identity(owner['pid'])==owner['start']
            except (OSError,CapitalError):alive=False
            if not alive:raise CapitalError('missing_active_manifest:'+r)
        ids=sorted(queued)
        return self.command('round:'+digest(ids),'runtime_allocate',dict(request_ids=ids,owners=owners),at)

    def _apply(self,state,event):
        action=event['action']
        if not action.startswith('runtime_'):return super()._apply(state,event)
        if state is None:raise CapitalError('preserved_epoch_migration_required')
        at=max(event['at'],state['at']);data=event['data'];state['at']=at
        def apply(action,data):
            nonlocal state
            state,result=super(RuntimeCapital,self)._apply(state,dict(action=action,at=at,data=data))
            return result
        if action=='runtime_admission':
            from meme_machine.operational.admission import configure
            return state,configure(state,data,at)
        if action=='runtime_owner':
            state.setdefault('runtime_owners',{})[data['regime']]=deepcopy(data)
            state['runtime_owner_version']=state.get('runtime_owner_version',0)+1
            return state,dict(accepted=True)
        if action=='runtime_publish':
            if state['inception'].get('sizing_basis')=='shared_realized_equity':
                from .authority import risk_view
                from meme_machine.portfolio_accounting import _decode_checkpoint
                from meme_machine.runtime.usd_valuation import utc
                risk=risk_view(state,at)
                history=state.setdefault('reporting_history',_decode_checkpoint(state['migration_source']['replayed_state'])['history'])
                values={'portfolio':amount(risk['marked_equity']) if risk['marked_equity'] is not None else None}
                for family in set(FAMILIES.values()):
                    value=sum((money(state['realized'][r]) for r in state['realized'] if FAMILIES[r]==family),Decimal(0))
                    if risk['valuation_ready']:
                        value+=sum((money(p['mark']['net_value'])-money(p['basis']) for p in state['positions'].values()
                                    if p['status']=='OPEN' and FAMILIES[p['regime']]==family),Decimal(0))
                    values[family]=amount(value) if risk['valuation_ready'] else None
                when=utc(at)
                history[:]=[h for h in history if h['at']!=when]
                history.extend(dict(epoch_id=state['epoch_id'],series=key,at=when,value=value) for key,value in sorted(values.items()))
                history[:]=history[-2000:]
            return state,dict(accepted=True)
        if action=='runtime_cancel':
            req_id=data['request_id'];queued=state.get('runtime_inbox',{}).pop(req_id,None)
            if queued:
                state['requests'][req_id]=dict(value=queued,status='CANCELLED',reason='VERIFIED_NATIVE_ABSENCE')
            return state,apply('cancel',data)
        if action=='runtime_queue':
            q=deepcopy(data['request']);r=q['regime'];owner=state.get('runtime_owners',{}).get(r)
            q['native_requested_units']=data['evidence']['native_requested_units']
            q['funding_deadline']=data['evidence'].get('funding_deadline',q['valuation']['valid_until'])
            if not owner or not owner['ready'] or owner['token']!=data['token']:
                raise CapitalError('missing_active_manifest:'+r)
            life=apply('native_identity',dict(family=FAMILIES[r],native_lifecycle_id=data['native_id']))['lifecycle_id']
            key=FAMILIES[r]+':'+data['native_id']+(':'+q['kind'] if q['kind']=='scale' else '')
            prior=state.setdefault('runtime_native_requests',{}).get(key)
            if prior and prior!=q['request_id']:raise CapitalError('conflicting_native_funding_request')
            state['runtime_native_requests'][key]=q['request_id']
            if q['kind']!='new':q['lifecycle_id']=life
            evidence=deepcopy(data['evidence']);evidence['capital_request']={k:q[k] for k in FIELDS}
            if q['kind']=='scale':evidence.update(scale_state=q['scale_state'],scale_facts=q['scale_facts'])
            observation=apply('observe',dict(regime=r,candidate_id=q['candidate_id'],generation=q['generation'],
                status='QUALIFIED',economic_keys=data['economic_keys'],evidence=evidence,
                qualification_sha256=digest(evidence),policy_hash=data['policy_hash']))
            q['qualification_sha256']=observation['qualification_sha256']
            state.setdefault('runtime_inbox',{})[q['request_id']]=q
            return state,dict(status='QUEUED',request_id=q['request_id'],lifecycle_id=life)
        if action=='runtime_allocate':
            owners=state.get('runtime_owners',{})
            if data['owners']!=owners or set(owners)!=set(ACTIVE_REGIMES) or any(not o['ready'] for o in owners.values()):
                raise CapitalError('missing_or_changed_active_manifest')
            inbox=state.get('runtime_inbox',{})
            if sorted(inbox)!=data['request_ids']:raise CapitalError('allocation_inbox_frontier_changed')
            round_id='native:'+digest(data['request_ids'])
            apply('open_round',dict(round_id=round_id,cutoff=at))
            for q in inbox.values():
                q=deepcopy(q);q['round_id']=round_id
                apply('submit',q)
            # Each manifest is an explicit snapshot of its owned durable inbox.
            # Paused manifests are definitive empties and have no owner process.
            for r in (*ACTIVE_REGIMES,'meteora','ramses'):
                apply('seal',dict(round_id=round_id,regime=r,request_ids=sorted(
                    q['request_id'] for q in inbox.values() if q['regime']==r)))
            result=apply('allocate',dict(round_id=round_id))
            state['runtime_inbox']={}
            return state,result
        if action=='runtime_prepare':
            family,native_id=data['lane'],data['native_id'];key=family+':'+native_id
            pending=state.setdefault('runtime_pending',{})
            if key in pending:raise CapitalError('prior_native_delivery_requires_reconciliation')
            life=state['native_aliases'].get(key)
            if life is None:raise CapitalError('shared_funding_missing_before_native_commit')
            kind=data['kind'];scale=kind=='rebalance'
            req_id=state['runtime_native_requests'].get(key+(':scale' if scale else ''))
            req=state['requests'].get(req_id)
            p=state['positions'].get(life)
            r=p['regime'] if p else (req or {}).get('value',{}).get('regime')
            if r is None:raise CapitalError('native_regime_identity_missing')
            seq=state['native_cursors'].get(r+':'+life,0)+1
            native=dict(epoch_id=state['epoch_id'],regime=r,lifecycle_id=life,event_id=data['event_key'],
                sequence=seq,journal_sha256=data['journal_hash'])
            item=dict(data,native=native,request_id=req_id,lifecycle_id=life)
            if kind in ('enter','rebalance'):
                from meme_machine.operational.admission import available
                reason=available(state,at)
                if reason:raise CapitalError(reason)
                # Prove the fill fits its durable hold before the native journal
                # commits. The simulation does not spend cash or release a hold.
                facts=data['data'];valuation=data['value_evidence']
                v=dict(evidence_id=valuation['evidence_id'],evidence_sha256=valuation['evidence_sha256'],
                    as_of=seconds(valuation['as_of']),valid_until=seconds(valuation['valid_until']),currency='USD')
                economic_at=seconds(data['at']);trial=deepcopy(state);trial['at']=min(trial['at'],economic_at)
                trial,_=super()._apply(trial,dict(action='consume',at=economic_at,data=dict(
                    request_id=req_id,lifecycle_id=life,basis=facts['basis'] if kind=='enter' else facts['basis_added'],
                    cost=facts.get('fee','0'),included_cost=facts.get('included_fee','0'),native=native,valuation=v,
                    native_basis_units=data['metadata']['native_basis_units'])))
                self._reconcile(trial)
            if kind=='reserve':
                if not req or req['status']!='RESERVED':raise CapitalError('shared_funding_missing_before_native_commit')
                if money(data['data']['amount'])>money(req['decision']['total']):raise CapitalError('native_reserve_exceeds_shared_grant')
                apply('commit',dict(request_id=req_id,commitment_id='native:'+data['journal_hash'],
                    intent_sha256=digest(data),lifecycle_id=life))
                apply('native_ack',dict(request_id=req_id,lifecycle_id=life,native=native))
            pending[key]=item
            result=LaneEvent(state['epoch_id'],family,life.split(':',1)[1],data['event_key'],seq,
                data['journal_hash'],kind,data['at'],data['data'],data['value_evidence']).canonical_value()
            return state,result
        if action in ('runtime_commit','runtime_abort'):
            key=data['lane']+':'+data['native_id'];item=state.setdefault('runtime_pending',{}).get(key)
            if item is None:return state,None
            if (item['event_key'],item['journal_hash'])!=(data['event_key'],data['journal_hash']):
                raise CapitalError('native_commit_does_not_match_pending_delivery')
            life,req_id,kind=item['lifecycle_id'],item['request_id'],item['kind']
            facts=item['data'];valuation=item['value_evidence']
            v=None if valuation is None else dict(evidence_id=valuation['evidence_id'],evidence_sha256=valuation['evidence_sha256'],
                as_of=seconds(valuation['as_of']),valid_until=seconds(valuation['valid_until']),currency='USD')
            if action=='runtime_abort':
                # The native book's verified absence is the only release proof.
                if kind in ('reserve','rebalance'):
                    apply('cancel',dict(request_id=req_id,at=at,proof_kind='VERIFIED_NATIVE_ABSENCE',proof_sha256=data['journal_hash']))
            elif kind in ('enter','rebalance'):
                # Delayed acknowledgement replays already-durable native facts
                # at their validated economic clock, not at the recovery clock.
                economic_at=seconds(item['at']);publication_at=state['at']
                state['at']=min(state['at'],economic_at);at=economic_at
                apply('consume',dict(request_id=req_id,lifecycle_id=life,basis=facts['basis'] if kind=='enter' else facts['basis_added'],
                    cost=facts.get('fee','0'),included_cost=facts.get('included_fee','0'),native=item['native'],valuation=v,
                    native_basis_units=item['metadata']['native_basis_units']))
                state['at']=max(publication_at,state['at'])
            elif kind in ('harvest','realize','settle'):
                economic_at=seconds(item['at']);publication_at=state['at']
                state['at']=min(state['at'],economic_at);at=economic_at
                basis=state['positions'][life]['basis'] if kind=='settle' else facts['basis_released']
                apply('realize',dict(lifecycle_id=life,basis_released=basis,gross_proceeds=facts['gross_proceeds'],
                    cost=facts.get('fee','0'),included_cost=facts.get('included_fee','0'),native=item['native'],valuation=v,terminal=kind=='settle'))
                state['at']=max(publication_at,state['at'])
            elif kind=='release':
                self._native(state,life,item['native'])
                apply('cancel',dict(request_id=req_id,at=at,proof_kind='DEFINITIVELY_CANCELLED',proof_sha256=data['journal_hash']))
            elif kind=='mark':
                if facts['state']=='CURRENT':
                    economic_at=seconds(item['at']);publication_at=state['at']
                    state['at']=min(state['at'],economic_at);at=economic_at
                    apply('mark',dict(lifecycle_id=life,net_value=facts['net_liquidation_value'],native=item['native'],valuation=v))
                    # The position was marked at this economic event time. The
                    # independent USD observation keeps its original expiry.
                    state['positions'][life]['mark']['at']=economic_at
                    state['at']=max(publication_at,state['at'])
                else:
                    self._native(state,life,item['native']);state['positions'][life]['mark']=None
            elif kind!='reserve':raise CapitalError('unsupported_shared_native_delivery')
            del state['runtime_pending'][key]
            return state,dict(accepted=True)
        raise CapitalError('unknown_runtime_capital_action')

    def _decision(self,state,request,at):
        if at>request.get('funding_deadline',at):
            return dict(status='QUALIFIED_BUT_CAPITAL_UNAVAILABLE',reason='FUNDING_EVIDENCE_EXPIRED',basis='0',total='0')
        from meme_machine.operational.admission import decision
        return decision(state,request,super()._decision(state,request,at),at)


class SharedNativePortfolio:
    shared=True
    def __init__(self,database,lane):
        if lane not in ('pump','pons'):raise CapitalError('paused_family_capital_admission:'+lane)
        self.database=Path(database);self.lane=lane
        path=selected(database)
        if path is None:raise CapitalError('shared_authority_not_selected')
        self.authority=connection(path)

    def equity(self):
        state=self.authority.ledger()
        return _size_equity(state,self.lane+'_current')

    @contextmanager
    def writer(self):
        # Compatibility for the existing boundary's read-only basis lookup.
        yield SharedReadView(self.authority),self

    def _alias(self,account,native):
        life=account.authority.ledger()['native_aliases'].get(self.lane+':'+native)
        if life is None:raise CapitalError('shared_native_identity_missing')
        return life.split(':',1)[1]

    def _canonical_lifecycle(self,lane,alias):return lane+':'+alias

    def prepare(self,native,*,event_key,journal_hash,kind,at,data,value_evidence=None,metadata=None):
        result=self.authority.command('intent:'+self.lane+':'+journal_hash,'runtime_prepare',dict(
            lane=self.lane,native_id=native,event_key=event_key,journal_hash=journal_hash,kind=kind,at=at,
            data=data,value_evidence=value_evidence,metadata=metadata or {}),seconds(at))
        return LaneEvent(**result)

    def committed(self,native,*,event_key,journal_hash):
        return self.authority.command('ack:'+self.lane+':'+journal_hash,'runtime_commit',dict(
            lane=self.lane,native_id=native,event_key=event_key,journal_hash=journal_hash),self.authority.ledger()['at'])

    def abort(self,native,event):
        return self.authority.command('abort:'+self.lane+':'+event.native_journal_hash,'runtime_abort',dict(
            lane=self.lane,native_id=native,event_key=event.native_event_id,journal_hash=event.native_journal_hash),
            self.authority.ledger()['at'])

    def pending(self):
        state=self.authority.ledger();out=[]
        for item in state.get('runtime_pending',{}).values():
            if item['lane']!=self.lane:continue
            n=item['native'];out.append((item['native_id'],LaneEvent(state['epoch_id'],self.lane,
                item['lifecycle_id'].split(':',1)[1],item['event_key'],n['sequence'],item['journal_hash'],
                item['kind'],item['at'],item['data'],item['value_evidence'])))
        return out

    def deliver(self,native,**facts):
        event=self.prepare(native,**facts)
        return self.committed(native,event_key=event.native_event_id,journal_hash=event.native_journal_hash)


class SharedReadView:
    def __init__(self,authority):self.authority=authority
    def snapshot(self):
        state=self.authority.ledger()
        return dict(positions={life:dict(p,remaining_basis=money(p['basis']),capital=money(p['original_basis']))
            for life,p in state['positions'].items()},reservations=state['reservations'])
    def sleeve_equity(self,lane):return _size_equity(self.authority.ledger(),lane+'_current')
