"""Enforcement for pump_pons_proof's published contract. No I/O on import.

Published modeled prices and legacy diagnostics have independent ledgers. A stop
inherits BaseException so native provider sanitizers cannot turn it into a retry.
"""
from collections import Counter, deque
from contextlib import contextmanager
from decimal import Decimal
import hashlib
import io
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

CONTRACT_PATH = Path(__file__).resolve().parents[2] / 'operational/forward-survivor/NEXT_PROOF.json'
LIMITS = {
 'consecutive_candidate_deadline_violations':2, 'cumulative_process_write_bytes':2147483648,
 'diagnostic_native_cu':4194304, 'diagnostic_rpc_cu':720000, 'http_response_bytes':134217728,
 'maximum_group_cpu_cores_30_second_average':1.8, 'maximum_log_range_blocks':10,
 'minimum_system_available_bytes':2147483648, 'native_inflight_shutdown_reserve_bytes':268435456,
 'native_stream_bytes':2147483648, 'output_stock_bytes':805306368, 'per_http_response_bytes':2000000,
 'physical_http_attempts':7200, 'position_deadline_violations':0, 'proof_group_rss_bytes':4294967296,
 'published_rpc_cu':720000, 'queue_capacity':64, 'robinhood_rpc_elements':1200, 'rpc_retries':0,
 'solana_rpc_elements':6000, 'sustained_queue_stop_depth':32, 'sustained_queue_stop_seconds':5,
 'total_diagnostic_cu':4914304, 'total_rpc_elements':7200,
}
CONTRACT_SHA256 = 'd258a12246128315e7516ff02fd65f4bc8de37845fb724564e77cd56f072c372'
TIMES = dict(kill_after_shutdown_seconds=30, maximum_startup_seconds=60, minimum_steady_seconds=180,
 shutdown_reserve_seconds=30, stop_new_work_at_seconds=270, term_after_shutdown_seconds=20, total_wall_seconds=300)
# Frozen independently of Governor, RepairRPC and certify.CU. A method absent
# from this read-only list has no dispatch authority. Contract's conservative
# getTokenLargestAccounts weight is 3000 (never the legacy diagnostic 20).
PRICE_SOURCE = 'https://www.alchemy.com/docs/reference/compute-unit-costs'
PUBLISHED = {
 'solana':dict(getGenesisHash=10,getSlot=20,getMultipleAccounts=20,getAccountInfo=10,
  getBlockTime=20,getTokenLargestAccounts=3000,getProgramAccounts=20,getProgramAccountsV2=20,
  getTransactionsForAddress=100,getTransaction=40,getBlock=40,getSignaturesForAddress=40,getSignatureStatuses=20),
 'robinhood':dict(eth_chainId=0,eth_blockNumber=10,eth_getBlockByNumber=20,eth_getBlockByHash=20,
  eth_getLogs=60,eth_getTransactionReceipt=20,eth_getCode=20,eth_call=26,eth_gasPrice=20,
  eth_getBalance=20,eth_getStorageAt=20,eth_getTransactionByHash=20,eth_getBlockReceipts=20,eth_callMany=20),
}
DIAGNOSTIC = {'solana':dict(PUBLISHED['solana'],getTokenLargestAccounts=20),
              'robinhood':{m:100 for m in PUBLISHED['robinhood']}}
HOSTS = {'solana-mainnet.g.alchemy.com':'solana','robinhood-mainnet.g.alchemy.com':'robinhood',
         'rpc.mainnet.chain.robinhood.com':'robinhood'}
STREAM_HOST = 'solana-mainnet.streaming.alchemy.com:443'
MAX_FRAME = 16*1024*1024


class CeilingReached(BaseException):
    def __init__(self, reason):self.reason=reason;super().__init__(reason)


