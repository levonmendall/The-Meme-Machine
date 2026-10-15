"""Prepared Robinhood 300-second proof. Default invocation is read-only preflight.

Execute only after separate explicit owner authorization. The original scout
contract stays byte-identical, including its ten-block ceiling. No subscriptions,
portfolio creation, production state, funding, deployment or service control.
"""
from collections import Counter, deque
from contextlib import contextmanager
from contextvars import ContextVar
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
PLAN=ROOT/'engineering/robinhood_scout/NEXT_VALIDATION.json'
PLAN_SHA256='89d7cbca347bcd1aa0246e37b3d7d1709348e686ab3d8d2bba83ff5b3e2b4e7b'
PUBLIC='rpc.mainnet.chain.robinhood.com'
CANONICAL='robinhood-mainnet.g.alchemy.com'
PER_RESPONSE=2_000_000  # Preserved native Rpc response bound.
_network=ContextVar('robinhood_proof_network',default=False)


class ProofStop(BaseException):pass


def contract():
    raw=PLAN.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PLAN_SHA256:raise ValueError('reviewed_proof_contract_changed')
    return json.loads(raw)


class Budget:
    def __init__(self, *, clock=time.monotonic):
        self.plan=contract();self.clock=clock;self.started=clock()
        self.counts=Counter();self.methods=Counter();self.lock=threading.RLock()
        self.reserved_bytes=0;self.reason=None;self.requests=[]
        from meme_machine.runtime.cu import DEFAULT
        self.weights=json.loads(DEFAULT.read_text())['methods']

    def fail(self,reason):
        self.reason=self.reason or reason
        raise ProofStop(self.reason)

    def time_check(self):
        if self.clock()-self.started>=self.plan['maximum_elapsed_seconds']:self.fail('maximum_elapsed_seconds')

    def reserve(self,endpoint,calls):
        from meme_machine.lanes.pons.provider import READ_METHODS
        with self.lock:
            self.time_check();p=urlsplit(endpoint)
            if p.scheme!='https' or p.hostname not in (PUBLIC,CANONICAL) or p.username or p.password or p.query or p.fragment:
                self.fail('unreviewed_endpoint')
            kind='alchemy' if p.hostname==CANONICAL else 'public'
            if not isinstance(calls,list) or not 1<=len(calls)<=50:self.fail('batch_shape')
            names=[];log_ranges=[]
            for call in calls:
                method=call.get('method');params=call.get('params')
                if method not in READ_METHODS or method not in self.weights or not isinstance(params,list):
                    self.fail('unpriced_or_unreviewed_method')
                if method=='eth_getLogs':
                    try:
                        q=params[0];span=int(q['toBlock'],16)-int(q['fromBlock'],16)+1
                        if len(params)!=1 or not 1<=span<=self.plan['maximum_getLogs_blocks_per_element']:
                            raise ValueError()
                        log_ranges.append(dict(first=int(q['fromBlock'],16),last=int(q['toBlock'],16)))
                    except (ValueError,KeyError,TypeError,IndexError):self.fail('maximum_getLogs_blocks_per_element')
                names.append(method)
            additions=dict(total_physical_http_attempts=1,total_logical_rpc_elements=len(calls))
            additions[kind+'_physical_http_attempts']=1
            if kind=='alchemy':
                additions['alchemy_logical_rpc_elements']=len(calls)
                additions['diagnostic_estimated_alchemy_cu']=sum(self.weights[m] for m in names)
            for key,value in additions.items():
                if self.counts[key]+value>self.plan['maximum_'+key]:self.fail('maximum_'+key)
            if self.counts['http_response_bytes']+self.reserved_bytes+PER_RESPONSE>self.plan['maximum_http_response_bytes']:
                self.fail('http_response_reservation')
            self.counts.update(additions);self.methods.update(kind+':'+m for m in names)
            self.reserved_bytes+=PER_RESPONSE
            row=dict(at=self.clock()-self.started,kind=kind,methods=names,elements=len(calls),log_ranges=log_ranges,
                     request_bytes=0,response_bytes=0,completed=False,latency_seconds=None)
            self.requests.append(row);return row

    def received(self,row,size):
        with self.lock:
            self.time_check()
            if row['response_bytes']+size>PER_RESPONSE:self.fail('native_response_capacity')
            if self.counts['http_response_bytes']+size>self.plan['maximum_http_response_bytes']:
                self.fail('maximum_http_response_bytes')
            row['response_bytes']+=size;self.counts['http_response_bytes']+=size

    def feed(self,size):
        with self.lock:
            self.time_check()
            if self.counts['sequencer_decoded_bytes']+size>self.plan['maximum_sequencer_decoded_bytes']:
                self.fail('maximum_sequencer_decoded_bytes')
            self.counts['sequencer_decoded_bytes']+=size

    def snapshot(self):
        elapsed=self.clock()-self.started
        recent=[r for r in self.requests if elapsed-10<=r['at']<=elapsed]
        by_category={}
        for row in self.requests:
            counts=by_category.setdefault(row.get('category','diagnostics'),Counter())
            counts['physical_http_attempts']+=1;counts['logical_rpc_elements']+=row['elements']
            counts['response_bytes']+=row['response_bytes']
            if row['kind']=='alchemy':counts['diagnostic_cu']+=sum(self.weights[m] for m in row['methods'])
        from meme_machine.runtime.cu import DEFAULT
        spec=json.loads(DEFAULT.read_text());throughput=dict(spec['methods'],**spec.get('throughput_overrides',{}))
        cu=sum(throughput[m] for row in recent if row['kind']=='alchemy' for m in row['methods'])
        return dict(counts=dict(self.counts),methods=dict(self.methods),requests=self.requests,
            work_categories={k:dict(v) for k,v in by_category.items()},
            rolling_10_seconds=dict(physical_http_rps=len(recent)/10,
                alchemy_diagnostic_throughput_cups=cu/10,verified_billed_cu=None),
            reason=self.reason,elapsed_seconds=elapsed,verified_billed_cu=None,
            provider_log_subscription_bytes=0,provider_log_subscriptions=0,
            sequencer_connected=False,
            byte_basis='HTTP application payload read; no sequencer/log WebSocket connected; excludes TLS/framing',
            original_contract_sha256=PLAN_SHA256)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):raise ProofStop('http_redirect_forbidden')


