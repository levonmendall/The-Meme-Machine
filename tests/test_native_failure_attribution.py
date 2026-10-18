"""Retain a bounded original cause without changing refusal/drain behavior."""
import asyncio
import ast
from contextlib import ExitStack, contextmanager
import copy
import errno
import io
import json
from pathlib import Path
import threading
import subprocess
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, call, patch

from meme_machine.operational import isolated_native_entry as entry
from meme_machine.operational import isolated_native_launcher as launcher
from meme_machine.operational import isolated_native_source as source
from tests import test_isolated_native_source as lifecycle_fixture

MODULE = 'meme_machine.lanes.pons.pons_selective_cohort'
MAPS = [('setgroups','deny'), ('uid_map','0 1001 1\n'), ('gid_map','0 1002 1\n')]


def failing_worker(body='raise PermissionError(13,"PRIVATE-body-path-SQL")'):
    scope={'__name__':MODULE}
    exec(compile('def fail():\n    '+body+'\n','/private/provider-credential.py','exec'),scope)
    return scope['fail']


class OriginalWorkerProjectionTests(unittest.TestCase):
    def test_actual_origin_errno_and_fixed_native_module_replace_no_exception_text(self):
        try:failing_worker()()
        except PermissionError as error:row=source._worker_failure_origin('pons',error)
        self.assertEqual(row,dict(worker='pons',error_type='PermissionError',source_module=MODULE,
            source_line=2,trace_complete=True,error_number=13))
        self.assertNotIn('PRIVATE',json.dumps(row))
        failure=source.ContainedNativeFailure('isolated_native_pons_failed')
        failure._worker_failures=(row,)
        value=entry._failure_details(failure,'native_lifecycle')
        self.assertEqual(value['worker_failures'],[row])
        self.assertEqual(value['boundary_code'],'isolated_native_pons_failed')
        self.assertEqual(value['failure_code'],'isolated_native_child_failed')

    def test_only_exact_known_class_and_allowlisted_boundary_code_are_published(self):
        from meme_machine.lanes.pons import BoundaryError
        for error in (BoundaryError('selective_tape_warmup_incomplete'),
                ValueError('PRIVATE'),type('PRIVATE_exception',(ValueError,),{})('PRIVATE')):
            row=source._worker_failure_origin('pons',error)
            self.assertEqual('boundary_code' in row,error.args==('selective_tape_warmup_incomplete',))
            self.assertNotIn('PRIVATE',json.dumps(row))
        self.assertEqual(source._worker_failure_origin('pons',error)['error_type'],'UNKNOWN')

    def test_foreign_module_bad_errno_and_hostile_attribute_cannot_replace_failure(self):
        class PrivateError(ValueError):
            @property
            def errno(self):raise RuntimeError('PRIVATE')
            @property
            def args(self):raise RuntimeError('PRIVATE')
        for error in (PrivateError('PRIVATE'),PermissionError('PRIVATE')):
            row=source._worker_failure_origin('pons',error)
            self.assertEqual(row['source_module'],None)
            self.assertNotIn('error_number',row)
            self.assertNotIn('PRIVATE',json.dumps(row))
        error=PermissionError('PRIVATE')
        for number in (None,0,-1,4096,True,'13'):
            error.errno=number
            self.assertNotIn('error_number',source._worker_failure_origin('pons',error))

    def test_traceback_walk_is_fixed_bounded_and_discloses_incompleteness(self):
        scope={'__name__':MODULE}
        exec(compile('def recurse(n):\n    if n:recurse(n-1)\n    else:raise ValueError("PRIVATE")\n',
            '/PRIVATE/path','exec'),scope)
        try:scope['recurse'](100)
        except ValueError as error:row=source._worker_failure_origin('pons',error)
        self.assertFalse(row['trace_complete'])
        self.assertEqual(row['source_module'],MODULE)
        self.assertIn(row['source_line'],(2,3))
        self.assertNotIn('PRIVATE',json.dumps(row))

    def test_malformed_reattached_carriers_never_publish_private_or_unbounded_fields(self):
        valid=dict(worker='pons',error_type='ValueError',source_module=MODULE,source_line=2,trace_complete=True)
        rows=[]
        for key,value in (('worker','PRIVATE'),('error_type','PRIVATE'),('source_module','PRIVATE'),
                ('source_line',True),('trace_complete',1),('error_number',True),('boundary_code','PRIVATE'),('raw','PRIVATE')):
            row=copy.deepcopy(valid);row[key]=value;rows.append((row,))
        rows.extend(([valid],(valid,valid),(valid,)*4))
        for carrier in rows:
            failure=source.ContainedNativeFailure('isolated_native_pons_failed');failure._worker_failures=carrier
            self.assertEqual(source.worker_failure_details(failure),[])
            self.assertNotIn('worker_failures',entry._failure_details(failure,'native_lifecycle'))
        foreign=ValueError('isolated_native_pons_failed');foreign._worker_failures=(valid,)
        self.assertEqual(source.worker_failure_details(foreign),[])


class OriginalWorkerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture=lifecycle_fixture.NativeLifecycleTests('test_actual_threads_concurrent_sizing_deny_and_join_before_complete')
        # This composed fixture has only synchronous cleanups and no separate
        # asyncio Runner. Use the synchronous TestCase cleanup dispatcher;
        # IsolatedAsyncioTestCase would silently record missing-Runner errors.
        self.fixture._callCleanup=unittest.TestCase._callCleanup.__get__(self.fixture)
        from meme_machine.runtime import stop
        original_stop=stop.requested
        await self.fixture.asyncSetUp()
        def cleanup():
            self.assertTrue(self.fixture.doCleanups())
            self.assertIs(stop.requested,original_stop)
        self.addCleanup(cleanup)

    async def test_real_worker_failure_keeps_original_classification_and_joined_partial(self):
        case=self.fixture
        with self.assertRaises(source.ContainedNativeFailure) as caught:
            await case.lifecycle(workers=[('pump',case.worker('pump')),('pons',failing_worker())])
        self.assertEqual(str(caught.exception),'isolated_native_pons_failed')
        value=json.loads((case.resources.root/'native-execution.json').read_text())
        self.assertEqual(value['worker_failures'],source.worker_failure_details(caught.exception))
        self.assertEqual(value['worker_failures'][0]['error_number'],13)
        self.assertTrue(value['source_joined'] and value['all_workers_joined'])
        self.assertEqual(value['status'],'FAILED');self.assertFalse(value['normal_readiness'])
        self.assertNotIn('PRIVATE',json.dumps(value))

    async def test_drain_failure_preserves_first_worker_origin_without_claiming_join(self):
        case=self.fixture;release=threading.Event();exited=threading.Event()
        def blocked():
            try:release.wait(2)
            finally:exited.set()
        try:
            with self.assertRaises(source.NativeOwnerDrainFailure) as caught:
                await source._run_lifecycle(resources=case.resources,stopped=case.stopped,
                    sizing_reader=case.reader(),source=case.source,
                    workers=[('pump',blocked),('pons',failing_worker())],
                    source_path=case.resources.root/'solana-evidence.sqlite',source_ready=case.source_ready,
                    seconds=.15,startup_seconds=1,shutdown_seconds=.02)
            value=caught.exception.receipt
            self.assertEqual(value['primary_failure_code'],'isolated_native_pons_failed')
            self.assertEqual(value['failure_code'],'isolated_native_shutdown_incomplete')
            self.assertEqual(value['worker_failures'][0]['error_number'],13)
            self.assertFalse(value['all_workers_joined']);self.assertEqual(value['status'],'FAILED')
            self.assertEqual(value['cleanup_disposition'],'OWNED_PROCESS_TERMINATION_REQUIRED')
        finally:
            release.set();self.assertTrue(await asyncio.to_thread(exited.wait,1))
            for thread in threading.enumerate():
                if thread.name=='isolated-native-pump':thread.join(timeout=1)
            await asyncio.sleep(.05)


