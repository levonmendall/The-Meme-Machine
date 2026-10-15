import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from meme_machine.runtime.robinhood.provider_usage import snapshot


class ProviderUsageWalRaceTests(unittest.TestCase):
    def test_demand_writer_does_not_upgrade_a_deferred_read_transaction(self):
        import json
        from meme_machine.runtime.robinhood import provider_usage
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'provider.sqlite'
            db=sqlite3.connect(path);db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE logical_demand(endpoint TEXT,method TEXT,n INTEGER,PRIMARY KEY(endpoint,method))')
            db.commit();db.close()
            connect=sqlite3.connect;injected=[]
            class ConcurrentDDL(sqlite3.Connection):
                def execute(self,statement,*args,**kwargs):
                    value=super().execute(statement,*args,**kwargs)
                    if statement.startswith('CREATE TABLE IF NOT EXISTS logical_demand'):
                        # Reproduce a completion committed after schema read and
                        # before demand insertion. A deferred BEGIN upgrades its
                        # obsolete snapshot and raises SQLITE_BUSY immediately.
                        other=connect(path);other.execute('INSERT INTO logical_demand VALUES(?,?,?)',('other','eth_call',1));other.commit();other.close()
                        injected.append(True)
                    return value
            def opened(*args,**kwargs):return connect(*args,factory=ConcurrentDDL,**kwargs)
            with patch.object(provider_usage.sqlite3,'connect',opened):provider_usage.demand(path,'endpoint',['eth_call'])
            self.assertEqual(injected,[True])
            db=connect(path)
            try:self.assertEqual(db.execute("SELECT n FROM logical_demand WHERE endpoint='endpoint'").fetchone()[0],1)
            finally:db.close()

    def test_checkpointed_wal_disappearing_during_snapshot_is_zero_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'shared-robinhood-admission.sqlite'
            db=sqlite3.connect(path)
            db.executescript("""
                CREATE TABLE provider_usage(
                    endpoint TEXT,lane TEXT,metric TEXT,value REAL,
                    PRIMARY KEY(endpoint,lane,metric));
                CREATE TABLE queue(
                    id TEXT,endpoint TEXT,priority INTEGER,created REAL,deadline REAL);
                CREATE TABLE limits(
                    endpoint TEXT PRIMARY KEY,next_at REAL,cooldown REAL,interval REAL);
                INSERT INTO limits VALUES('endpoint',0,0,0.5);
            """)
            db.commit();db.close()

            original_exists=Path.exists
            original_stat=Path.stat
            def raced_exists(value):
                if str(value).endswith('-wal'):
                    return True
                return original_exists(value)
            def raced_stat(value,*args,**kwargs):
                if str(value).endswith('-wal'):
                    raise FileNotFoundError(str(value))
                return original_stat(value,*args,**kwargs)

            # Reproduces Run 375 deterministically: the old snapshot observed the
            # WAL, SQLite checkpointed/unlinked it, then stat() killed Pons.
            with patch.object(Path,'exists',raced_exists),patch.object(Path,'stat',raced_stat):
                result=snapshot(path,'endpoint')

            self.assertEqual(result['health']['wal_bytes'],0)
            self.assertGreater(result['health']['database_bytes'],0)