class Response:
    def __init__(self,raw,budget,row,deadline=None):
        self.raw=raw;self.budget=budget;self.row=row;self.closed=False
        self.deadline=budget.started+budget.plan['maximum_elapsed_seconds'] if deadline is None else deadline
    def read(self,n=-1):
        raw=bytearray();maximum=PER_RESPONSE-self.row['response_bytes']
        requested=maximum if n<0 else min(n,maximum)
        while len(raw)<requested:
            self.budget.time_check()
            if self.budget.clock()>=self.deadline:self.budget.fail('http_absolute_deadline')
            value=getattr(self.raw,'read1',self.raw.read)(min(8192,requested-len(raw)))
            self.budget.received(self.row,len(value));raw.extend(value)
            if not value:break
        if len(raw)==maximum and n>maximum:self.budget.fail('native_response_capacity')
        try:
            reply=json.loads(raw)
            if any(isinstance(r,dict) and r.get('error') for r in (reply if isinstance(reply,list) else [reply])):
                self.budget.fail('rpc_error_no_retry')
        except (ValueError,TypeError):self.budget.fail('rpc_response_shape')
        return bytes(raw)
    def close(self):
        if not self.closed:
            self.closed=True;self.raw.close()
            with self.budget.lock:
                self.budget.reserved_bytes-=PER_RESPONSE
                self.row.update(completed=True,latency_seconds=self.budget.clock()-self.budget.started-self.row['at'])
    def __enter__(self):return self
    def __exit__(self,*a):self.close()


