"""Actual anonymous IPC/kernel identities; root/unit/clock namespace simulated.

No fixture value grants host boot or market authority. Native fixture replay is
real; child acquisition completes before any provider/runtime constructor.
"""
from contextlib import closing
from copy import deepcopy
import hashlib
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from meme_machine.operational import normal_boot as boot
from meme_machine.operational import normal_boot_record as wire
from meme_machine.operational import normal_source_boot as source
from tests import test_normal_boot_context as fixtures
envelope=fixtures.envelope
rehash=fixtures.rehash


CHILD=r'''
import json,os,sys
from types import SimpleNamespace
from unittest.mock import patch
from operational.tests import network_guard
network_guard()
from meme_machine.operational import normal_boot as boot
from meme_machine.operational import normal_source_boot as source
fixture=json.loads(sys.stdin.readline())
locator,record=fixture['locator'],fixture['record']
fields='MainPID='+str(record['supervisor']['pid'])+'\nInvocationID='+record['supervisor']['invocation_id']+'\nActiveState=active\n'
try:
    with patch.object(source,'_read_record',return_value=(locator,record)), \
         patch.object(source,'_clock_sha256',return_value='e'*64), \
         patch.object(boot,'_source_identity',return_value=(record['application_commit'],record['application_tree'])), \
         patch.object(source.subprocess,'run',return_value=SimpleNamespace(stdout=fields.replace('\\n','\n'))):
        cap=source.accept_source_launch(int(sys.argv[1]))
    if fixture.get('revoke_before_entry'):
        sys.stdin.readline()
        import asyncio
        from meme_machine.runtime import evidence_worker
        revoked=dict(locator,state='REVOKED',record_sha256=None)
        with patch.object(source,'_read_record',return_value=(revoked,record)), \
             patch('meme_machine.operational.bounded_provider.install',side_effect=AssertionError('provider install')):
            asyncio.run(evidence_worker.main_async(normal_generation=cap))
    if fixture.get('expire_before_entry'):
        sys.stdin.readline()
        import asyncio
        from meme_machine.runtime import evidence_worker
        with patch.object(source,'_read_record',return_value=(locator,record)), \
             patch.object(source,'_clock_sha256',return_value='e'*64), \
             patch.object(source.time,'monotonic',return_value=record['not_after_monotonic']), \
             patch('meme_machine.operational.bounded_provider.install',side_effect=AssertionError('provider install')), \
             patch.object(evidence_worker,'Governor',side_effect=AssertionError('provider governor')), \
             patch.object(evidence_worker,'serve',side_effect=AssertionError('native state constructor')):
            asyncio.run(evidence_worker.main_async(normal_generation=cap))
    closed=False
    try:os.fstat(int(sys.argv[1]))
    except OSError:closed=True
    if fixture.get('run_native_source'):
        import asyncio
        from tests.test_normal_source_boot import run_native_fixture
        asyncio.run(run_native_fixture(cap))
    print(json.dumps(dict(identity_sha256=cap.identity_sha256,pid=os.getpid(),closed=closed,
        generation=cap.generation,has_funding_flag='funding_authority' in cap.identity())),flush=True)
    sys.stdin.readline()
except BaseException as error:
    print(type(error).__name__+':'+str(error),file=sys.stderr,flush=True)
    raise SystemExit(2)
'''


async def run_native_fixture(cap):
    """Actual native65-frame source fixture; market transports are offline."""
    from meme_machine.solana_evidence_service import ServiceState
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from meme_machine.solana_selective_source import SelectiveSource,install
    from tests import test_solana_source_drain as original
    from tests.test_solana_closure import NOW
    state=ServiceState(Path(cap.identity()['root'])/'shared/solana-evidence.sqlite',
        AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline_fixture_only'))
    try:
        history=install(state);history.clock=lambda:NOW;history.lifecycle.clock=lambda:NOW
        state.writer.clock=lambda:NOW
        harness=unittest.TestCase();harness.state=state;harness.history=history
        harness.source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64,stream_url='offline'),
            None,normal_generation=cap)
        harness.source.stop=asyncio.Event();harness.entered=asyncio.Event();harness.release=asyncio.Event()
        harness.quiet=lambda *args:original.SourceDrainTests.quiet(harness,*args)
        with patch.dict(os.environ,MM_MODE='PAPER',MM_OPERATIONAL_PHASE='continuous'):
            await original.SourceDrainTests.actual_run(harness)
    finally:state.close()


class NativeSourceLaunchTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.NativePrewriteReplayTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.record=self.case.record;self.locator=self.case.locator
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.record['boot_id']=self.record['boot_eligibility']['boot_id']=self.locator['boot_id']=boot_id
        self.record['supervisor']['start_ticks']=source._process_start(os.getpid())
        rehash(self.record['boot_eligibility'])
        self.locator['record_sha256']=hashlib.sha256(wire.canonical(self.record)).hexdigest()
        self.case.launch._locator=deepcopy(self.locator);self.case.launch._record=deepcopy(self.record)
        self.context=boot.consume_normal_boot(self.case.supervisor,cancelled=lambda:False)
        self.enterContext(patch.object(source,'_ISSUED_CONTEXT',None))
        self.enterContext(patch.object(source,'_clock_sha256',return_value='e'*64))

    def launch(self,channel,*,run_native_source=False,revoke_before_entry=False,expire_before_entry=False):
        env=dict(os.environ,MM_STATE_ROOT=str(self.case.root),
            MM_SOLANA_EVIDENCE_PLANE_DB=str(self.case.root/'shared/solana-evidence.sqlite'))
        child=subprocess.Popen([sys.executable,'-c',CHILD,str(channel.child_fd)],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,pass_fds=(channel.child_fd,),
            start_new_session=True,env=env)
        def cleanup():
            if child.poll() is None:child.kill()
            child.wait(timeout=5)
            for stream in (child.stdin,child.stdout,child.stderr):
                if stream is not None:stream.close()
        self.addCleanup(cleanup)
        child.stdin.write(json.dumps(dict(locator=self.locator,record=self.record,
            run_native_source=run_native_source,revoke_before_entry=revoke_before_entry,
            expire_before_entry=expire_before_entry))+'\n');child.stdin.flush()
        return child

    def test_actual_private_launch_peer_pid_start_run_and_one_shot_fd_are_bound(self):
        channel=source.SourceLaunch(self.context);child=self.launch(channel)
        value=channel.bind(child,deadline=time.monotonic()+5)
        row=json.loads(child.stdout.readline())
        self.assertEqual(row['identity_sha256'],wire.digest(value))
        self.assertEqual(value['source']['pid'],child.pid)
        self.assertEqual(value['source']['start_ticks'],source._process_start(child.pid))
        self.assertEqual(row['generation'],value['generation'])
        self.assertTrue(row['closed']);self.assertFalse(row['has_funding_flag'])
        self.assertEqual(value['unknown_historical_handlers'],2)
        self.assertEqual(value['launch']['record_sha256'],self.locator['record_sha256'])
        self.assertTrue(channel.closed)
        child.stdin.write('stop\n');child.stdin.flush();child.stdin.close()
        self.assertEqual(child.wait(timeout=5),0,child.stderr.read())
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'already_issued'):
            source.SourceLaunch(self.context)

    def test_wrong_epoch_on_real_parent_channel_cannot_ack_or_start_runtime(self):
        channel=source.SourceLaunch(self.context);child=self.launch(channel)
        send=source._send
        def changed(connected,value):
            value=deepcopy(value);value['launch']['epoch_id']='wrong-native-epoch';send(connected,value)
        with patch.object(source,'_send',side_effect=changed):
            with self.assertRaisesRegex(wire.NormalBootUnavailable,'channel_eof'):
                channel.bind(child,deadline=time.monotonic()+5)
        self.assertTrue(channel.closed);self.assertIsNone(channel.identity)
        self.assertEqual(child.wait(timeout=5),2)
        self.assertIn('source_child_instance',child.stderr.read())
        self.assertEqual(child.stdout.read(),'')

    def test_clock_failure_after_real_spawn_closes_both_channels_and_preserves_failure(self):
        channel=source.SourceLaunch(self.context);child=self.launch(channel)
        descriptors=(channel.parent.fileno(),channel.child.fileno())
        with patch.object(source,'_clock_sha256',side_effect=RuntimeError('fixed clock refusal')):
            with self.assertRaisesRegex(RuntimeError,'fixed clock refusal'):
                channel.bind(child,deadline=time.monotonic()+5)
        self.assertTrue(channel.closed)
        for fd in descriptors:
            with self.assertRaises(OSError):os.fstat(fd)
        self.assertEqual(child.wait(timeout=5),2)

    def test_actual_accepted_child_revocation_refuses_before_provider_constructor(self):
        channel=source.SourceLaunch(self.context);child=self.launch(channel,revoke_before_entry=True)
        channel.bind(child,deadline=time.monotonic()+5)
        child.stdin.write('revoke\n');child.stdin.flush();child.stdin.close()
        self.assertEqual(child.wait(timeout=5),2)
        error=child.stderr.read()
        self.assertIn('source_entry_instance_changed',error)
        self.assertNotIn('provider install',error)
        self.assertEqual(child.stdout.read(),'')

    def test_actual_accepted_child_expiry_refuses_before_provider_or_native_constructor(self):
        channel=source.SourceLaunch(self.context);child=self.launch(channel,expire_before_entry=True)
        channel.bind(child,deadline=time.monotonic()+5)
        child.stdin.write('cross original expiry\n');child.stdin.flush();child.stdin.close()
        self.assertEqual(child.wait(timeout=5),2)
        error=child.stderr.read()
        self.assertIn('source_entry_expired',error)
        for constructor in ('provider install','provider governor','native state constructor'):
            self.assertNotIn(constructor,error)
        self.assertEqual(child.stdout.read(),'')

    def test_actual_child_native_commits_have_root_provenance_and_dead_source_replay(self):
        channel=source.SourceLaunch(self.context);child=self.launch(channel,run_native_source=True)
        identity=channel.bind(child,deadline=time.monotonic()+5)
        row=json.loads(child.stdout.readline())
        self.assertEqual(row['identity_sha256'],wire.digest(identity))
        child.stdin.write('stop\n');child.stdin.flush();child.stdin.close()
        self.assertEqual(child.wait(timeout=5),0,child.stderr.read())
        import sqlite3
        path=self.case.root/'shared/solana-evidence.sqlite'
        raw_record=wire.canonical(self.record)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,isolation_level=None)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            before=db.total_changes
            with patch.object(wire,'_protected_bytes',return_value=(raw_record,())):
                value=source.validate_prewrite_generation(db,root=self.case.root,
                    source_inputs=self.record['boot_eligibility']['source_inputs'],unknown_historical_handlers=2)
            self.assertEqual(value['state'],'DRAINED')
            self.assertEqual(value['identity_sha256'],row['identity_sha256'])
            self.assertFalse(value['historical_handler_disposition_verified'])
            current=source.validate_current_generation(db.execute(
                'SELECT value FROM service_health WHERE key=?',(source.KEY,)).fetchone()[0])
            self.assertEqual(current['census']['queues']['scout'],dict(accepted=65,committed=65,pending=0))
            self.assertGreater(current['census']['pending_history'],0)
            self.assertEqual(db.total_changes,before)
            with patch.object(wire,'_protected_bytes',return_value=(raw_record+b' ',())):
                with self.assertRaisesRegex(wire.NormalBootUnavailable,'previous_generation_root_record'):
                    source.validate_prewrite_generation(db,root=self.case.root,
                        source_inputs=self.record['boot_eligibility']['source_inputs'],unknown_historical_handlers=2)


