"""Nonfinancial adapter for the unchanged native Survivor market read methods.

The explicit method list below supplies acquisition, reconstruction and frozen
qualification only. No financial Runtime, sleeve, book or lifecycle is created.
One dedicated executor thread owns this adapter and its native History.
"""
from collections import Counter
import json
import time

from meme_machine.runtime.journal import canonical,digest
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime,Quotes
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY,POLICY_HASH
from meme_machine.lanes.pons.provider_admission import decision_work
from .managed_native_pons import require


class SurvivorMarketReadSide:
    # These are the actual production read implementations, not copied variants.
    # Deliberately exclude Runtime.__init__, step, _enter, _position, exits and
    # every financial publication/commit method. Missing authority fails closed.
    _provider_native=Runtime._provider
    _discover_scout=Runtime._discover_scout
    _watch_due=Runtime._watch_due
    _deep_watch_due=Runtime._deep_watch_due
    _schedule_watch=Runtime._schedule_watch
    candidate_readiness=Runtime.candidate_readiness
    _increment=Runtime._increment
    _recover_reorg=Runtime._recover_reorg
    _append_tape=Runtime._append_tape
    _increment_candidates=Runtime._increment_candidates
    fresh_state=Runtime.fresh_state
    fresh_quotes=Runtime.fresh_quotes
    reconstruct=Runtime.reconstruct
    qualify=Runtime.qualify
    observation_interval_seconds=Runtime.observation_interval_seconds

    def __init__(self,path,endpoint,plane,scout,*,cancel=None):
        from meme_machine.lanes.pons.pons_history import PonsHistory
        self.endpoint=endpoint;self.plane=plane;self.scout=scout
        self.cancel=cancel or (lambda:False);self.rpc=None;self.current=None
        self.history=PonsHistory(str(path),policy=POLICY_HASH)
        self.counts=Counter();self.last_snapshot={};self.closed=False
        # Native observations/strategy decisions may persist here. A position,
        # pending financial action or lifecycle state can never be written.
        for action in ('INSERT','UPDATE'):
            self.history.db.execute('CREATE TRIGGER IF NOT EXISTS managed_no_financial_'+action+
                ' BEFORE '+action+''' ON candidates WHEN
                json_extract(NEW.body,'$.position') IS NOT NULL OR
                json_extract(NEW.body,'$.pending_action') IS NOT NULL OR
                json_extract(NEW.body,'$.state') IN ('reserved','filled','runner','exit_pending')
                BEGIN SELECT RAISE(ABORT,'managed_survivor_financial_state_refused'); END''')
        self.history.db.execute('''CREATE TABLE IF NOT EXISTS managed_provider_corpus(
            seq INTEGER PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL)''')
        for row in self.history.rows(include_retired=True):
            self._nonfinancial(row)

    @staticmethod
    def _nonfinancial(row):
        require(not row.get('position') and not row.get('pending_action') and
            row.get('state') not in ('reserved','filled','runner','exit_pending'),
            'survivor_financial_state')

    def market_reference_basis(self,target_bps,*,minimum_bps=0):
        from meme_machine.lanes.pons.pons_selective_paper import STRATEGY_CAPITAL_QUOTE
        capital=STRATEGY_CAPITAL_QUOTE
        return dict(realized_equity=capital,target=capital*target_bps//10000,
                    minimum=capital*minimum_bps//10000,allocation_authority=False)

    def now(self):return int(time.time())

    def _capture(self,calls,values,scope):
        require(type(values) is list and len(values)==len(calls),'survivor_capture_shape')
        row=dict(calls=calls,values=values,scope=scope,provider=self.endpoint,
                 observed_at=time.time(),monotonic=time.monotonic())
        self.history.db.execute('INSERT INTO managed_provider_corpus(body,hash) VALUES(?,?)',
                                (canonical(row),digest(row)))
        return values

    def _provider(self):
        require(not self.cancel(),'survivor_cancelled')
        self._provider_native()
        if getattr(self.rpc,'_managed_captured',False):return
        rpc=self.rpc;original_call=rpc.call;original_batch=rpc.batch
        def call(method,params,*,scope='connectivity'):
            require(not self.cancel(),'survivor_cancelled')
            value=original_call(method,params,scope=scope)
            self._capture([(method,params)],[value],scope)
            return value
        def batch(calls,*,scope='connectivity'):
            require(not self.cancel(),'survivor_cancelled')
            return self._capture(calls,original_batch(calls,scope=scope),scope)
        rpc.call=call;rpc.batch=batch;rpc._managed_captured=True

    def _position_context(self):
        from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
        from meme_machine.runtime.robinhood.pons import durable_cache,shared_evidence_domain
        context=getattr(self,'position_evidence_context',None)
        if context is not None:return context
        context=SelectiveEvidenceContext(self.endpoint,cache=durable_cache(self.plane,shared_evidence_domain(self.endpoint)))
        original=context.batch
        def batch(calls,scope):
            require(not self.cancel(),'survivor_cancelled')
            calls=list(calls)
            return self._capture(calls,original(calls,scope),scope)
        context.batch=batch;self.position_evidence_context=context
        return context

    @decision_work(4)
    def step(self,top):
        """Production fair discovery/history/qualification turn, without entries."""
        require(not self.cancel(),'survivor_cancelled')
        self._provider();self._discover_scout()
        # The same fair bounded pool cohort that the production broad discovery
        # loop runs. Each pool keeps its own gap and coverage cursor.
        self.scout.read_pools(self.rpc,top)
        rows=self.history.rows();now=self.now()
        for row in rows:self._nonfinancial(row)
        active=[]
        for row in rows:
            if now-row['graduation']['at']>POLICY['universe']['max_seconds_after_graduation']:
                self.history.retire(row,expired_before=now-POLICY['universe']['max_seconds_after_graduation'])
            elif self._deep_watch_due(row,now):active.append(row)
        if active:
            self._increment_candidates(active,top)
            active=[self.history.get(row['id']) for row in active]
            row=self.history.qualification_turn(active,now)
            self._increment(row,min(top,row['block']+40));row=self.history.get(row['id'])
            if now-row['graduation']['at']<POLICY['universe']['min_seconds_after_graduation']:
                row['state']='aging';self.history.save(row);self.counts['aging_turns']+=1
            elif top-row['block']<=40:
                state=self.fresh_state(row['id'])
                quotes=self.fresh_quotes(state,self.market_reference_basis(500)['target'])
                facts=self.reconstruct(state,quotes);decision=self.qualify(facts)
                row=self.history.get(row['id']);self._nonfinancial(row)
                row.update(decision=decision,state=decision['stage'],
                           decision_policy_hash=POLICY_HASH)
                self._schedule_watch(row,state['at'],self.scout.signal(row['graduation']['transition']['market']))
                self.history.save(row)
                self.counts['qualification_completed']+=1
                self.counts['qualification_passed']+=bool(decision['candidate'])
        current=self.history.rows();eligible=sum(now-r['graduation']['at']>=
            POLICY['universe']['min_seconds_after_graduation'] for r in current)
        self.counts['turns']+=1
        self.last_snapshot=dict(available=True,counts=dict(self.counts),candidates=len(current),
            economic_events=self.history.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],
            price_points=self.history.db.execute('SELECT COUNT(*) FROM points').fetchone()[0],
            raw_provider_batches=self.history.db.execute('SELECT COUNT(*) FROM managed_provider_corpus').fetchone()[0],
            age_eligible_candidates=eligible,pending_graduations=self.history.pending_graduations(),
            pool_discovery=self.scout.snapshot(),acquisition=getattr(self,'acquisition',None),
            historical_readiness=getattr(self,'historical_readiness',None),
            maximum_history_lag_blocks=max((top-r.get('block',top) for r in current),default=0),
            qualification_throughput_verified=False,allocation_authority=False,
            observed_at=time.time(),monotonic=time.monotonic())
        return self.last_snapshot

    def replay(self):
        """Reauthenticate persisted native V4 swaps with the production decoder."""
        from meme_machine.lanes.pons.pons_selective_v4 import collect_v4_activity
        from meme_machine.lanes.pons.protocols import PoolKey
        raw={};headers={};receipts={};txs={};corpus=[]
        for sequence,body,checksum in self.history.db.execute(
                'SELECT seq,body,hash FROM managed_provider_corpus ORDER BY seq'):
            row=json.loads(body);require(digest(row)==checksum,'survivor_corpus_digest')
            corpus.append([sequence,checksum])
            for (method,params),value in zip(row['calls'],row['values']):
                if method=='eth_getLogs':
                    for event in value:
                        if len(event.get('topics',[]))>1:
                            identity=f"{int(event['blockNumber'],16)}:{event['transactionHash']}:{int(event['logIndex'],16)}"
                            raw[identity]=event
                elif method in ('eth_getBlockByHash','eth_getBlockByNumber') and isinstance(value,dict):headers[value['hash']]=value
                elif method=='eth_getTransactionReceipt':receipts[(value['transactionHash'],value['blockHash'])]=value
                elif method=='eth_getTransactionByHash':txs[(value['hash'],value['blockHash'])]=value
        events=0;candidate_hashes=[]
        for row in self.history.rows(include_retired=True):
            self._nonfinancial(row)
            _,expected=self.history.facts(row['id'],row.get('through',row['graduation']['at']))
            event_ids={e['id'] for e in expected}
            selected=[raw[identity] for identity in event_ids if identity in raw]
            require(len(selected)==len(expected),'survivor_replay_raw_missing')
            selected.sort(key=lambda e:tuple(int(e[k],16) for k in ('blockNumber','transactionIndex','logIndex')))
            for event in selected:
                pair=(event['transactionHash'],event['blockHash']);receipt=receipts[pair]
                if pair not in txs and receipt.get('from'):
                    txs[pair]=dict(hash=pair[0],blockHash=pair[1],**{'from':receipt['from']})
            shared=dict(raw=selected,headers=headers,receipts=receipts,txs=txs,sessions=[])
            tape=collect_v4_activity(self.endpoint,pool_id=row['graduation']['transition']['market'],
                key=PoolKey(**row['graduation']['key']),token=row['id'],
                start_block=row['graduation']['block'],end_block=row.get('block',row['graduation']['block']),
                _shared=shared)
            decoded={e['identity']:dict(id=e['identity'],at=e['event_at'],group=e['group'],
                buy=e['side']=='buy',quote=e['quote'],tokens=e['tokens'],authenticated=True,
                block=e['block'],transaction_index=e.get('transaction_index'),log_index=e.get('log_index'))
                for e in tape['swaps']}
            require(all(decoded.get(e['id'])==e for e in expected),'survivor_replay_economic_mismatch')
            events+=len(expected);candidate_hashes.append(digest([row,expected]))
        return dict(verified=True,events=events,candidates=len(candidate_hashes),
                    corpus_sha256=digest(corpus),history_sha256=digest(candidate_hashes),allocation_authority=False)

    def close(self):
        if not self.closed:self.history.close();self.closed=True