class Contract:
    def __init__(self, body):
        self.body=body;self.limits=dict(body['limits']);self.time=dict(body['time'])
        self.sha256=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def load_contract(path=CONTRACT_PATH):
    try:
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError('duplicate_contract_field')
                result[key]=value
            return result
        with Path(path).open('rb') as source:raw=source.read(32769)
        if len(raw)>32768:raise ValueError('contract_size')
        body=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite_contract')))
        # Every published value is pinned. Description changes also need review;
        # old limit names cannot accidentally acquire dispatch authority.
        identity=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if identity!=CONTRACT_SHA256 or body.get('limits')!=LIMITS or body.get('time')!=TIMES:
            raise ValueError('incompatible_published_contract')
        if body['schema']!='forward-survivor-next-proof-v1' or body['mode']!='PAPER_READ_ONLY_ISOLATED':
            raise ValueError('contract_identity')
        for key in ('dispatch_allowed','deployment_allowed','paid_upgrade_allowed','production_epoch_access','production_service_restart_allowed'):
            if body[key] is not False:raise ValueError('contract_isolation')
        if body['authorization']!='NOT_GRANTED' or body['paused_operational_workloads']!={'meteora':0,'ramses':0}:
            raise ValueError('contract_authorization')
        for k,v in LIMITS.items():
            if type(body['limits'][k]) is not type(v):raise ValueError('contract_limit_type')
        for k,v in TIMES.items():
            if type(body['time'][k]) is not int:raise ValueError('contract_time_type')
        return Contract(body)
    except (OSError,KeyError,TypeError,json.JSONDecodeError) as error:
        raise ValueError('missing_or_malformed_contract') from None


def endpoint_family(endpoint):
    try:
        p=urlsplit(endpoint)
        if p.scheme!='https' or p.username or p.password or p.query or p.fragment or p.port not in (None,443):
            raise ValueError('unapproved_provider_endpoint')
        family=HOSTS[p.hostname]
        if p.hostname.endswith('.g.alchemy.com'):
            if not re.fullmatch(r'/v2/[A-Za-z0-9_-]+',p.path):raise ValueError('unapproved_provider_endpoint')
        elif p.path not in ('','/'):raise ValueError('unapproved_provider_endpoint')
        return family
    except (ValueError,KeyError,TypeError):raise ValueError('unapproved_provider_endpoint') from None


def validate_native_bindings(contract):
    from meme_machine.lanes.pons.pons_historical import FACTORY,LAUNCH,GRADUATION
    from meme_machine.runtime.operating_families import PAUSED_LANES
    if contract.body['exact_pons_factory_filter']!=dict(address=FACTORY,topics=[[LAUNCH,GRADUATION]]):
        raise ValueError('native_factory_contract_mismatch')
    if not {'meteora','ramses'}<=PAUSED_LANES.keys():raise ValueError('native_pause_contract_mismatch')


