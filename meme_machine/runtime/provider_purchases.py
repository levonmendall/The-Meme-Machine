"""Bounded operation attribution at existing transport boundaries; zero I/O.

    Physical attempts and logical consumers are separate. All CU prices are the
    frozen repository schedule, never invoices. No endpoint/params/body is kept.
"""
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import threading

OPERATIONS=(
    'pump_discovery','pump_current_qualification','pump_survivor_qualification','pump_held_protection',
    'pons_discovery','pons_current_qualification','pons_survivor_qualification','pons_held_protection',
    'scaling_requalification','history_receipt','recovery_restart','retries_duplicates','unattributed')
CONSUMERS=('discovery','current','survivor','history','recovery','shared','unknown')
FAMILIES=('pump','pons','shared','unknown')
PURPOSES=('discovery','qualification','held_protection','scaling_requalification',
          'history_receipt','recovery_restart','evidence_reconstruction','diagnostics','unknown')
_work=ContextVar('provider_purchase_work',default=None)
_transport=ContextVar('provider_purchase_transport',default=None)
_ledger_lock=threading.RLock()


def work_label(*,family='unknown',consumer='unknown'):
    active=_work.get()
    if active:
        return dict(active,family=family if active['family']=='unknown' else active['family'],
            consumer=consumer if active['consumer']=='unknown' else active['consumer'])
    return dict(operation='unattributed',family=family,consumer=consumer,purpose='unknown',origin_operation='unattributed')


@contextmanager
def provider_work(operation,*,family=None,consumer=None,purpose=None):
    if operation not in OPERATIONS:raise ValueError('provider_purchase_operation')
    parent=work_label()
    if operation.startswith(('pump_','pons_')):
        family=family or operation.split('_')[0]
        consumer=consumer or ('discovery' if operation.endswith('discovery') else
            'survivor' if 'survivor' in operation else 'current' if 'current' in operation else parent['consumer'])
        purpose=purpose or ('held_protection' if operation.endswith('held_protection') else
            'discovery' if operation.endswith('discovery') else 'qualification')
    label=dict(operation=operation,origin_operation=parent['origin_operation'] if _work.get() else operation,
        family=family or parent['family'],consumer=consumer or parent['consumer'],
        purpose=purpose or (operation if operation in PURPOSES else parent['purpose']))
    if label['family'] not in FAMILIES or label['consumer'] not in CONSUMERS or label['purpose'] not in PURPOSES:
        raise ValueError('provider_purchase_label')
    token=_work.set(label)
    try:yield
    finally:_work.reset(token)


def attributed_work(operation,**labels):
    def decorate(function):
        @wraps(function)
        def wrapped(*args,**kwargs):
            with provider_work(operation,**labels):return function(*args,**kwargs)
        return wrapped
    return decorate