@contextmanager
def launcher_setup(write):
    with ExitStack() as stack:
        boundary=launcher.boundary;kernel=Mock()
        stack.enter_context(patch.object(launcher,'_spec',side_effect=lambda value:value))
        stack.enter_context(patch.object(boundary,'Kernel',return_value=kernel))
        stack.enter_context(patch.object(launcher.os,'geteuid',return_value=1001))
        stack.enter_context(patch.object(launcher.os,'getegid',return_value=1002))
        stack.enter_context(patch.object(launcher.os,'getppid',return_value=99))
        stack.enter_context(patch.object(launcher.os,'listdir',return_value=['single']))
        stack.enter_context(patch.object(boundary,'_private',side_effect=lambda value,**kw:Path(value)))
        stack.enter_context(patch.object(boundary,'_scratch'))
        stack.enter_context(patch.object(launcher,'_verify_image'))
        stack.enter_context(patch.object(launcher,'_channel_descriptors'))
        stack.enter_context(patch.object(Path,'write_text',autospec=True,side_effect=write))
        fork=stack.enter_context(patch.object(launcher.os,'fork'))
        spec=dict(root='/fixed/root',work='/fixed/work',parent_pid=99,image='/fixed/image',
            manifest_sha256='a'*64,transport_fd=3,facts_fd=4)
        yield spec,kernel,fork


class OriginalLauncherMappingTests(unittest.TestCase):
    def test_each_original_map_actual_errno_stops_all_later_namespace_actions(self):
        for target,_ in MAPS:
            for number in (errno.EPERM,errno.EACCES):
                writes=[]
                def write(path,value):
                    writes.append((path.name,value))
                    if path.name==target:raise PermissionError(number,'PRIVATE')
                with self.subTest(target=target,number=number),launcher_setup(write) as (spec,kernel,fork):
                    with self.assertRaises(launcher.boundary.Blocked) as caught:launcher._setup(spec)
                    self.assertEqual(caught.exception.code,'namespace_'+target+'_refused')
                    self.assertEqual(caught.exception.number,number)
                    self.assertEqual(writes,MAPS[:[name for name,_ in MAPS].index(target)+1])
                    kernel.unshare.assert_called_once_with(launcher.boundary.USER)
                    kernel.mount.assert_not_called();fork.assert_not_called()

    def test_original_success_order_and_values_reach_same_second_unshare(self):
        writes=[];stop=RuntimeError('offline stop')
        with launcher_setup(lambda path,value:writes.append((path.name,value))) as (spec,kernel,fork):
            kernel.unshare.side_effect=[None,stop]
            with self.assertRaises(RuntimeError) as caught:launcher._setup(spec)
            self.assertIs(caught.exception,stop);self.assertEqual(writes,MAPS)
            self.assertEqual(kernel.unshare.call_args_list,[call(launcher.boundary.USER),
                call(launcher.boundary.MOUNT|launcher.boundary.NET|launcher.boundary.PID|launcher.boundary.IPC)])
            kernel.mount.assert_not_called();fork.assert_not_called()

    def test_fixed_launcher_main_reports_actual_errno_with_no_private_text_or_success(self):
        def write(path,value):raise PermissionError(errno.EACCES,'PRIVATE')
        output=io.StringIO()
        with launcher_setup(write) as (spec,kernel,fork),patch.object(launcher.sys,'argv',['launcher','--setup','{}']),\
                patch.object(launcher.json,'loads',return_value=spec),patch.object(launcher.sys,'stdout',output):
            self.assertEqual(launcher.main(),2)
        result=json.loads(output.getvalue())
        self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['error_number'],13)
        self.assertEqual(result['code'],'namespace_setgroups_refused')
        self.assertFalse(result['financial_authority']);self.assertFalse(result['actual_service_restrictions_verified'])
        self.assertNotIn('PRIVATE',output.getvalue());kernel.mount.assert_not_called();fork.assert_not_called()

    def test_invalid_errno_remains_original_failure_and_never_advances(self):
        for number in (None,0,-1,4096,True,'13'):
            error=PermissionError('PRIVATE');error.errno=number
            with self.subTest(number=number),launcher_setup(Mock(side_effect=error)) as (spec,kernel,fork):
                with self.assertRaises(PermissionError) as caught:launcher._setup(spec)
                self.assertIs(caught.exception,error)
                kernel.unshare.assert_called_once_with(launcher.boundary.USER)
                kernel.mount.assert_not_called();fork.assert_not_called()


