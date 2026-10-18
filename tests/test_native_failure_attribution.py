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
        await self.fixture.asyncSetUp()
        self.addCleanup(self.fixture.doCleanups)

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


if __name__=='__main__':unittest.main()