class ProviderPurchases:
    """Fixed label/method domains; process-lifetime totals, no request archive."""
    def __init__(self,*,max_rows=256):
        if max_rows<1:raise ValueError('provider_purchase_row_bound')
        self.max_rows=max_rows
        from .cu import DEFAULT
        from .source_artifacts import REGISTRY
        import hashlib
        try:
            schedule=REGISTRY.get(DEFAULT)
            self.prices=dict(schedule['methods']);self.schedule_source=schedule['source']
            self.schedule_sha256=hashlib.sha256(DEFAULT.read_bytes()).hexdigest()
        except (OSError,ValueError,KeyError,TypeError):
            # Missing prices disable estimates, never a native provider read.
            self.prices={};self.schedule_source=None;self.schedule_sha256=None
        self.methods=frozenset(self.prices)|frozenset(
            ('getSlot','getBlock','getBlocks','getTransactionsForAddress','solana_websocket','solana_grpc','evm_websocket','unknown',
             'getMultipleAccounts','getProgramAccounts','getGenesisHash','getBlockTime','getTokenLargestAccounts','getSignaturesForAddress','getTransaction',
             'eth_call','eth_chainId','eth_blockNumber','eth_getBlockByNumber','eth_getBlockByHash','eth_getLogs',
             'eth_getTransactionReceipt','eth_getBlockReceipts','eth_getCode','eth_gasPrice','eth_getBalance','eth_getStorageAt','eth_getTransactionByHash'))
        self.rows={};self.lock=threading.RLock()

    def _method(self,method):return method if method in self.methods else 'unknown'
    def _row(self,label):
        if (label['operation'] not in OPERATIONS or label.get('origin_operation',label['operation']) not in OPERATIONS or label['family'] not in FAMILIES
                or label['consumer'] not in CONSUMERS or label['purpose'] not in PURPOSES):
            raise ValueError('provider_purchase_label')
        key=tuple(label[k] for k in ('operation','family','consumer','purpose'))+(label.get('origin_operation',label['operation']),)
        if key not in self.rows and len(self.rows)>=self.max_rows-1:
            key=('unattributed','unknown','unknown','unknown','unattributed')
        return self.rows.setdefault(key,Counter())

    def consumer(self,methods,*,cache_hit=None,shared=False,family='unknown',consumer='unknown'):
        label=work_label(family=family,consumer=consumer)
        with self.lock:
            row=self._row(label);row['logical_consumers']+=len(methods)
            for method in methods:row['consumer_method:'+self._method(method)]+=1
            if cache_hit is not None:row['cache_hits' if cache_hit else 'cache_misses']+=len(methods)
            if shared:row['shared_acquisition_consumers']+=len(methods)

    def started(self,label,methods,request_bytes,*,retry=0):
        with self.lock:
            row=self._row(label);row['physical_requests']+=1;row['request_bytes']+=request_bytes
            row['retry_requests']+=int(retry>0)
            for method in methods:row['purchased_method:'+self._method(method)]+=1

    def completed(self,label,response_bytes,*,failed=False):
        with self.lock:
            row=self._row(label);row['completed_requests']+=1;row['delivered_payload_bytes']+=response_bytes
            row['failed_requests']+=int(failed)

    def stream(self,kind,delivered_bytes,*,family,consumer='shared'):
        label=work_label(family=family,consumer=consumer)
        with self.lock:
            row=self._row(label);row['delivered_payload_bytes']+=delivered_bytes
            row['stream_messages']+=1;row['stream_type:'+self._method(kind)]+=1

    def snapshot(self):
        with self.lock:
            rows=[];totals=Counter()
            for key,counts in sorted(self.rows.items()):
                methods={k.split(':',1)[1]:v for k,v in counts.items() if k.startswith('purchased_method:')}
                priced={m:n*self.prices[m] for m,n in methods.items() if m in self.prices}
                unknown={m:n for m,n in methods.items() if m not in self.prices}
                unpriced_stream=counts.get('stream_messages',0)>0
                totals.update({k:v for k,v in counts.items() if ':' not in k})
                totals['known_estimated_cu']+=sum(priced.values())
                rows.append(dict(zip(('operation','family','consumer','purpose','origin_operation'),key),**dict(counts),
                    estimated_cu=None if unknown or unpriced_stream else sum(priced.values()),
                    known_estimated_cu=sum(priced.values()),unpriced_methods=unknown,
                    verified_billed_cu=None))
            complete=all(row['estimated_cu'] is not None for row in rows)
            return dict(schema_version=1,basis='process-lifetime initiated HTTP attempts; streams are delivered messages',
                operations=rows,totals=dict(totals,estimated_cu=totals['known_estimated_cu'] if complete else None),
                schedule_source=self.schedule_source,schedule_sha256=self.schedule_sha256,
                label_row_capacity=self.max_rows,
                verified_billed_cu=None,billing_status='UNMEASURED',
                stream_cu_status='UNPRICED; bytes do not imply a CU rate',
                retry_failure_overlay='subset of operation totals; never add twice',
                request_identity_status='not retained; exact duplicate requests require existing audit/captured records')


def ledger(instance):
    owner=getattr(instance,'read_pacer',getattr(instance,'pacer',instance))
    existing=getattr(owner,'purchase_accounting',None)
    if existing is None:
        with _ledger_lock:
            existing=getattr(owner,'purchase_accounting',None)
            if existing is None:owner.purchase_accounting=existing=ProviderPurchases()
    return existing


def account_transport(family):
    def decorate(function):
        @wraps(function)
        def wrapped(instance,*args,**kwargs):
            if family=='pump':
                body=args[-1];calls=body if isinstance(body,list) else [body]
                methods=[c.get('method','unknown') for c in calls]
            else:
                methods=[args[0]] if isinstance(args[0],str) else [c[0] for c in args[0]]
            current=dict(ledger=ledger(instance),label=work_label(family=family),methods=methods,
                retry=0 if function.__name__=='_http_batch' else getattr(instance,'retry_attempt',getattr(instance,'_purchase_retry_attempt',0)),
                started=False,response_bytes=0)
            token=_transport.set(current);failed=False
            try:return function(instance,*args,**kwargs)
            except BaseException:failed=True;raise
            finally:
                _transport.reset(token)
                if current['started']:current['ledger'].completed(current['label'],current['response_bytes'],failed=failed)
        return wrapped
    return decorate


def purchase_started(request_bytes=0):
    current=_transport.get()
    if current is not None and not current['started']:
        current['started']=True
        current['ledger'].started(current['label'],current['methods'],request_bytes,retry=current['retry'])


def purchase_received(response_bytes):
    current=_transport.get()
    if current is not None:current['response_bytes']+=response_bytes