class TargetedWorkflowContractTests(unittest.TestCase):
    def test_diagnostic_uses_distinct_check_and_only_original_cases_after_source_proof(self):
        root=Path(__file__).resolve().parents[1]
        text=(root/'.github/workflows/ci.yml').read_text()
        self.assertIn("name: ${{ github.event_name == 'workflow_dispatch' && inputs.validation == 'native-attribution' && 'native-attribution-only' || 'fast' }}",text)
        start=text.index('      - name: Attribute the two unchanged native failures only')
        block=text[start:text.index('      - name:',start+10)]
        self.assertIn("if: ${{ github.event_name == 'workflow_dispatch' && inputs.validation == 'native-attribution' }}",block)
        script=textwrap.dedent(block.split("python - <<'PYATTR'\n",1)[1].rsplit('          PYATTR',1)[0])
        tree=ast.parse(script)
        literals={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
            and node.targets[0].id in ('proof_modules','cases')}
        cases=literals['cases'];self.assertEqual(len(cases),2)
        self.assertIn('tests.test_future_pump_source_guard',literals['proof_modules'])
        self.assertIn('tests.test_native_failure_attribution',literals['proof_modules'])
        self.assertIn("if finished.code not in (None, 0):",script)
        self.assertIn("('CapInh', 'CapPrm', 'CapEff', 'CapAmb')",script)
        self.assertIn("resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, 4096), hard))",script)
        self.assertNotIn('sudo',script)
        expected=(('tests.test_isolated_native_launcher','DescriptorAndLifetimeTests',
            'test_actual_fixed_image_imports_spawn_SQLite_and_graceful_TERM_cleanup'),
            ('tests.test_isolated_native_kernel_validation','NativeKernelValidationTests',
            'test_actual_fixed_copied_main_all_four_native_adapters_and_shutdown'))
        self.assertEqual(cases,['.'.join(value) for value in expected])
        for module,owner,name in expected:
            relative=module.replace('.','/')+'.py'
            old=subprocess.check_output(['git','show','e0e6ad2957cbc38247a189715417fdf967072ede:'+relative],cwd=root)
            def body(raw):
                return next(case for cls in ast.parse(raw).body if isinstance(cls,ast.ClassDef) and cls.name==owner
                    for case in cls.body if isinstance(case,ast.FunctionDef) and case.name==name)
            self.assertEqual(ast.dump(body(old)),ast.dump(body((root/relative).read_bytes())))


class ParentCapacityChainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests import test_parent_native_transport as fixture
        await fixture.ParentNativeTransportTests.asyncSetUp(self)

    async def test_raw_control_bypass_retains_hard_server_capacity_and_closed_capability_guard(self):
        from tests import test_child_transport as fixture
        from tests.test_isolated_native_resources import authenticated,receipt
        from meme_machine.operational.child_transport import ChildRPCPort
        from meme_machine.operational.transport_bridge import BridgeRejected
        from meme_machine.runtime.isolated_native_bootstrap import NativeRunnerPorts,require_runner_ports
        from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
        client,parent=await fixture.ChildTransportTests.connected(self)
        resources=IsolatedNativeResources(self.root/'native',sizing_facts=authenticated(receipt()),clock=lambda:1000)
        self.addCleanup(resources.close)
        ports=NativeRunnerPorts(resources,client)
        self.assertIs(require_runner_ports(resources,ports),ports)
        failures=[];dispatch=parent.dispatch
        async def observed(frame):
            try:return await dispatch(frame)
            except BridgeRejected as error:
                failures.append((str(error),sum(c.kind=='http' and c.status in ('running','delivered')
                    for c in parent.contents.values())))
                raise
        parent.dispatch=observed
        # Hold the exact admitted work before original provider acquisition.
        # Otherwise the real Governor may refuse some duplicate-source calls
        # before all four parent content slots become occupied.
        gate=asyncio.Event();execute=self.http.execute
        async def held(attempt):
            await gate.wait()
            return await execute(attempt)
        def begin_all():
            for _ in range(parent.workers+1):
                client.request('http_begin',alias='pump',calls=[dict(method='getSlot',params=[])],batch=False)
        try:
            with patch.object(self.http,'execute',held),self.assertRaises(Exception):
                await asyncio.wait_for(asyncio.to_thread(begin_all),3)
            self.assertEqual(failures,[('parent_attempt_capacity',parent.workers)])
            self.assertIs(type(ports),NativeRunnerPorts)
            self.assertIs(ports.resources,resources)
            self.assertFalse(ports.closed);self.assertTrue(ports.channel.closed)
            with self.assertRaisesRegex(ValueError,'isolated_native_runner_ports_required'):
                require_runner_ports(resources,ports)
        finally:
            gate.set()
            await asyncio.wait_for(parent.aclose(),3)
        self.assertLessEqual(int(self.budget.snapshot()['http_attempts']),parent.workers)
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')
        self.assertEqual(parent.first_fault()['boundary_code'],'parent_attempt_capacity')
        self.assertEqual(client.abort_snapshot()['boundary_code'],'child_parent_eof')

    async def test_five_native_calls_backpressure_at_four_and_keep_other_control_progress(self):
        from tests import test_child_transport as fixture
        from meme_machine.operational.child_transport import ChildRPCPort
        client,parent=await fixture.ChildTransportTests.connected(self)
        gate=threading.Event();entered=threading.Event();begins=[];arrived=[]
        dispatch=parent.dispatch;content=client._content
        async def observed(frame):
            value=json.loads(frame[4:])
            if value['verb']=='http_begin':begins.append(value['seq'])
            return await dispatch(frame)
        parent.dispatch=observed
        def hold(accepted,**kw):
            arrived.append(accepted['token'])
            if len(arrived)==parent.workers:entered.set()
            if not gate.wait(3):raise TimeoutError('offline content gate')
            return content(accepted,**kw)
        pool=ThreadPoolExecutor(max_workers=parent.workers+1);tasks=[]
        try:
            with patch.object(client,'_content',hold):
                tasks=[asyncio.get_running_loop().run_in_executor(pool,ChildRPCPort(client,'pump').envelope,
                    dict(jsonrpc='2.0',id=n+1,method='getSlot',params=[])) for n in range(parent.workers+1)]
                self.assertTrue(await asyncio.to_thread(entered.wait,2))
                await asyncio.sleep(.05)
                self.assertEqual(client.http_workers,parent.workers)
                self.assertEqual(len(begins),parent.workers)
                self.assertEqual(len(arrived),parent.workers)
                # Native/control messages do not consume the HTTP class slots.
                await asyncio.wait_for(asyncio.to_thread(ChildRPCPort(client,'pons').demand,['eth_chainId']),1)
                self.assertFalse(client.closed);self.assertFalse(parent.closed)
                gate.set()
                results=await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),3)
            self.assertEqual(len(begins),parent.workers+1)
            self.assertEqual(len(results),parent.workers+1)
            self.assertTrue(any(type(row) is dict for row in results))
            self.assertFalse(client.closed);self.assertFalse(parent.closed)
            self.assertIsNone(client.abort_snapshot());self.assertIsNone(parent.first_fault())
            self.assertFalse(parent.contents)
        finally:
            gate.set()
            try:await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),3)
            except TimeoutError:
                client.abort()
                await asyncio.gather(*tasks,return_exceptions=True)
                raise
            finally:await asyncio.to_thread(pool.shutdown,wait=True)

    async def test_capacity_wait_keeps_original_deadline_no_purchase_or_session_abort(self):
        from tests import test_child_transport as fixture
        from meme_machine.operational.child_transport import ChildRPCPort,ChildTransportFailure
        client,parent=await fixture.ChildTransportTests.connected(self)
        for _ in range(parent.workers):self.assertTrue(client._http_slots.acquire(blocking=False))
        before=client.sequence;deadline=time.monotonic()+.05
        try:
            with self.assertRaisesRegex(ChildTransportFailure,'child_transport_stopped'):
                await asyncio.to_thread(ChildRPCPort(client,'pump').envelope,
                    dict(jsonrpc='2.0',id=1,method='getSlot',params=[]),deadline=deadline)
            self.assertGreaterEqual(time.monotonic(),deadline)
            self.assertEqual(client.sequence,before)
            self.assertEqual(self.budget.snapshot()['http_attempts'],'0')
            self.assertFalse(client.closed);self.assertIsNone(client.abort_snapshot())
        finally:
            for _ in range(parent.workers):client._http_slots.release()
        self.assertEqual((await asyncio.to_thread(ChildRPCPort(client,'pump').envelope,
            dict(jsonrpc='2.0',id=2,method='getSlot',params=[])))['result'],'0x123')

    async def test_cancelled_capacity_wait_is_unsent_and_does_not_close_accepted_session(self):
        from tests import test_child_transport as fixture
        from meme_machine.operational.child_transport import ChildRPCPort,ChildTransportFailure
        cancelled=threading.Event();client,parent=await fixture.ChildTransportTests.connected(self,cancelled=cancelled.is_set)
        for _ in range(parent.workers):self.assertTrue(client._http_slots.acquire(blocking=False))
        before=client.sequence
        waiter=asyncio.create_task(asyncio.to_thread(ChildRPCPort(client,'pump').envelope,
            dict(jsonrpc='2.0',id=1,method='getSlot',params=[])))
        try:
            await asyncio.sleep(.03);cancelled.set()
            with self.assertRaisesRegex(ChildTransportFailure,'child_transport_stopped'):
                await asyncio.wait_for(waiter,1)
            self.assertEqual(client.sequence,before)
            self.assertFalse(client.closed);self.assertFalse(parent.contents)
            self.assertEqual(self.budget.snapshot()['http_attempts'],'0')
        finally:
            for _ in range(parent.workers):client._http_slots.release()

    async def test_unsent_control_deadline_refusal_preserves_sequence_and_shared_session(self):
        from tests import test_child_transport as fixture
        from meme_machine.operational.child_transport import ChildRPCPort,ChildTransportFailure
        client,parent=await fixture.ChildTransportTests.connected(self)
        before=client.sequence
        with self.assertRaisesRegex(ChildTransportFailure,'child_transport_stopped'):
            await asyncio.to_thread(client.request,'activity',alias='pons',deadline=time.monotonic()-1)
        self.assertEqual(client.sequence,before);self.assertFalse(client.closed)
        await asyncio.to_thread(ChildRPCPort(client,'pons').demand,['eth_chainId'])

    async def test_partial_control_write_quarantines_and_retains_first_private_safe_abort(self):
        import socket
        from tests import test_child_transport as fixture
        from meme_machine.operational.child_transport import ChildRPCPort
        client,parent=await fixture.ChildTransportTests.connected(self)
        original=socket.socket.sendall;failure=BrokenPipeError(errno.EPIPE,'PRIVATE-provider-SQL')
        def partial(sock,body):
            original(sock,body[:2]);raise failure
        with patch.object(socket.socket,'sendall',partial):
            with self.assertRaises(BrokenPipeError) as caught:
                await asyncio.to_thread(ChildRPCPort(client,'pons').activity_marker)
        self.assertIs(caught.exception,failure);self.assertTrue(client.closed)
        value=client.abort_snapshot()
        self.assertEqual(value['phase'],'CONTROL_EXCHANGE');self.assertEqual(value['error_number'],errno.EPIPE)
        self.assertNotIn('PRIVATE',json.dumps(value))
        client.abort(PermissionError(13,'PRIVATE'),phase='CONTENT_HANDOFF')
        self.assertEqual(client.abort_snapshot(),value)
        value['phase']='PRIVATE';self.assertNotEqual(client.abort_snapshot(),value)
        self.assertEqual(self.budget.snapshot()['http_attempts'],'0')

    async def test_fault_projection_failure_cannot_prevent_original_channel_quarantine(self):
        from tests import test_child_transport as fixture
        from meme_machine.operational import transport_bridge,parent_channel
        client,parent=await fixture.ChildTransportTests.connected(self)
        with patch.object(transport_bridge,'transport_fault',side_effect=RuntimeError('PRIVATE')):
            client.abort(ValueError('PRIVATE'),phase='CONTROL_EXCHANGE')
        self.assertTrue(client.closed)
        self.assertEqual(client.abort_snapshot()['error_type'],'PROJECTION_UNAVAILABLE')
        with patch.object(parent_channel,'transport_fault',side_effect=RuntimeError('PRIVATE')):
            parent._record_fault('PARENT_DISPATCH',ValueError('PRIVATE'))
        self.assertEqual(parent.first_fault()['error_type'],'PROJECTION_UNAVAILABLE')
        self.assertNotIn('PRIVATE',json.dumps(parent.first_fault()))

    async def test_hello_rejects_missing_invalid_or_old_http_capacity_contract(self):
        import socket
        from tests import test_child_transport as fixture
        from meme_machine.operational.child_transport import ChildChannel,ChildTransportFailure
        from meme_machine.operational.transport_bridge import encode_frame
        client,parent=await fixture.ChildTransportTests.connected(self)
        values=[dict(parent.hello(),http_workers=value) for value in (0,9,True,'4',None)]
        missing=dict(parent.hello());missing.pop('http_workers');values.append(missing)
        values.append(dict(parent.hello(),protocol='native-parent-transport-v3'))
        for value in values:
            upstream,downstream=socket.socketpair()
            try:
                upstream.sendall(encode_frame(value))
                with self.assertRaises(ChildTransportFailure):
                    await asyncio.to_thread(ChildChannel,downstream)
                self.assertEqual(downstream.fileno(),-1)
            finally:upstream.close();downstream.close()
        self.assertFalse(client.closed)
        self.assertEqual(self.budget.snapshot()['http_attempts'],'0')