class Budget:
    def __init__(self, contract, out=None, *, clock=time.monotonic, started=None):
        self.contract=contract;self.limits=dict(contract.limits);self.time=dict(contract.time)
        self.out=out;self.clock=clock;self.started=clock() if started is None else started
        self.lock=threading.RLock();self.stop=threading.Event();self.admissions_stopped=threading.Event()
        self.reason=None;self.shutdown_at=None;self.ready_at=None;self.counts=Counter();self.methods=Counter()
        self.http_reserved=0;self.native_inflight=0;self.native_transports=Counter();self.native_uncertain=Counter();self.events=deque(maxlen=2048)
        self.dispatched=0;self.fake_dispatches=0;self.rpc_errors=Counter();self.billed_provider_cu=None

    def stop_work(self):
        with self.lock:
            self.admissions_stopped.set()
            if self.shutdown_at is None:self.shutdown_at=self.clock()

    def fail(self, reason):
        with self.lock:
            self.reason=self.reason or reason;self.stop_work();self.stop.set()
        raise CeilingReached(self.reason)

    def admission(self):
        if self.reason:raise CeilingReached(self.reason)
        if self.clock()-self.started>=self.time['total_wall_seconds']:self.fail('wall_time_ceiling')
        if self.clock()-self.started>=self.time['stop_new_work_at_seconds']:self.stop_work()
        if self.admissions_stopped.is_set():raise CeilingReached('admission_closed')

    def ready(self):
        with self.lock:
            if self.ready_at is not None:return
            if self.clock()-self.started>self.time['maximum_startup_seconds']:self.fail('startup_ceiling')
            self.ready_at=self.clock()

    def check_time(self):
        with self.lock:
            elapsed=self.clock()-self.started
            if elapsed>=self.time['total_wall_seconds']:self.fail('wall_time_ceiling')
            if self.ready_at is None and elapsed>=self.time['maximum_startup_seconds']:self.fail('startup_ceiling')
            if elapsed>=self.time['stop_new_work_at_seconds']:self.stop_work()

    def reserve_http(self, endpoint, calls, *, retry=0):
        with self.lock:
            self.admission()
            try:family=endpoint_family(endpoint)
            except ValueError:self.fail('unapproved_provider_endpoint')
            if retry!=0:self.fail('rpc_retries')
            if not isinstance(calls,list) or not 1<=len(calls)<=200:self.fail('rpc_batch_shape')
            names=[]
            for row in calls:
                if not isinstance(row,dict) or row.get('jsonrpc')!='2.0' or not isinstance(row.get('params'),list):self.fail('rpc_envelope')
                method=row.get('method')
                if method not in PUBLISHED[family] or method not in DIAGNOSTIC[family]:self.fail('unpriced_or_unapproved_method')
                if method=='eth_getLogs':
                    try:
                        q=row['params'][0]
                        if len(row['params'])!=1 or not isinstance(q,dict):raise ValueError()
                        if 'blockHash' in q:
                            if 'fromBlock' in q or 'toBlock' in q:raise ValueError()
                            span=1
                        else:
                            a,b=q['fromBlock'],q['toBlock']
                            if not (isinstance(a,str) and isinstance(b,str) and a.startswith('0x') and b.startswith('0x')):raise ValueError()
                            span=int(b,16)-int(a,16)+1
                        if not 1<=span<=self.limits['maximum_log_range_blocks']:raise ValueError()
                    except (KeyError,IndexError,TypeError,ValueError):self.fail('maximum_log_range_blocks')
                names.append(method)
            published=sum(PUBLISHED[family][m] for m in names)
            diagnostic=sum(DIAGNOSTIC[family][m] for m in names)
            additions=dict(total_rpc_elements=len(calls),physical_http_attempts=1,published_rpc_cu=published,
                           diagnostic_rpc_cu=diagnostic,total_diagnostic_cu=diagnostic)
            additions[family+'_rpc_elements']=len(calls)
            for key,n in additions.items():
                if self.counts[key]+n>self.limits[key]:self.fail(key)
            maximum=self.limits['per_http_response_bytes']
            if self.counts['http_response_bytes']+self.http_reserved+maximum>self.limits['http_response_bytes']:
                self.fail('http_response_reservation')
            self.counts.update(additions);self.methods.update(family+':'+m for m in names)
            self.http_reserved+=maximum
            exhausted=next((key for key in additions if self.counts[key]>=self.limits[key]),None)
            if exhausted:self.stop_work()
            self.events.append(dict(kind='http_attempt',at=self.clock()-self.started,family=family,methods=names,
                                    elements=len(calls),published_modeled_cu=published,diagnostic_cu=diagnostic))
            return HTTPReceipt(self,maximum,exhausted)

    def stream_open(self,transport):
        with self.lock:
            self.admission()
            if transport not in ('yellowstone','solana_websocket'):self.fail('unapproved_native_transport')
            # One acquisition + one pending frame for gRPC; recv + max_queue=2
            # for WS. This is a byte reservation, never unbilled delivery.
            reserve=MAX_FRAME*(3 if transport=='solana_websocket' else 2)
            if self.native_inflight+reserve>self.limits['native_inflight_shutdown_reserve_bytes']:
                self.fail('native_inflight_shutdown_reserve_bytes')
            # WebSocket upgrades and gRPC Subscribe HTTP/2 attempts are physical
            # HTTP attempts too, although they contain no JSON-RPC elements.
            if self.counts['physical_http_attempts']>=self.limits['physical_http_attempts']:self.fail('physical_http_attempts')
            self.counts['physical_http_attempts']+=1
            self.native_inflight+=reserve
            if self.counts['physical_http_attempts']>=self.limits['physical_http_attempts']:self.fail('physical_http_attempts')
            return reserve

    def stream_close(self,reserve,*,transport=None,unread_possible=False):
        with self.lock:
            self.native_inflight-=reserve
            if unread_possible:
                # SDK buffers can contain received messages not yet delivered to
                # the application. Never release them as free provider usage.
                self.native(transport,reserve,estimated=True)

    def native(self,transport,size,*,estimated=False):
        with self.lock:
            if transport not in ('yellowstone','solana_websocket') or type(size) is not int or size<0:self.fail('native_accounting_unavailable')
            # Charge frames even after admission closes: in-flight shutdown
            # delivery is never free. Reserve prevents reaching the hard limit.
            new=self.counts['native_stream_bytes']+size
            cu=(new+511)//512;delta=cu-self.counts['diagnostic_native_cu']
            self.counts['native_stream_bytes']=new;self.counts['diagnostic_native_cu']=cu
            self.counts['total_diagnostic_cu']+=delta
            (self.native_uncertain if estimated else self.native_transports)[transport]+=size
            if size>MAX_FRAME and not estimated:self.fail('native_frame_bound')
            for key in ('native_stream_bytes','diagnostic_native_cu','total_diagnostic_cu'):
                if self.counts[key]>self.limits[key]:self.fail(key)
            margin=self.limits['native_inflight_shutdown_reserve_bytes']
            # Stop one maximum acquisition before the reserve boundary. The
            # stopping frame itself is already received; it cannot be assumed
            # free or allowed to overshoot the 256 MiB shutdown headroom.
            if new>=self.limits['native_stream_bytes']-margin-MAX_FRAME:self.fail('native_shutdown_margin')
            if self.counts['total_diagnostic_cu']>=self.limits['total_diagnostic_cu']:self.fail('total_diagnostic_cu')

    def snapshot(self):
        with self.lock:
            return dict(counts=dict(self.counts),methods=dict(self.methods),http_reserved_bytes=self.http_reserved,
             native_transports=dict(self.native_transports),native_possible_unread_shutdown_bytes=dict(self.native_uncertain),
             native_known_delivered_bytes=sum(self.native_transports.values()),
             native_ceiling_ledger='known delivered payload plus conservative unobserved SDK shutdown reservations',
             native_inflight_reserved_bytes=self.native_inflight,
             published_modeled_solana_ws_cu=str(Decimal(self.native_transports['solana_websocket']+self.native_uncertain['solana_websocket'])*Decimal('.0002')),
             published_modeled_yellowstone_usd=str(Decimal(self.native_transports['yellowstone']+self.native_uncertain['yellowstone'])*Decimal(75)/Decimal(10**12)),
             published_method_prices=PUBLISHED,price_source=PRICE_SOURCE,
             conservative_contract_weight_overrides={'getTokenLargestAccounts':3000},
             actual_provider_billed_cu=self.billed_provider_cu,actual_provider_currency=None,
             accounting_basis='attempted RPC elements; separate physical HTTP/WS-upgrade/gRPC-Subscribe attempts; received payload plus conservative SDK tail reservations; TLS excluded',
             retries=0,real_provider_dispatches=self.dispatched,fake_provider_dispatches=self.fake_dispatches,
             reason=self.reason,admissions_stopped=self.admissions_stopped.is_set(),
             ready_elapsed=None if self.ready_at is None else self.ready_at-self.started,
             elapsed=self.clock()-self.started,shutdown_elapsed=None if self.shutdown_at is None else self.shutdown_at-self.started,limits=self.limits,time=self.time,contract_sha256=self.contract.sha256,
             events=list(self.events))