@contextmanager
def transports(budget, *, opener=None, offline=False):
    from meme_machine.lanes.pons import provider
    opener=opener or build_opener(NoRedirect()).open
    def open_request(request,**kw):
        payload=json.loads(request.data);row=budget.reserve(request.full_url,payload if isinstance(payload,list) else [payload])
        from meme_machine.runtime.robinhood.provider_usage import _active
        from meme_machine.runtime.robinhood.provider_authority import safe_label
        active=_active.get()
        row.update(scope=safe_label(active['scope']) if active else 'diagnostics',
            category=active.get('category','diagnostics') if active else 'diagnostics')
        row['request_bytes']=len(request.data);budget.counts['http_request_bytes']+=len(request.data)
        remaining=budget.started+budget.plan['maximum_elapsed_seconds']-budget.clock()
        token=_network.set(True)
        try:
            timeout=min(float(kw.get('timeout',10)),remaining,10)
            raw=opener(request,timeout=timeout)
            return Response(raw,budget,row,budget.clock()+timeout)
        except Exception:budget.fail('http_failure_no_retry')
        finally:_network.reset(token)
    original_init=provider.Rpc.__init__
    def init(rpc,*a,**kw):
        if kw.get('retries',0)!=0:budget.fail('rpc_retries')
        kw['retries']=0;return original_init(rpc,*a,**kw)
    def audit(event,args):
        if event in ('socket.connect','socket.sendto') and args[0].family!=socket.AF_UNIX and (offline or not _network.get()):
            budget.fail('unmetered_socket')
    # Installed in the disposable proof worker only. A reused caller must use
    # the offline tests' patchable boundary, never install a permanent audit hook.
    if not offline:sys.addaudithook(audit)
    with patch.object(provider,'urlopen',open_request),patch.object(provider.Rpc,'__init__',init):yield


def environment(path):
    # Consume the protected file; return only the existing canonical authority.
    values={}
    from .identity import protected
    for line in protected(path).splitlines():
        if '=' in line and line.strip() and not line.lstrip().startswith('#'):
            name,value=line.split('=',1);values[name.strip()]=' '.join(shlex.split(value))
    if values.get('MM_MODE')!='PAPER':raise ValueError('paper_configuration_required')
    from meme_machine.runtime.robinhood.provider_authority import endpoint
    return {'MM_ROBINHOOD_READ_RPC_URL':endpoint(environ=values)}


def identity():
    def git(*args):return subprocess.check_output(['git','-C',str(ROOT),*args],text=True).strip()
    return dict(commit=git('rev-parse','HEAD'),dirty=bool(git('status','--porcelain')),
                original_contract_sha256=PLAN_SHA256)


def isolate(out,env):
    # No Production state path is inherited; neither funding nor native books
    # are constructed. Every provider/cache/history/journal belongs to this run.
    for key in list(os.environ):
        if key.startswith('MM_'):del os.environ[key]
    os.environ.update(env,MM_RUNTIME_LANE='pons',MM_ROBINHOOD_STATE_DIR=str(out/'rpc'),
        MM_PROVIDER_DB=str(out/'provider.sqlite'),MM_RPC_CACHE_DB=str(out/'cache.sqlite'),
        MM_PONS_CANDIDATE_PLANE=str(out/'candidates.sqlite'),MM_ENGINEERING_TMPDIR=str(out))


