"""Bounded physical-response head measurements, with no economic authority.

Explicit attachment observes existing real native transports. Cache hits,
sequencer clocks and caller-supplied result dictionaries are not head receipts.
The refresh controller adds only stale, normally governed native reads; it does
not construct a Budget, URL transport, portfolio, new quota or coverage proof.
"""
from dataclasses import dataclass
from pathlib import Path
import math
import os
import re
import subprocess
import threading
import time
import uuid
import weakref

FRESH_SECONDS = 5
REFRESH_SECONDS = 5
MAXIMUM_BYTES = 8192


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _sha(value, length=40):
    return type(value) is str and re.fullmatch('[0-9a-f]{'+str(length)+'}',value) is not None


def _number(value):
    return type(value) in (int,float) and math.isfinite(value) and 0 <= value < 2**63


def _quantity(value):
    _require(type(value) is str and re.fullmatch(r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)',value)
             is not None,'head_quantity')
    number=int(value,16)
    _require(0 <= number < 2**63,'head_quantity')
    return number


@dataclass(frozen=True)
class HeadSource:
    commit: str
    tree: str
    pid: int
    process_start_ticks: int
    generation: str

    @classmethod
    def verified_checkout(cls, *, expected_commit, expected_tree, generation):
        """Bind the existing exact-source guard; local cleanliness is not approval."""
        _require(_sha(expected_commit) and _sha(expected_tree) and _sha(generation,32),
                 'head_source_identity')
        root=Path(__file__).resolve().parents[2]
        env=dict(os.environ,GIT_OPTIONAL_LOCKS='0',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1')
        values=[]
        for arguments in (('rev-parse','HEAD'),('rev-parse','HEAD^{tree}'),
                          ('status','--porcelain','--untracked-files=normal')):
            result=subprocess.run(['git','-c','safe.directory='+str(root),'-c','core.hooksPath=/dev/null',
                '-c','core.fsmonitor=false','--no-optional-locks',*arguments],cwd=root,env=env,
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                timeout=5,check=True)
            _require(len(result.stdout)<=8192,'head_source_bound')
            values.append(result.stdout.decode('ascii').strip())
        _require(values==[expected_commit,expected_tree,''],'head_source_changed_or_dirty')
        with Path('/proc/self/stat').open('rb') as file:
            raw=file.read(4097)
        _require(len(raw)<=4096,'head_process_identity')
        leader,tail=raw.decode('ascii').rsplit(')',1)
        pid=os.getpid();ticks=int(tail.split()[19])
        _require(int(leader.split('(',1)[0])==pid and ticks>0,'head_process_identity')
        return cls(expected_commit,expected_tree,pid,ticks,generation)


class MarketHeads:
    """Two explicit head kinds; every physical completion keeps its own clock."""
    def __init__(self, source, *, generation, clock=time.monotonic, wall=time.time):
        _require(type(source) is HeadSource and _sha(source.commit) and _sha(source.tree)
            and type(source.pid) is int and 0<source.pid<2**31
            and type(source.process_start_ticks) is int and 0<source.process_start_ticks<2**63
            and _sha(source.generation,32) and callable(generation)
            and callable(clock) and callable(wall),'head_source_identity')
        self.source=source;self.generation=generation;self.clock=clock;self.wall=wall
        self.lock=threading.RLock();self.bindings=weakref.WeakKeyDictionary()
        self.providers={}
        self.points={};self.first_points={};self.failures={};self.discontinuities={};self.inflight=set()
        self.stopped=False;self.refresh_failures={};self.invalid_responses={};self.out_of_order={}

    def _current(self):
        try:return os.getpid()==self.source.pid and self.generation()==self.source.generation
        except Exception:return False

    def attach(self, rpc, chain):
        """Attach only to actual authenticated existing native controller types."""
        from .evidence_worker import RepairRPC
        from meme_machine.lanes.pons.provider_topology import PacedRpc
        from .governor import Governor
        if chain=='solana':
            _require(type(rpc) is RepairRPC and isinstance(rpc.governor,Governor)
                and rpc.endpoint==rpc.config.http_url,'head_solana_native_rpc_required')
            identity=rpc.config.identity
        elif chain=='pons':
            _require(isinstance(rpc,PacedRpc) and rpc.canonical_authority is True
                and rpc.provider_fingerprint is not None and rpc.shared_admission is not None
                and getattr(rpc,'_injected_transport',None) is None,
                'head_pons_canonical_native_rpc_required')
            identity=rpc.provider_fingerprint
        else:
            raise ValueError('head_chain')
        _require(_sha(identity,64),'head_provider_identity')
        with self.lock:
            _require(not self.stopped and self._current(),'head_source_changed_or_stopped')
            old=getattr(rpc,'market_head_observer',None)
            _require(old is None or old is self,'head_rpc_already_owned')
            _require(self.providers.get(chain,identity)==identity,'head_provider_changed')
            self.providers.setdefault(chain,identity)
            self.bindings[rpc]=(chain,identity,uuid.uuid4().hex)
            rpc.market_head_observer=self
        return rpc

    @staticmethod
    def _kind(chain, method, params):
        if chain=='solana' and method=='getSlot' and params==[dict(commitment='finalized')]:
            return 'solana_finalized'
        if (chain=='pons' and method=='eth_getBlockByNumber' and type(params) is list
                and len(params)==2 and params[0] in ('latest','finalized') and params[1] is False):
            return 'pons_'+params[0]
        return None

    def physical_response(self, rpc, method, params, result, *, started, completed):
        """Called only after validated physical JSON-RPC response completion.

        Malformed measurements never alter the native result or confer coverage.
        Cached return paths and custom/injected transports do not invoke this.
        """
        with self.lock:
            binding=self.bindings.get(rpc)
            if binding is None:return
            chain,identity,session=binding
            kind=self._kind(chain,method,params)
            if kind is None:return
            try:
                _require(not self.stopped and self._current(),'SOURCE_CHANGED_OR_STOPPED')
                _require(_number(started) and _number(completed) and started<=completed<=self.clock(),
                    'PHYSICAL_CLOCK_UNAVAILABLE')
                if chain=='solana':
                    from meme_machine.solana_provider_config import GENESIS
                    _require(getattr(rpc,'network_verified',False) is True
                        and rpc.config.identity==identity and rpc.endpoint==rpc.config.http_url,
                        'NETWORK_UNVERIFIED')
                    _require(type(result) is int and 0<=result<2**63,'HEAD_MALFORMED')
                    height=result;header_hash=None;header_time=None;network=GENESIS
                else:
                    from .robinhood import provider_authority as authority
                    _require(rpc.canonical_authority is True and rpc.chain_verified is True
                        and authority.fingerprint(rpc._endpoint)==identity
                        and rpc.provider_fingerprint==identity,'NETWORK_UNVERIFIED')
                    _require(type(result) is dict,'HEAD_MALFORMED')
                    height=_quantity(result.get('number'));header_time=_quantity(result.get('timestamp'))
                    header_hash=result.get('hash')
                    _require(type(header_hash) is str and re.fullmatch(r'0x[0-9a-fA-F]{64}',header_hash)
                        is not None,'HEAD_MALFORMED')
                    header_hash=header_hash.lower();network=authority.CHAIN_ID
                observed_wall=self.wall()
                _require(_number(observed_wall),'PHYSICAL_CLOCK_UNAVAILABLE')
                point=dict(application_commit=self.source.commit,application_tree=self.source.tree,
                    source_pid=self.source.pid,source_process_start_ticks=self.source.process_start_ticks,
                    source_generation=self.source.generation,provider_identity=identity,
                    network=network,method=method,commitment='finalized' if chain=='solana' else params[0],
                    rpc_session=session,request_started_monotonic=started,
                    physical_completed_monotonic=completed,physical_completed_wall=observed_wall-(self.clock()-completed),
                    height=height,header_hash=header_hash,header_timestamp=header_time,
                    acquisition='ACTUAL_NATIVE_PHYSICAL_RESPONSE')
                prior=self.points.get(kind)
                if prior and (completed<prior['physical_completed_monotonic'] or
                        started<prior['request_started_monotonic'] and height<=prior['height']):
                    # Concurrent native calls can complete out of request order.
                    # Keep the newer physical fact, without inventing a rollback.
                    self.out_of_order[kind]=self.out_of_order.get(kind,0)+1
                    return
                if prior and (height<prior['height'] or (chain=='pons' and height==prior['height']
                        and header_hash!=prior['header_hash'])):
                    self.discontinuities[kind]=self.discontinuities.get(kind,0)+1
                    raise ValueError('HEAD_OR_CLOCK_DISCONTINUITY')
                self.points[kind]=point
                if kind not in self.first_points:self.first_points[kind]=point
                self.failures.pop(kind,None)
            except Exception:
                # Fixed code only; never reflect params, provider body or error.
                self.failures[kind]='PHYSICAL_HEAD_UNAVAILABLE'
                self.invalid_responses[kind]=self.invalid_responses.get(kind,0)+1

    def snapshot(self, kind):
        _require(kind in ('solana_finalized','pons_latest','pons_finalized'),'head_kind')
        with self.lock:
            point=self.points.get(kind)
            now=self.clock();age=(now-point['physical_completed_monotonic'] if point else None)
            fresh=(self._current() and not self.stopped and point is not None
                and _number(age) and age<=FRESH_SECONDS and kind not in self.failures
                and not self.discontinuities.get(kind,0))
            return dict(state='OBSERVED' if fresh else 'UNAVAILABLE',kind=kind,
                sampled_at_monotonic=now if _number(now) else None,age_seconds=age if _number(age) else None,
                stale=(age>FRESH_SECONDS if _number(age) else None),
                discontinuities=self.discontinuities.get(kind,0),
                invalid_physical_responses=self.invalid_responses.get(kind,0),
                out_of_order_physical_responses=self.out_of_order.get(kind,0),
                failed_refreshes=self.refresh_failures.get(kind,0),
                failure_code=self.failures.get(kind),receipt=dict(point) if point else None,
                first_receipt=dict(self.first_points[kind]) if kind in self.first_points else None,
                collection_stopped=self.stopped,
                economic_arrival_count=None,canonical_coverage=False,normal_readiness=False,
                scope='AUTHENTICATED_PROVIDER_HEAD_NOT_ECONOMIC_WORKLOAD_OR_COMPLETION')

    def begin_refresh(self, chain, kind):
        with self.lock:
            if self.stopped or not self._current() or chain in self.inflight:
                return False
            if self.snapshot(kind)['state']=='OBSERVED':return False
            self.inflight.add(chain)
            return True

    def end_refresh(self, chain, kind, *, failed=False):
        with self.lock:
            self.inflight.discard(chain)
            if failed:
                self.failures[kind]='GOVERNED_HEAD_REFRESH_UNAVAILABLE'
                self.refresh_failures[kind]=self.refresh_failures.get(kind,0)+1

    def stop(self):
        with self.lock:self.stopped=True


class HeadRefresh:
    """One stale-only scheduled attempt; native clients own every physical retry.

    Call on an owned worker and join it on stop. An already admitted request
    drains under its original transport/deadline; this class never kills a
    thread, changes provider allowance, retries a 429 itself or resets debt.
    """
    def __init__(self, heads, chain, *, rpc, stopped, deadline, clock=time.monotonic):
        _require(type(heads) is MarketHeads and chain in ('solana','pons')
            and callable(stopped) and _number(deadline) and callable(clock),'head_refresh_contract')
        self.heads=heads;self.chain=chain;self.kind=('solana_finalized' if chain=='solana' else 'pons_latest')
        self.rpc=heads.attach(rpc,chain);self.stopped=stopped;self.deadline=deadline;self.clock=clock
        self._require_budget()
        self.next_due=0;self.lock=threading.Lock();self.rotate_pons=False

    @classmethod
    def pons(cls, heads, *, stopped, deadline, clock=time.monotonic):
        """Own the ordinary configured canonical session; retain native limits."""
        from meme_machine.lanes.pons.provider_topology import configured_rpc
        value=cls(heads,'pons',rpc=configured_rpc(),stopped=stopped,deadline=deadline,clock=clock)
        value.rotate_pons=True
        return value

    def _require_budget(self):
        import urllib.request
        from meme_machine.operational.bounded_provider import Budget,PhaseBudget
        opener=urllib.request.urlopen
        if self.chain=='pons':
            from meme_machine.lanes.pons import provider
            _require(provider.urlopen is opener,'head_original_budget_transport_required')
        _require(type(getattr(opener,'_mm_operational_budget',None)) in (Budget,PhaseBudget),
            'head_original_budget_transport_required')

    def step(self):
        # Nonblocking ownership prevents catch-up bursts/concurrent controllers.
        if not self.lock.acquire(blocking=False):return False
        accepted=False;failed=False
        try:
            now=self.clock()
            if self.stopped() or now>=self.deadline:
                self.heads.stop();return False
            if now<self.next_due:return False
            self._require_budget()
            if not self.heads.begin_refresh(self.chain,self.kind):return False
            accepted=True
            from meme_machine.operational.bounded_provider import head_read_bound
            with head_read_bound(min(self.deadline,now+8),self.stopped):
                self._request(now)
            _require(self.heads.snapshot(self.kind)['state']=='OBSERVED',
                     'head_refresh_physical_receipt_unavailable')
            return True
        except Exception:
            failed=True
            return False
        finally:
            if accepted:self.heads.end_refresh(self.chain,self.kind,failed=failed)
            # Schedule from completion after waits/failure, never replay missed
            # ticks in a burst. A fresh ordinary read can suppress the next one.
            if accepted:self.next_due=self.clock()+REFRESH_SECONDS
            if self.stopped() or self.clock()>=self.deadline:self.heads.stop()
            self.lock.release()

    def _request(self,now):
        if self.chain=='solana':
            from .provider_purchases import provider_work
            with provider_work('history_receipt',family='shared',consumer='history',purpose='diagnostics'):
                # Existing shared Governor, Budget and eight-second native
                # attempt; no position priority or direct request transport.
                self.rpc.call_delivered('getSlot',[dict(commitment='finalized')],2,
                    deadline=min(self.deadline,now+8),cancelled=self.stopped)
        else:
            if self.rotate_pons and (self.rpc.used>=self.rpc.limit or
                    self.rpc.counts['pons_evidence_head']>=self.rpc.per_scope):
                from meme_machine.lanes.pons.provider_topology import configured_rpc
                self.rpc=self.heads.attach(configured_rpc(),'pons')
            from meme_machine.lanes.pons.provider_admission import decision_work
            @decision_work(3)
            def request():
                # Fixed evidence scope avoids priority()'s monitor/exit
                # priority-zero names. Existing Admission remains authority.
                return self.rpc.call('eth_getBlockByNumber',['latest',False],scope='pons_evidence_head')
            # Native thread-local bound cannot change another decision's
            # client deadline or install a shared cancellation callback.
            with self.rpc.fallback_deadline(min(self.deadline,now+8)):
                request()

    def run(self):
        try:
            while not self.stopped() and self.clock()<self.deadline:
                self.step()
                remaining=min(.1,max(0,self.deadline-self.clock()))
                if remaining:time.sleep(remaining)
        finally:self.heads.stop()