class HTTPReceipt:
    def __init__(self,budget,reserved,exhausted=None):self.budget=budget;self.reserved=reserved;self.received=0;self.closed=False;self.exhausted=exhausted
    def acquire(self,reader,n=-1):
        b=self.budget;pieces=[];remaining=n
        while remaining!=0:
            with b.lock:
                if b.reason:raise CeilingReached(b.reason)
                allowance=min(16384,self.reserved,remaining if remaining>0 else 16384)
                if allowance==0:b.fail('per_http_response_bytes')
            # A full response is never buffered before limiting. read1, where
            # available, returns one acquisition so streaming peers cannot hide
            # an indefinite read(n) within the 8-second socket timeout.
            raw=reader(allowance)
            if not isinstance(raw,bytes) or len(raw)>allowance:b.fail('unbounded_response_reader')
            with b.lock:
                self.received+=len(raw);self.reserved-=len(raw);b.http_reserved-=len(raw)
                b.counts['http_response_bytes']+=len(raw)
                if b.counts['http_response_bytes']>=b.limits['http_response_bytes']:b.fail('http_response_bytes')
                if self.received>=b.limits['per_http_response_bytes']:b.fail('per_http_response_bytes')
            if not raw:break
            pieces.append(raw)
            if remaining>0:remaining-=len(raw)
        return b''.join(pieces)
    def close(self):
        with self.budget.lock:
            if not self.closed:
                self.budget.http_reserved-=self.reserved;self.reserved=0;self.closed=True
                if self.exhausted:self.budget.fail(self.exhausted)