class ProviderDemandCallerTests(unittest.TestCase):
    """Offline caller/accounting coverage, not a replay of the readonly cause."""

    endpoint='https://robinhood-mainnet.g.alchemy.com/v2/SYNTHETIC_DEMAND_SECRET'

    def setUp(self):
        from meme_machine.lanes.pons import immutable_rpc
        from meme_machine.runtime.robinhood import provider_authority
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.environment=patch.dict(os.environ,{
            'MM_ROBINHOOD_READ_RPC_URL':self.endpoint,
            'MM_ROBINHOOD_STATE_DIR':self.temp.name,
            'MM_RUNTIME_LANE':'pons'},clear=True)
        self.environment.start();self.addCleanup(self.environment.stop)
        self.path=provider_authority.paths()['provider']
        cache_path=str(provider_authority.paths()['cache'])
        self.store=immutable_rpc.configured(cache_path)
        def close_fixture_store():
            with immutable_rpc._lock:
                self.assertIs(immutable_rpc._stores.pop(cache_path),self.store)
            self.store.db.close()
        self.addCleanup(close_fixture_store)
        self.clock=100.;self.lock=threading.Lock();self.requests=[];self.failed_headers=set()
        # Every HTTP boundary is replaced, with a second guard against accidental
        # network access through an unexpected caller.
        for target in ('socket.socket.connect','socket.getaddrinfo'):
            guard=patch(target,side_effect=AssertionError('offline_network_forbidden'))
            guard.start();self.addCleanup(guard.stop)
        http=patch('meme_machine.lanes.pons.provider.urlopen',side_effect=self.http)
        http.start();self.addCleanup(http.stop)
        from meme_machine.lanes.pons import pons_selective_acquisition as acquisition
        from meme_machine.lanes.pons.provider_topology import configured_rpc
        def configured(*args,**kwargs):
            rpc=configured_rpc(*args,**kwargs)
            rpc.shared_admission.clock=self.now
            rpc.shared_admission.sleep=self.advance
            return rpc
        factory=patch.object(acquisition,'configured_rpc',side_effect=configured)
        factory.start();self.addCleanup(factory.stop)

    def now(self):
        with self.lock:return self.clock

    def advance(self,seconds):
        with self.lock:self.clock+=seconds

    def http(self,request,**kwargs):
        from meme_machine.lanes.pons import CHAIN_ID
        payload=json.loads(request.data)
        with self.lock:
            self.requests.append(payload);wire_number=len(self.requests)
        # The initiated attempt must be durable before the HTTP boundary, even
        # when the fake response below reports a provider failure.
        db=sqlite3.connect(self.path)
        try:self.assertGreaterEqual(db.execute('SELECT COUNT(*) FROM transport_starts').fetchone()[0],wire_number)
        finally:db.close()
        def reply(row):
            method=row['method']
            if method=='eth_chainId':value=hex(CHAIN_ID)
            elif method=='eth_getBlockByHash':
                block_hash=row['params'][0]
                if block_hash in self.failed_headers:
                    return dict(jsonrpc='2.0',id=row['id'],error=dict(code=-32000,message='offline failure'))
                value=dict(hash=block_hash,number='0x1',timestamp='0x2')
            elif method=='eth_getCode':value='0x6000'
            else:raise AssertionError('unexpected_offline_method')
            return dict(jsonrpc='2.0',id=row['id'],result=value)
        result=[reply(row) for row in payload] if isinstance(payload,list) else reply(payload)
        return io.BytesIO(json.dumps(result).encode())

    def context(self,consumer):
        from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
        from meme_machine.runtime.provider_purchases import provider_work
        context=SelectiveEvidenceContext(self.endpoint)
        with provider_work('pons_'+consumer+'_qualification',family='pons',consumer=consumer):
            context.acquire(scope='pons_natural')
        return context

    def batch(self,context,consumer,calls):
        from meme_machine.runtime.provider_purchases import provider_work
        with provider_work('pons_'+consumer+'_qualification',family='pons',consumer=consumer):
            return context.batch(calls,'pons_natural')

    def test_concurrent_current_survivor_callers_record_demand_with_reader_and_shared_cache_hit(self):
        current=self.context('current');survivor=self.context('survivor')
        shared=('eth_getBlockByHash',['0xshared',False])
        calls=[(current,'current',[shared,('eth_getCode',['0xcurrent','latest'])]),
               (survivor,'survivor',[('eth_getBlockByHash',['0xsurvivor',False])])]
        # A retained readonly WAL snapshot of the same fixture overlaps both
        # real caller writes. This exercises a known role overlap without
        # claiming that the preserved readonly failure is reproduced.
        reader=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            reader.execute('BEGIN')
            self.assertEqual(reader.execute('SELECT SUM(n) FROM logical_demand').fetchone()[0],2)
            ready=threading.Barrier(2)
            def consume(item):
                ready.wait(timeout=5)
                return self.batch(*item)
            with ThreadPoolExecutor(max_workers=2) as workers:
                results=list(workers.map(consume,calls))
            self.assertEqual(results[0],[dict(hash='0xshared',number='0x1',timestamp='0x2'),'0x6000'])
            self.assertEqual(results[1],[dict(hash='0xsurvivor',number='0x1',timestamp='0x2')])
            self.assertEqual(reader.execute('SELECT SUM(n) FROM logical_demand').fetchone()[0],2)
        finally:reader.close()
        physical_before=len(self.requests)
        self.assertEqual(self.batch(survivor,'survivor',[shared]),[results[0][0]])
        self.assertEqual(len(self.requests),physical_before)
        telemetry=current.rpc.shared_admission.telemetry()
        self.assertEqual(telemetry['consumer_calls_by_method'],{
            'eth_chainId':2,'eth_getBlockByHash':3,'eth_getCode':1})
        self.assertEqual(telemetry['consumer_logical_calls'],6)
        self.assertEqual(telemetry['physical_http_requests'],4)
        self.assertEqual(telemetry['logical_rpc_calls'],5)
        self.assertEqual(telemetry['batch_transports'],2)
        self.assertEqual(telemetry['batch_members'],3)
        self.assertEqual(telemetry['unresolved_transport_attempts'],0)
        # Physical purchases retain each initiating consumer; a shared hit adds
        # demand without another purchase or completion.
        purchases={row['consumer']:row['physical_http_requests'] for row in telemetry['purchase_work']}
        self.assertEqual(purchases,{'current':2,'survivor':2})

    def test_existing_ledger_gains_covering_retention_indexes_without_rewriting_accounting(self):
        from meme_machine.lanes.pons.provider_admission import Admission
        self.context('current')
        indexes={'transport_starts':'usage_start_retention_seq',
                 'admissions':'usage_admission_retention_seq','transports':'usage_transport_retention_seq'}
        with sqlite3.connect(self.path) as db:
            for index in indexes.values():db.execute('DROP INDEX '+index)
            before={table:db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
                    for table in (*indexes,'provider_usage','limits','logical_demand')}
        Admission(self.path,self.endpoint,lane='pons',clock=self.now,sleeper=self.advance)
        with sqlite3.connect(self.path) as db:
            for table,index in indexes.items():
                plan=db.execute('EXPLAIN QUERY PLAN SELECT seq FROM '+table+
                    ' WHERE 1=1 ORDER BY seq DESC LIMIT 1 OFFSET 4095').fetchall()
                self.assertTrue(any('USING COVERING INDEX '+index in row[3] for row in plan),plan)
            for table,rows in before.items():
                self.assertEqual(db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall(),rows,table)
            for table in indexes:
                with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):
                    db.execute('DELETE FROM '+table)
                db.rollback()

    def test_failed_current_request_keeps_demand_and_recovers_without_caching_failure(self):
        from meme_machine.lanes.pons import BoundaryError
        current=self.context('current')
        call=('eth_getBlockByHash',['0xfailure',False])
        self.failed_headers.add('0xfailure')
        with self.assertRaisesRegex(BoundaryError,'provider_rpc_-32000'):
            self.batch(current,'current',[call])
        telemetry=current.rpc.shared_admission.telemetry()
        self.assertEqual(telemetry['consumer_logical_calls'],2)
        self.assertEqual(telemetry['physical_http_requests'],2)
        self.assertEqual(telemetry['logical_rpc_calls'],2)
        self.assertEqual(telemetry['sanitized_failures'],{'provider_rpc_-32000':1})
        self.assertEqual(telemetry['retries'],0)
        self.assertEqual(telemetry['unresolved_transport_attempts'],0)
        key=current.rpc.evidence_reuse.key(*call)
        self.assertIsNone(self.store.get(current.rpc.evidence_reuse.domain,key))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM flights').fetchone()[0],0)
        db=sqlite3.connect(self.path)
        try:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM queue').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM queue_meta').fetchone()[0],0)
        finally:db.close()
        self.failed_headers.clear()
        expected=[dict(hash='0xfailure',number='0x1',timestamp='0x2')]
        self.assertEqual(self.batch(current,'current',[call]),expected)
        physical_before=len(self.requests)
        self.assertEqual(self.batch(current,'current',[call]),expected)
        self.assertEqual(len(self.requests),physical_before)
        telemetry=current.rpc.shared_admission.telemetry()
        self.assertEqual(telemetry['consumer_calls_by_method'],{'eth_chainId':1,'eth_getBlockByHash':3})
        self.assertEqual(telemetry['consumer_logical_calls'],4)
        self.assertEqual(telemetry['physical_http_requests'],3)
        self.assertEqual(telemetry['logical_rpc_calls'],3)
        self.assertEqual(telemetry['sanitized_failures'],{'provider_rpc_-32000':1})
        self.assertEqual(telemetry['unresolved_transport_attempts'],0)

    @staticmethod
    def telemetry_totals(context):
        """Preserved reporting path used as the exact operation-count baseline."""
        telemetry=context.telemetry()
        sessions=list(telemetry.get('completed_sessions',[]))
        if telemetry.get('current_session'):sessions.append(telemetry['current_session'])
        if not sessions:return (0,0)
        if any('logical_requests' not in row or 'transport_requests' not in row for row in sessions):return (None,None)
        return (sum(row['logical_requests'] for row in sessions),
            sum(row['physical_http_requests'] for row in sessions)
            if all('physical_http_requests' in row for row in sessions) else None)

    def test_provider_totals_avoids_full_endpoint_snapshot_and_repeated_schedule_reads(self):
        from collections import Counter
        from meme_machine.runtime.robinhood.pons import provider_totals
        from meme_machine.runtime.robinhood import provider_usage
        context=self.context('current')
        connect=sqlite3.connect;read_bytes=Path.read_bytes;read_text=Path.read_text
        requests_before=len(self.requests)

        def measured(function):
            counts=Counter()
            class Counted(sqlite3.Connection):
                def execute(self,statement,*args,**kwargs):
                    counts['statements']+=1
                    if 'FROM provider_usage' in statement:counts['endpoint_snapshots']+=1
                    if 'FROM reuse_events' in statement:counts['cache_scans']+=1
                    return super().execute(statement,*args,**kwargs)
            def opened(*args,**kwargs):
                counts['connections']+=1
                kwargs.setdefault('factory',Counted)
                return connect(*args,**kwargs)
            def bytes_read(path):
                if path.name=='alchemy-cu-schedule.json':counts['schedule_reads']+=1
                return read_bytes(path)
            def text_read(path,*args,**kwargs):
                if path.name=='alchemy-cu-schedule.json':counts['schedule_reads']+=1
                return read_text(path,*args,**kwargs)
            with patch.object(provider_usage.sqlite3,'connect',opened), \
                    patch.object(Path,'read_bytes',bytes_read),patch.object(Path,'read_text',text_read):
                value=function(context)
            return value,counts

        original,baseline=measured(self.telemetry_totals)
        current,changed=measured(provider_totals)
        self.assertEqual(original,(1,1));self.assertEqual(current,original)
        self.assertEqual(baseline['endpoint_snapshots'],1)
        self.assertEqual(baseline['cache_scans'],1)
        self.assertGreaterEqual(baseline['connections'],2)
        self.assertGreaterEqual(baseline['schedule_reads'],16)
        self.assertEqual(changed,Counter())
        self.assertEqual(len(self.requests),requests_before)

    def test_provider_totals_reads_fresh_native_counters_without_changing_admission(self):
        from meme_machine.runtime.robinhood.pons import provider_totals
        context=self.context('current')
        self.assertEqual(provider_totals(context),(1,1))
        self.batch(context,'current',[('eth_getBlockByHash',['0xfresh',False])])
        # A local immutable hit raises demand without changing the legacy
        # current-session RPC counters or adding another HTTP start.
        self.batch(context,'current',[('eth_getBlockByHash',['0xfresh',False])])
        self.assertEqual(self.telemetry_totals(context),(2,2))
        with patch.object(context,'telemetry',side_effect=AssertionError('reporting_not_required')):
            self.assertEqual(provider_totals(context),(2,2))
        authority=context.rpc.shared_admission.telemetry()
        self.assertEqual(authority['consumer_logical_calls'],3)
        self.assertEqual(authority['physical_http_requests'],2)
        self.assertEqual(authority['unresolved_transport_attempts'],0)
        # Full health reporting remains independently available and fallible.
        with patch('meme_machine.runtime.robinhood.provider_usage.snapshot',
                   side_effect=RuntimeError('reporting_unavailable')):
            self.assertEqual(provider_totals(context),(2,2))
            with self.assertRaisesRegex(RuntimeError,'reporting_unavailable'):
                context.telemetry()

    def test_provider_totals_preserves_completed_session_rotation_and_unknown_fields(self):
        from meme_machine.runtime.robinhood.pons import provider_totals
        from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
        context=self.context('current')
        context.completed_sessions=[dict(logical_requests=i+1,transport_requests=i+2,
            physical_http_requests=i+3) for i in range(32)]
        context._rotate()
        self.assertEqual(len(context.completed_sessions),32)
        self.assertEqual(provider_totals(context),self.telemetry_totals(context))
        self.assertEqual(provider_totals(context),(529,591))
        for missing,expected in [('logical_requests',(None,None)),
                                 ('transport_requests',(None,None)),
                                 ('physical_http_requests',(529,None))]:
            with self.subTest(missing=missing):
                row=context.completed_sessions[0]
                value=row.pop(missing)
                try:self.assertEqual(provider_totals(context),expected)
                finally:row[missing]=value
        empty=SelectiveEvidenceContext(self.endpoint)
        self.assertEqual(provider_totals(empty),(0,0))

    def test_provider_totals_preserves_legacy_telemetry_and_explicit_none(self):
        from types import SimpleNamespace
        from meme_machine.runtime.robinhood.pons import provider_totals
        cases=[({},(0,0)),({'current_session':None},(0,0)),
            ({'current_session':dict(logical_requests=7,transport_requests=9,
                                    physical_http_requests=3)},(7,3)),
            ({'completed_sessions':[dict(logical_requests=7,transport_requests=9)]},(7,None)),
            ({'completed_sessions':[dict(physical_http_requests=3)]},(None,None))]
        for payload,expected in cases:
            with self.subTest(payload=payload):
                context=SimpleNamespace(telemetry=lambda value=payload:value)
                self.assertEqual(provider_totals(context),expected)
        payload={'current_session':dict(logical_requests=7,transport_requests=9,
                                        physical_http_requests=None)}
        context=SimpleNamespace(telemetry=lambda:payload)
        # An explicitly invalid counter must not silently turn into zero.
        with self.assertRaises(TypeError):provider_totals(context)