class TransportFaultPrivacyTests(unittest.TestCase):
    def test_only_fixed_phase_class_code_errno_and_native_source_site_are_retained(self):
        from meme_machine.operational.transport_bridge import transport_fault,BridgeRejected
        for error in (ValueError('PRIVATE'),type('PRIVATE',(ValueError,),{})('PRIVATE'),
                BridgeRejected('parent_attempt_capacity'),PermissionError(13,'PRIVATE')):
            value=transport_fault(error,'CONTROL_EXCHANGE')
            self.assertNotIn('PRIVATE',json.dumps(value))
            self.assertEqual('boundary_code' in value,error.args==('parent_attempt_capacity',))
        self.assertEqual(value['error_number'],13)
        self.assertEqual(transport_fault(None,'PARENT_UPLOAD_DEADLINE')['error_type'],'NO_EXCEPTION')

    def test_transport_snapshot_failure_never_replaces_original_child_failure(self):
        receipt=dict(status='BLOCKED',failure_code='isolated_native_pons_failed')
        channel=Mock();channel.abort_snapshot.side_effect=RuntimeError('PRIVATE')
        entry._capture_transport_abort(receipt,channel)
        self.assertEqual(receipt['failure_code'],'isolated_native_pons_failed')
        self.assertEqual(receipt['status'],'BLOCKED')
        self.assertEqual(receipt['transport_abort']['error_type'],'PROJECTION_UNAVAILABLE')
        self.assertNotIn('PRIVATE',json.dumps(receipt))


if __name__=='__main__':unittest.main()