def workload(out,budget,*,stop_after=None):
    from meme_machine.lanes.pons import BoundaryError
    from meme_machine.lanes.pons.pons_selective_cohort import _discovery
    from meme_machine.lanes.pons.pons_natural_observation import MarketScout,_latest_header
    from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
    from meme_machine.lanes.pons.pons_history import PonsHistory
    from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
    from meme_machine.lanes.pons.pons_attempts import Attempts
    from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext,evaluate_candidate
    from meme_machine.lanes.pons.pons_selective_paper import STRATEGY_CAPITAL_QUOTE
    from meme_machine.runtime.robinhood.pons import Broker,durable_cache
    from meme_machine.lanes.pons.pons_selective_continuation import POLICY
    endpoint=os.environ['MM_ROBINHOOD_READ_RPC_URL']
    broker=Broker(out/'candidates.sqlite',POLICY)
    scout=MarketScout(broker.plane)
    survivor=object.__new__(Runtime);survivor.root=out;survivor.endpoint=endpoint;survivor.rpc=None
    survivor.history=PonsHistory(out/'history.sqlite',policy=POLICY_HASH)
    survivor.plane=broker.plane;survivor.scout=scout;survivor.attempts=Attempts(broker.plane);survivor.current=None
    from meme_machine.runtime.robinhood.provider_authority import fingerprint
    context=SelectiveEvidenceContext(endpoint,cache=durable_cache(broker.plane,fingerprint(endpoint)))
    cursor=None;rpc=None;tape=deque(maxlen=40_000);samples=[];comparisons=[];pool_comparisons=[];turns=0
    started=budget.clock()
    try:
        while budget.clock()-started<(budget.plan['maximum_elapsed_seconds']-10 if stop_after is None else stop_after):
            budget.time_check()
            if rpc is None or rpc.used>150:rpc=_discovery(endpoint)
            header=_latest_header(rpc);top=int(header['number'],16)
            if cursor is None:cursor=top-1
            end=min(top,cursor+40)
            if end>cursor:
                observed=scout.read_market(rpc,cursor+1,end,nominate=lambda e,at:broker.enqueue(e,now=at))
                tape.extend(observed);cursor=end
            # At most one claimed original Current deadline per turn. All other
            # identities stay in the durable native Broker, without a top-N cap.
            work=broker.pop()
            if work:
                start=time.monotonic()
                try:
                    result=evaluate_candidate(endpoint,work['event'],list(tape),
                        strategy_capital_quote=STRATEGY_CAPITAL_QUOTE,evidence_context=context,
                        evidence_observed_at=work['queued_at'],
                        evidence_observed_monotonic=start-max(0,time.time()-work['queued_at']))
                    broker.finish(work,result,time.monotonic()-start)
                except BoundaryError as exc:broker.failure(work,str(exc))
            survivor.discover();scout.read_pools(rpc,top)
            survivor._increment_candidates(survivor.history.rows(),top)
            # One short canonical public-coverage witness every 15 seconds.
            # It measures disagreement, never fabricates complete older history.
            if cursor is not None and (not comparisons or budget.clock()-started>=15*len(comparisons)):
                survivor._provider();first=max(scout.plane.checkpoint_read('pons_scout_enrollment')['first'],cursor-9)
                query=dict(fromBlock=hex(first),toBlock=hex(cursor),topics=[[scout.launch,scout.graduation,*scout.curve_topics]])
                witness=survivor.rpc.call('eth_getLogs',[query],scope='pons_scout_gap_witness')
                from meme_machine.lanes.pons.log_windows import LogWindows
                witness=LogWindows(endpoint,query)._validate(witness,first,cursor)
                stored=scout.plane.db.execute("SELECT body,hash FROM pons_scout_events WHERE kind IN ('launch','graduation','curve') "
                    'AND block>=? AND block<=? ORDER BY block,seq LIMIT 4097',(first,cursor)).fetchall()
                if len(stored)>4096:budget.fail('coverage_witness_resource_capacity')
                from meme_machine.runtime.journal import digest
                observed=[json.loads(body) for body,_ in stored]
                if any(digest(e)!=checksum for e,(_,checksum) in zip(observed,stored)):
                    budget.fail('scout_journal_corruption')
                canonical=survivor.rpc.call('eth_getBlockByNumber',[hex(cursor),False],scope='pons_scout_gap_witness')
                if canonical['hash']!=scout.plane.checkpoint_read('pons_scout_market_boundary')['hash']:
                    budget.fail('public_canonical_boundary_disagreement')
                def normalized(rows):
                    return {json.dumps({k:e[k] for k in ('blockHash','transactionHash','logIndex','address','topics','data')},sort_keys=True)
                            for e in rows}
                # Factory lookalikes are outside the strategy scope in both tapes.
                witness=[e for e in witness if e['topics'][0] in scout.curve_topics or e['address'].lower()==scout.factory]
                equal=normalized(witness)==normalized(observed)
                comparisons.append(dict(first=first,last=cursor,equal=equal,events=len(witness)))
                if not equal:budget.fail('public_canonical_disagreement')
                # Pool witnesses use the contiguous interval actually completed
                # by the shared scout, rather than borrowing the market cursor.
                pool_rows=scout.plane.db.execute('SELECT pool,cursor,graduation FROM pons_scout_pools '
                    'ORDER BY attempt,token LIMIT 64').fetchall()
                if pool_rows:
                    through=min(r[1] for r in pool_rows)
                    begin=max(through-9,max(r[2] for r in pool_rows))
                    if begin<=through:
                        ids=sorted({r[0] for r in pool_rows})
                        pool_query=dict(address=scout.manager,topics=[scout.activity_topics,ids],
                            fromBlock=hex(begin),toBlock=hex(through))
                        canonical_pools=survivor.rpc.call('eth_getLogs',[pool_query],scope='pons_scout_pool_gap_witness')
                        canonical_pools=LogWindows(endpoint,pool_query)._validate(canonical_pools,begin,through)
                        placeholders=','.join('?' for _ in ids)
                        stored_pools=scout.plane.db.execute("SELECT body,hash FROM pons_scout_events WHERE kind='pool' "
                            'AND block>=? AND block<=? AND subject IN ('+placeholders+') ORDER BY block,seq LIMIT 4097',
                            [begin,through,*ids]).fetchall()
                        if len(stored_pools)>4096:budget.fail('pool_witness_resource_capacity')
                        public_pools=[json.loads(body) for body,_ in stored_pools]
                        if any(digest(e)!=checksum for e,(_,checksum) in zip(public_pools,stored_pools)):
                            budget.fail('scout_pool_journal_corruption')
                        equal=normalized(canonical_pools)==normalized(public_pools)
                        pool_comparisons.append(dict(first=begin,last=through,pools=len(ids),
                            events=len(canonical_pools),equal=equal))
                        if not equal:budget.fail('public_canonical_pool_disagreement')
            from meme_machine.runtime.robinhood.provider_authority import paths
            from meme_machine.runtime.robinhood.provider_usage import snapshot as provider_snapshot
            try:governor=provider_snapshot(paths()['provider'],fingerprint(endpoint))
            except Exception:budget.fail('provider_usage_measurement_unavailable')
            samples.append(dict(elapsed_seconds=budget.clock()-started,cursor=cursor,head=top,
                cursor_lag_blocks=top-cursor,scout=scout.snapshot(),provider_governor=governor,
                current_immutable_cache=context.cache.telemetry(),
                current=broker.telemetry(),survivor_candidates=len(survivor.history.rows()),
                provider=survivor.rpc.telemetry() if survivor.rpc else None))
            turns+=1
            if stop_after is not None and turns>=2:break
            time.sleep(.5)
    finally:
        survivor.history.close();broker.close()
    return dict(status='INSUFFICIENT_SAMPLE',samples=samples,public_canonical_witnesses=comparisons,
        public_canonical_pool_witnesses=pool_comparisons,
        authentic_funded_position_samples=0,mature_survivor_samples=0,
        combined_latency_guard='combined_position_and_candidate_provider_latency_not_certified',
        guard_removed=False,full_market_coverage_certified=False,
        reason='technical forward proof cannot establish genuine funded-position latency or four-hour maturity')