def readonly_fixture(source):
    """Real unprivileged SQLite failure; no attribution to the operating incident."""
    # The suite's root-owned Scratch parent is 0700. This tiny owned fixture
    # needs a traversable parent after dropping privileges, independent of TMPDIR.
    with tempfile.TemporaryDirectory(dir='/tmp') as temp:
        script='''
import json, os, pwd, runpy, sqlite3, sys, threading
from pathlib import Path
namespace=runpy.run_path(sys.argv[1])  # Load before dropping access to the checkout.
root=Path(sys.argv[2]);path=root/'provider.sqlite'
db=sqlite3.connect(path)
db.execute('CREATE TABLE logical_demand(endpoint TEXT,method TEXT,n INTEGER,PRIMARY KEY(endpoint,method))')
db.commit();db.close()
if os.geteuid()==0:
    try:actor=pwd.getpwnam('meme-machine')
    except KeyError:actor=pwd.getpwnam('nobody')
    os.chown(root,actor.pw_uid,actor.pw_gid);os.chown(path,actor.pw_uid,actor.pw_gid)
    os.setgroups([]);os.setgid(actor.pw_gid);os.setuid(actor.pw_uid)
assert os.geteuid()!=0, 'permission fixture must not bypass permissions'
path.chmod(0o400)
connect=sqlite3.connect;connections=[]
class Tracked(sqlite3.Connection):
    closed=False
    def close(self):
        super().close();self.closed=True
def opened(*args,**kwargs):
    db=connect(*args,factory=Tracked,**kwargs);connections.append(db);return db
sqlite3.connect=opened
try:
    namespace['demand'](path,'SYNTHETIC_ENDPOINT_SECRET',['SYNTHETIC_METHOD_SECRET','eth_call'])
except sqlite3.OperationalError as error:
    failure=dict(code=error.sqlite_errorcode,name=error.sqlite_errorname,
        diagnostic=getattr(error,'provider_demand_diagnostic',None),notes=getattr(error,'__notes__',[]))
else:raise AssertionError('readonly fixture unexpectedly wrote')
db=connect(path)
assert db.execute('SELECT COUNT(*) FROM logical_demand').fetchone()[0]==0
db.close()
assert len(connections)==1 and connections[0].closed
path.chmod(0o600)
namespace['demand'](path,'fixture',['eth_call'])
db=connect(path)
assert db.execute('SELECT endpoint,method,n FROM logical_demand').fetchall()==[('fixture','eth_call',1)]
db.close()
assert len(connections)==2 and all(db.closed for db in connections)
print(json.dumps(dict(failure=failure,uid=os.geteuid(),gid=os.getegid(),pid=os.getpid(),
    recovered_rows=1,closed_connections=len(connections))))
'''
        result=subprocess.run([sys.executable,'-c',script,str(source),temp],
            capture_output=True,text=True,timeout=15)
        if result.returncode:raise AssertionError(result.stderr)
        return json.loads(result.stdout)


class ProviderDemandDiagnosticTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='linux','unprivileged Linux permission fixture')
    def test_real_readonly_failure_preserves_connection_evidence_and_reopen_recovery(self):
        from meme_machine.runtime.robinhood import provider_usage
        result=readonly_fixture(provider_usage.__file__)
        failure=result['failure'];facts=failure['diagnostic']
        self.assertEqual((failure['code'],failure['name']),(sqlite3.SQLITE_READONLY,'SQLITE_READONLY'))
        self.assertEqual((facts['sqlite_errorcode'],facts['sqlite_errorname']),
                         (failure['code'],failure['name']))
        self.assertEqual(facts['phase'],'insert')
        self.assertEqual((facts['uid'],facts['gid'],facts['pid']),
                         (result['uid'],result['gid'],result['pid']))
        self.assertNotEqual(facts['uid'],0)
        self.assertEqual(facts['connection_requested_open_mode'],'readwrite_create')
        self.assertFalse(facts['connection_uri'])
        self.assertEqual(facts['journal_mode'],'delete')
        self.assertEqual(facts['query_only'],0)
        self.assertTrue(facts['in_transaction'])
        self.assertEqual(facts['files']['']['mode'],'0o400')
        self.assertFalse(facts['files']['']['writable_by_actor'])
        self.assertTrue(facts['parent']['writable_by_actor'])
        self.assertIn('inode',facts['files'][''])
        self.assertIn('readonly',facts['filesystem'])
        self.assertEqual(facts['database_list'][0][2],facts['state_path'])
        self.assertEqual(facts['files']['-wal'],{'errno':2})
        self.assertEqual(json.loads(failure['notes'][0].split('=',1)[1]),facts)
        self.assertNotIn('SYNTHETIC_ENDPOINT_SECRET',json.dumps(facts))
        self.assertNotIn('SYNTHETIC_METHOD_SECRET',json.dumps(facts))
        self.assertEqual((result['recovered_rows'],result['closed_connections']),(1,2))

    def test_diagnostic_failure_does_not_mask_original_error_or_leave_connection_open(self):
        from meme_machine.runtime.robinhood import provider_usage
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'provider.sqlite';original=sqlite3.OperationalError('fixture_failure')
            connect=sqlite3.connect;connections=[]
            class FailedInsert(sqlite3.Connection):
                closed=False
                def executemany(self,*args,**kwargs):raise original
                def close(self):super().close();self.closed=True
            def opened(*args,**kwargs):
                db=connect(*args,factory=FailedInsert,**kwargs);connections.append(db);return db
            with patch.object(provider_usage.sqlite3,'connect',opened), \
                    patch.object(provider_usage,'_demand_failure',side_effect=OSError('diagnostic_failure')):
                with self.assertRaises(sqlite3.OperationalError) as raised:
                    provider_usage.demand(path,'endpoint',['eth_call'])
            self.assertIs(raised.exception,original)
            self.assertTrue(connections[0].closed)

    def test_success_does_not_collect_failure_diagnostics(self):
        from meme_machine.runtime.robinhood import provider_usage
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(provider_usage,'_demand_failure',side_effect=AssertionError('success_probe')) as probe:
            path=Path(temp)/'provider.sqlite'
            provider_usage.demand(path,'endpoint',['eth_call','eth_call'])
            probe.assert_not_called()
            db=sqlite3.connect(path)
            try:self.assertEqual(db.execute('SELECT n FROM logical_demand').fetchone()[0],2)
            finally:db.close()

    def test_optional_probe_failure_keeps_original_error_and_essential_note(self):
        from meme_machine.runtime.robinhood import provider_usage
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'provider.sqlite';original=sqlite3.OperationalError('fixture_readonly')
            original.sqlite_errorcode=sqlite3.SQLITE_READONLY;original.sqlite_errorname='SQLITE_READONLY'
            connect=sqlite3.connect;connections=[]
            class FailedInsert(sqlite3.Connection):
                closed=False
                def executemany(self,*a,**kw):raise original
                def close(self):super().close();self.closed=True
            def opened(*a,**kw):
                db=connect(*a,factory=FailedInsert,**kw);connections.append(db);return db
            with patch.object(provider_usage.sqlite3,'connect',opened),\
                    patch.object(provider_usage,'_demand_failure_probes',side_effect=OSError('optional_probe_failure')):
                with self.assertRaises(sqlite3.OperationalError) as caught:provider_usage.demand(path,'endpoint',['eth_call'])
            self.assertIs(caught.exception,original);self.assertTrue(connections[0].closed)
            facts=original.provider_demand_diagnostic
            self.assertEqual((facts['sqlite_errorcode'],facts['sqlite_errorname'],facts['phase']),
                (sqlite3.SQLITE_READONLY,'SQLITE_READONLY','insert'))
            self.assertEqual(facts['requested_state_path'],str(path));self.assertEqual(facts['pid'],os.getpid())
            self.assertEqual(json.loads(original.__notes__[0].split('=',1)[1]),facts)

    def test_actual_lane_main_traceback_retains_demand_diagnostic_note(self):
        # Run the actual worker entrypoint/error-reporting boundary. The native
        # acquisition body is a tiny real SQLite readonly fixture, never a market
        # call, portfolio initialization or invocation of a live strategy.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'pons').mkdir();path=root/'provider.sqlite'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE logical_demand(endpoint TEXT,method TEXT,n INTEGER,PRIMARY KEY(endpoint,method))')
            db.commit();db.close()
            script='''
import sys,sqlite3
from pathlib import Path
from unittest.mock import patch
from operational.tests import network_guard
network_guard()
from meme_machine.operational import lane
from meme_machine.runtime.robinhood import provider_usage
root,path=sys.argv[1:];connect=sqlite3.connect
def readonly(*args,**kwargs):return connect(Path(path).as_uri()+'?mode=ro',uri=True)
def native(*args):
    with patch.object(provider_usage.sqlite3,'connect',readonly):
        provider_usage.demand(path,'SYNTHETIC_ENDPOINT_SECRET',['SYNTHETIC_METHOD_SECRET'])
sys.argv=['lane','--lane','pons','--state-root',root]
with patch.object(lane,'run_native',native),patch('meme_machine.operational.bounded_provider.install'):
    lane.main()
'''
            result=subprocess.run([sys.executable,'-c',script,str(root),str(path)],capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('attempt to write a readonly database',result.stderr)
            notes=[r for r in result.stderr.splitlines() if r.startswith('provider_demand_diagnostic=')]
            self.assertEqual(len(notes),1);facts=json.loads(notes[0].split('=',1)[1])
            self.assertEqual((facts['sqlite_errorcode'],facts['sqlite_errorname'],facts['phase']),
                (sqlite3.SQLITE_READONLY,'SQLITE_READONLY','insert'))
            self.assertEqual(facts['requested_state_path'],str(path));self.assertGreater(facts['pid'],0)
            self.assertNotIn('SYNTHETIC_ENDPOINT_SECRET',notes[0]);self.assertNotIn('SYNTHETIC_METHOD_SECRET',notes[0])
            self.assertFalse((root/'pons'/'health.json').exists())
            with sqlite3.connect(path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM logical_demand').fetchone()[0],0)


if __name__=='__main__':
    unittest.main()