class SourceCurrentCensusTests(unittest.TestCase):
    def setUp(self):
        from meme_machine.solana_evidence_service import ServiceState
        from meme_machine.solana_provider_config import AlchemyEndpoint
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.state=ServiceState(self.root/'shared/solana-evidence.sqlite',
            AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline_fixture_only'))
        self.addCleanup(self.state.close)
        body=dict(state='RECOVERY_REQUIRED',terminal=True,accepted_handlers=2,settled_handlers=0,
            pending_handlers=2,unpreserved_sessions=0,all_accepted_committed=True,
            queues={name:dict(accepted=0,committed=0,pending=0) for name in ('control','scout','rolling','candidate')})
        self.raw=json.dumps(body)
        self.state.writer.db.execute("INSERT OR REPLACE INTO service_health(key,value) VALUES('source_drain',?)",(self.raw,))
        values,_=boot._source_inputs(self.state.writer.db)
        locator,record=envelope()
        self.value=dict(schema='normal-source-subcap-v1',launch=source._launch_identity(record,locator['record_sha256']),
            source={'pid':os.getpid(),'start_ticks':source._process_start(os.getpid())},
            generation='d'*32,native_clock_sha256='e'*64,root=str(self.root),source_inputs=values,
            unknown_historical_handlers=2,issued_monotonic=time.monotonic(),
            not_after_monotonic=time.monotonic()+30)
        source._packet(self.value)
        # Namespace-only mechanics use an explicit acquired-cap premise. The
        # actual IPC acquisition is exercised by NativeSourceLaunchTests.
        self.cap=source.NativeSourceGeneration(self.value,_issuer=source._ISSUER)

    def census(self,*,terminal=False,pending=0):
        import asyncio
        from meme_machine.solana_source_drain import HandlerLedger
        ledger=HandlerLedger(self.cap.generation)
        if pending:
            async def interrupted():
                identity=ledger.accept('offline-stream','offline-session','yellowstone','pump','slot',time.time())
                ledger.fail(identity,asyncio.CancelledError())
            asyncio.run(interrupted())
        snapshot=ledger.snapshot()
        return dict(state='RECOVERY_REQUIRED' if pending else ('DRAINED' if terminal else 'RUNNING'),
            terminal=terminal,source_pid=os.getpid(),run_identity=self.cap.generation,
            accepted_handlers=snapshot['accepted'],settled_handlers=snapshot['returned'],pending_handlers=pending,
            handler_accounting=snapshot,closed_sessions=0,pending_history=0,pending_proofs=0,
            unpreserved_sessions=0,all_accepted_committed=True,
            queues={name:dict(accepted=0,committed=0,pending=0) for name in ('control','scout','rolling','candidate')})

    def test_real_current_generation_drain_keeps_original_unknown_two_and_pins(self):
        self.cap.begin(self.state,self.census())
        self.cap.publish(self.state,self.census(terminal=True))
        raw=self.state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(source.KEY,)).fetchone()[0]
        value=source.validate_current_generation(raw)
        self.assertEqual(value['identity_sha256'],self.cap.identity_sha256)
        self.assertEqual(value['identity']['unknown_historical_handlers'],2)
        self.assertEqual(value['census']['pending_handlers'],0)
        self.assertEqual(self.state.writer.db.execute("SELECT value FROM service_health WHERE key='source_drain'").fetchone()[0],self.raw)
        self.assertNotIn('historical_handler_disposition_verified',value)

    def test_previous_unresolved_generation_is_not_reset_by_new_empty_run(self):
        self.cap.begin(self.state,self.census())
        self.cap.publish(self.state,self.census(terminal=True,pending=1))
        next_value=deepcopy(self.value);next_value['generation']='f'*32
        cap=source.NativeSourceGeneration(next_value,_issuer=source._ISSUER)
        body=self.census();body['run_identity']=cap.generation
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'previous_generation_unresolved'):
            cap.begin(self.state,body)

    def test_changed_original_unknowns_or_current_boundary_refuse_publication(self):
        self.cap.begin(self.state,self.census())
        self.state.writer.db.execute("UPDATE service_health SET value='changed' WHERE key='source_drain'")
        with self.assertRaisesRegex(Exception,'retained_boundary_changed'):
            self.cap.publish(self.state,self.census(terminal=True))

    def test_sequence_packet_stream_is_rejected_before_protocol(self):
        if not hasattr(socket,'SOCK_SEQPACKET'):return
        left,right=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        self.addCleanup(right.close)
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'anonymous_stream'):
            source._channel(left.detach())

    def test_partial_real_socket_progress_does_not_renew_absolute_receive_deadline(self):
        import struct
        left,right=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
        self.addCleanup(left.close);self.addCleanup(right.close)
        right.sendall(struct.pack('!I',4)+b'{')
        with patch.object(source.time,'monotonic',side_effect=(1.,1.,3.)):
            with self.assertRaisesRegex(wire.NormalBootUnavailable,'channel_deadline'):
                source._receive(left,deadline=2.)

    def test_direct_dictionary_cannot_issue_source_generation(self):
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'issuer'):
            source.NativeSourceGeneration(self.value)

    def test_rehashed_drain_cannot_fabricate_handler_or_queue_population(self):
        self.cap.begin(self.state,self.census())
        body=self.census(terminal=True)
        body['handler_accounting']['accepted']=1
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'handler_identity'):
            self.cap.publish(self.state,body)
        body=self.census(terminal=True);body['queues']['scout']['pending']=1
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'generation_drain'):
            self.cap.publish(self.state,body)


class NativeSourceDriverGenerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from tests import test_solana_source_drain as original
        from meme_machine.solana_selective_source import SelectiveSource,install
        from tests.test_solana_closure import NOW
        self.case=SourceCurrentCensusTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.state=self.case.state;self.history=install(self.state)
        self.history.clock=lambda:NOW;self.history.lifecycle.clock=lambda:NOW
        self.state.writer.clock=lambda:NOW
        self.source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64,stream_url='offline'),
            None,normal_generation=self.case.cap)
        self.source.stop=asyncio.Event();self.entered=asyncio.Event();self.release=asyncio.Event()
        self.actual_run=lambda **kwargs:original.SourceDrainTests.actual_run(self,**kwargs)
        self.quiet=lambda *args:original.SourceDrainTests.quiet(self,*args)
        self.enterContext(patch.dict(os.environ,MM_MODE='PAPER',MM_OPERATIONAL_PHASE='continuous'))

    def record(self):
        raw=self.state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(source.KEY,)).fetchone()[0]
        self.assertEqual(self.state.writer.db.execute("SELECT value FROM service_health WHERE key='source_drain'").fetchone()[0],self.case.raw)
        return source.validate_current_generation(raw)

    async def test_real_native_scout_commits_join_separate_normal_generation_with_old_two_untouched(self):
        await self.actual_run()
        value=self.record()
        self.assertEqual(value['census']['state'],'DRAINED')
        self.assertEqual(value['census']['queues']['scout'],dict(accepted=65,committed=65,pending=0))
        self.assertEqual(value['identity_sha256'],self.source.source_boot_identity_sha256)
        self.assertEqual(value['identity']['unknown_historical_handlers'],2)
        self.assertEqual(value['provider_identity'],self.state.fence.endpoint_identity)
        self.assertEqual(value['census']['pending_history'],self.history.db.execute(
            'SELECT count(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0])
        self.assertGreater(value['census']['pending_history'],0)

    async def test_real_native_commit_failure_retains_current_obligation_and_original_unknown_two(self):
        await self.actual_run(fail=True)
        value=self.record()
        self.assertEqual(value['census']['state'],'RECOVERY_REQUIRED')
        self.assertEqual(value['census']['queues']['scout'],dict(accepted=128,committed=0,pending=128))
        self.assertEqual(self.history.db.execute('SELECT count(*) FROM market_observations').fetchone()[0],0)

    async def test_real_unexpected_cancellation_remains_failed_even_after_all_scout_commits(self):
        await self.actual_run(startup='unexpected_cancel')
        value=self.record()
        self.assertTrue(value['census']['unexpected_cancellation'])
        self.assertEqual(value['census']['state'],'RECOVERY_REQUIRED')
        self.assertEqual(value['census']['queues']['scout']['pending'],0)


class SourceEntryRefusalTests(unittest.TestCase):
    def test_unissued_normal_source_refuses_before_provider_or_state_constructor(self):
        from meme_machine.runtime import evidence_worker
        with patch.dict(os.environ,MM_MODE='PAPER',MM_OPERATIONAL_PHASE='continuous',
                MM_PROVIDER_OPERATION_MODE='CONTINUOUS'), \
                patch('meme_machine.operational.bounded_provider.install',side_effect=AssertionError('provider install')), \
                patch.object(evidence_worker,'Governor',side_effect=AssertionError('governor writer')), \
                patch.object(evidence_worker,'serve',side_effect=AssertionError('native writer')):
            with self.assertRaisesRegex(wire.NormalBootUnavailable,'capability_required'):
                asyncio.run(evidence_worker.main_async())

    def test_submitted_or_source_ack_does_not_supply_native_economic_completion(self):
        # The actual Supervisor boundary must remain closed even if old health
        # is otherwise sufficient and the source capability has been accepted.
        from tests.test_continuous_paper import AdmissionTests
        from tests.test_position_continuation import healthy
        fixture=AdmissionTests();self.addCleanup(fixture.doCleanups)
        root,capital,now,service=fixture.service()
        health,portfolio,rss=healthy();health['providers'].pop('robinhood');health['lanes'].pop('pons')
        rows=[dict(scope='candidate:'+family,slot=100,updated=now,market_time=now)
            for family in ('pump','pumpswap')]
        health['providers']['evidence']['program_frontiers']=rows
        before=capital.ledger()
        with patch('meme_machine.operational.acceptance.observe',return_value=(health,portfolio,rss)), \
                patch('time.time',return_value=now):
            service.normal_tick();service.ready_since-=61
            for row in rows:row['slot']+=1
            service.normal_tick()
            self.assertTrue(service.provider_budget.usage()['new_risk_ready'])
            # Neither an object nor a source acknowledgment supplies the absent
            # native endpoint capability. This is a refusal fixture only.
            service.normal_boot=object();service.source_boot_generation={'source_ack':True}
            service.ready_since=time.monotonic()-61
            for row in rows:row['slot']+=1
            service.normal_tick()
        self.assertFalse(service.provider_budget.usage()['new_risk_ready'])
        self.assertIn('economic_generation_witness_missing',
            json.loads(service.provider_budget.snapshot()['provider_fault'])['reason'])
        self.assertIsNone(service.ready_since)
        self.assertEqual(capital.ledger(),before)