def proc_sample(pid,out):
    fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
    cpu=(int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')
    files=[(p,p.stat().st_size) for p in out.rglob('*') if p.is_file()]
    stock=sum(size for _,size in files)
    return dict(at=time.monotonic(),cpu_seconds=cpu,rss_bytes=int(fields[21])*os.sysconf('SC_PAGE_SIZE'),
                artifact_bytes=stock,sqlite_wal_bytes=sum(size for p,size in files if p.name.endswith('-wal')),
                sqlite_database_bytes=sum(size for p,size in files if p.suffix in ('.sqlite','.db')),
                volume_available_bytes=os.statvfs('/mnt/volume_nyc1_1790918115030').f_bavail*
                    os.statvfs('/mnt/volume_nyc1_1790918115030').f_frsize)


def write_report(path,receipt,maximum):
    """Final diagnostics cannot overrun the unchanged artifact ceiling."""
    raw=json.dumps(receipt,separators=(',',':'))+'\n'
    stock=sum(p.stat().st_size for p in path.parent.rglob('*') if p.is_file() and p!=path)
    if stock+len(raw.encode())>maximum:
        receipt=dict(status='FAIL',reason='maximum_temporary_artifact_bytes',
                     diagnostics_too_large=True,guard_removed=False)
        raw=json.dumps(receipt,separators=(',',':'))+'\n'
        if stock+len(raw.encode())>maximum:raise ProofStop('maximum_temporary_artifact_bytes')
    path.write_text(raw);return receipt


def supervise(out,env,*,action=None,budget_factory=Budget):
    plan=budget_factory().plan;started=time.monotonic();pid=os.fork()
    if pid==0:
        os.setsid();isolate(out,env);budget=budget_factory();receipt={}
        def no_production(event,args):
            if event=='open' and isinstance(args[0],(str,bytes)):
                p=Path(os.fsdecode(args[0])).resolve()
                if str(p).startswith('/mnt/volume_nyc1_1790918115030/meme-machine-paper-v1'):
                    budget.fail('production_state_access')
            if event in ('subprocess.Popen','os.system','os.fork'):budget.fail('proof_child_process')
        sys.addaudithook(no_production)
        try:
            with transports(budget):receipt=(action or workload)(out,budget)
        except ProofStop as exc:receipt=dict(status='FAIL',reason=str(exc))
        except BaseException as exc:receipt=dict(status='FAIL',reason='proof_worker_'+type(exc).__name__)
        receipt['budget']=budget.snapshot()
        write_report(out/'worker-result.json',receipt,plan['maximum_temporary_artifact_bytes']);os._exit(0)
    samples=[];recent=deque();forced=None
    while True:
        done,status=os.waitpid(pid,os.WNOHANG)
        if done:break
        try:
            row=proc_sample(pid,out);samples.append(row);recent.append(row)
            while len(recent)>2 and recent[1]['at']<=row['at']-30:recent.popleft()
            if row['rss_bytes']>plan['maximum_process_group_rss_bytes']:forced='maximum_process_group_rss_bytes'
            if row['artifact_bytes']>plan['maximum_temporary_artifact_bytes']-2*1024*1024:forced='maximum_temporary_artifact_bytes'
            if row['volume_available_bytes']<plan['minimum_volume_free_bytes']:forced='minimum_volume_free_bytes'
            if len(recent)>1 and row['at']-recent[0]['at']>=30:
                rate=(row['cpu_seconds']-recent[0]['cpu_seconds'])/(row['at']-recent[0]['at'])
                if rate>plan['maximum_process_group_cpu_core_equivalent']:forced='maximum_process_group_cpu_core_equivalent'
        except (OSError,ValueError,IndexError):forced='resource_measurement_unavailable'
        if time.monotonic()-started>=plan['maximum_elapsed_seconds']:forced='maximum_elapsed_seconds'
        if forced:
            os.killpg(pid,signal.SIGKILL);_,status=os.waitpid(pid,0);break
        time.sleep(.1)
    path=out/'worker-result.json'
    receipt=json.loads(path.read_text()) if path.exists() else dict(status='FAIL',reason='missing_worker_result')
    receipt.update(independent_supervisor=True,forced_stop=forced,resources=samples,
        source=identity(),live_provider_validation_performed=True,original_contract_sha256=PLAN_SHA256,
        enforced_limits=plan,wider_range_comparison=budget_factory is not Budget,
        provider_capability_expansion=False,deployment_performed=False,production_epoch_access=False)
    if forced:receipt.update(status='FAIL',reason=forced)
    return write_report(out/'result.json',receipt,plan['maximum_temporary_artifact_bytes'])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='Run only after explicit owner authorization')
    parser.add_argument('--env-file',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--source-commit')
    args=parser.parse_args(argv);plan=contract();source=identity()
    if not args.execute:
        print(json.dumps(dict(status='PREFLIGHT_ONLY',execution_status='NOT_RUN',authorization='NOT_GRANTED',
            source=source,contract=plan,larger_capability_test_requires_separate_revised_range_review=True),indent=2));return 0
    if os.environ.get('CI') or not args.env_file or not args.output or args.source_commit!=source['commit'] or source['dirty']:
        parser.error('clean exact source, protected env file, explicit output and non-CI execution required')
    out=args.output.absolute()
    if out.is_symlink() or out.exists() or out.resolve()!=out or str(out).startswith('/mnt/'):
        parser.error('new isolated root-disk output required')
    # The ordinary engineering admission is applied before any output creation.
    from meme_machine.operational.artifact_storage import Scratch
    with Scratch() as scratch:
        scratch.check();out.mkdir(parents=True);result=supervise(out,environment(args.env_file))
        scratch.check();scratch.success=result['status']!='FAIL'
    print(json.dumps(dict(status=result['status'],result=str(out/'result.json'),reason=result.get('reason'))))
    return 0 if result['status']=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())