class QueueEvidence:
    """Events from real admissions/dispatch/completion, with monotonic deadlines.

    Wall strategy deadlines are converted once on admission. Their original
    value is retained; queueing and provider waits consume the same deadline.
    """
    def __init__(self,budget):
        self.budget=budget;self.lock=threading.RLock();self.pending={};self.running={};self.rows=deque(maxlen=2048)
        self.depths={};self.overloaded={};self.candidate_streak=0;self.completed=0;self.peak=0;self.violations=Counter()
        self.enqueued=0;self.dispatched=0;self.successful=0;self.first_completion=None;self.last_completion=None
        self.first_poll=None;self.last_poll=None;self.polls=0;self.finished_ids=set()
        self.successful_by_queue=Counter();self.normal_service_witness=None
    def occupancy(self,queue,depth):
        b=self.budget;now=b.clock()
        with self.lock:
            if not isinstance(depth,int) or depth<0:b.fail('queue_measurement_unavailable')
            self.depths[queue]=depth;self.peak=max(self.peak,depth)
            if depth>b.limits['queue_capacity']:b.fail('queue_capacity')
            if depth>=b.limits['sustained_queue_stop_depth']:
                self.overloaded.setdefault(queue,now)
                if now-self.overloaded[queue]>=b.limits['sustained_queue_stop_seconds']:b.fail('sustained_queue_overload')
            else:self.overloaded.pop(queue,None)
    def enqueue(self,identity,*,kind='work',deadline=None,queue='owner',original_deadline=None,enqueued=None,control=False):
        with self.lock:
            if not control:self.budget.admission()
            if identity in self.pending or identity in self.running:self.budget.fail('duplicate_scheduler_identity')
            row=dict(identity=identity,kind=kind,queue=queue,enqueued=self.budget.clock() if enqueued is None else enqueued,deadline=deadline,
                     original_wall_deadline=original_deadline,cancelled=False)
            self.pending[identity]=row;self.occupancy(queue,sum(r['queue']==queue for r in self.pending.values()))
            self.enqueued+=1
            return row
    def dispatch(self,identity):
        with self.lock:
            row=self.pending.pop(identity);row['dispatch']=self.budget.clock();row['queue_wait']=row['dispatch']-row['enqueued']
            self.running[identity]=row;self.occupancy(row['queue'],sum(r['queue']==row['queue'] for r in self.pending.values()))
            self.dispatched+=1
            self._deadline(row)
    def _deadline(self,row):
        if row.get('deadline') is not None and self.budget.clock()>row['deadline'] and not row.get('violated'):
            row['violated']=True;row['deadline_violation_at']=self.budget.clock();self.violations[row['kind']]+=1
            self.rows.append(dict(row,event='deadline_violation'))
            if row['kind']=='position':self.budget.fail('position_deadline_violation')
            if row['kind']=='candidate':
                self.candidate_streak+=1
                if self.candidate_streak>=self.budget.limits['consecutive_candidate_deadline_violations']:
                    self.budget.fail('consecutive_candidate_deadline_violations')
    def finish(self,identity,*,cancelled=False,error=None):
        with self.lock:
            row=self.running.pop(identity,None) or self.pending.pop(identity,None)
            if row is None:self.budget.fail('completion_without_admission')
            self._deadline(row);row.update(completed=self.budget.clock(),cancelled=cancelled,error=error)
            self.completed+=1;self.rows.append(row)
            self.finished_ids.add(identity)
            if not cancelled and error is None:
                self.successful+=1;self.first_completion=self.first_completion if self.first_completion is not None else row['completed']
                self.last_completion=row['completed']
                self.successful_by_queue[row['queue']]+=1
            if row['kind']=='candidate':
                # An overdue cancellation is still a violation. Incomplete,
                # failed and cancelled work cannot reset the completed streak.
                if not row.get('violated') and not cancelled and error is None:self.candidate_streak=0
                if self.candidate_streak>=self.budget.limits['consecutive_candidate_deadline_violations']:
                    self.budget.fail('consecutive_candidate_deadline_violations')
            self.occupancy(row['queue'],sum(r['queue']==row['queue'] for r in self.pending.values()))
    def poll(self):
        with self.lock:
            now=self.budget.clock();self.first_poll=now if self.first_poll is None else self.first_poll
            self.last_poll=now;self.polls+=1
            for queue,depth in list(self.depths.items()):self.occupancy(queue,depth)
            for row in list(self.pending.values())+list(self.running.values()):self._deadline(row)
            if (not self.budget.admissions_stopped.is_set() and not self.pending and not self.overloaded
                and self.successful>=2 and self.last_completion-self.first_completion>=5
                and self.last_poll-self.first_poll>=5 and all(self.successful_by_queue[q] for q in self.depths)):
                self.normal_service_witness=dict(at=now,successful_completions=self.successful,
                    completed_by_queue=dict(self.successful_by_queue),pending=0,running=len(self.running))
    def scheduler_snapshot(self,jobs,*,queue='acquisition',source_now=None,claimed=None):
        # Durable native job identities/timestamps, not invented dispatch clocks.
        with self.lock:
            now=self.budget.clock();wall=time.time() if source_now is None else source_now
            for job in sorted(jobs,key=lambda r:(r['deadline'],r.get('created',r.get('created_at',wall)),r['id'])):
                identity=queue+':'+job['id'];state=job['status']
                terminal=state in ('complete','failed','deadline_missed','cancelled')
                known=identity in self.pending or identity in self.running
                if identity in self.finished_ids:continue
                if not known and terminal:
                    # A job can fail its native deadline inside plan()/claim()
                    # before any subsequent census sees it pending. Preserve
                    # that violation rather than erase a disposed candidate.
                    created=job.get('created',job.get('created_at',wall))
                    self.enqueue(identity,kind='position' if job.get('priority',3)<=1 else 'candidate',
                        deadline=now+job['deadline']-wall,queue=queue,original_deadline=job['deadline'],
                        enqueued=now+created-wall,control=True)
                    self.finish(identity,cancelled=state!='complete',error=job.get('error'));continue
                if not known and not terminal:
                    created=job.get('created',job.get('created_at',wall))
                    self.enqueue(identity,kind='position' if job.get('priority',3)<=1 else 'candidate',
                        deadline=now+job['deadline']-wall,queue=queue,original_deadline=job['deadline'],
                        enqueued=now+created-wall,control=True)
                if known and terminal:self.finish(identity,cancelled=state!='complete',error=job.get('error'))
                elif identity in self.pending and (state=='active' or claimed==job['id']):self.dispatch(identity)
            self.poll()

    @contextmanager
    def work(self,identity,*,kind='work',wall_deadline=None,queue='candidates'):
        deadline=None if wall_deadline is None else self.budget.clock()+wall_deadline-time.time()
        self.enqueue(identity,kind=kind,deadline=deadline,queue=queue,original_deadline=wall_deadline);self.dispatch(identity)
        error=None
        try:yield
        except BaseException as exc:error=type(exc).__name__;raise
        finally:self.finish(identity,error=error)
    def snapshot(self):
        with self.lock:
            progress_span=0 if self.first_completion is None else self.last_completion-self.first_completion
            observation_span=0 if self.first_poll is None else self.last_poll-self.first_poll
            drained=(self.normal_service_witness is not None and self.successful>=2 and progress_span>=5 and observation_span>=5 and self.polls>=2
                     and not self.pending and not self.running and not self.overloaded)
            return dict(peak=self.peak,depths=dict(self.depths),sustained_since=dict(self.overloaded),
             pending=list(self.pending.values()),running=list(self.running.values()),completed=self.completed,
             deadline_violations=dict(self.violations),consecutive_candidate_violations=self.candidate_streak,
             events=list(self.rows),drain_proven=drained,drain_evidence=dict(enqueued=self.enqueued,
                 dispatched=self.dispatched,successful_completions=self.successful,polls=self.polls,
                 progress_span_seconds=progress_span,observation_span_seconds=observation_span,
                 completed_by_queue=dict(self.successful_by_queue),normal_service_witness=self.normal_service_witness,
                 criterion='multiple successful service events spanning at least five seconds, continuously polled; no remaining work'))
