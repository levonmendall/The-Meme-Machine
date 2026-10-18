"""Real errno handoff at fixed namespace maps; no kernel policy is installed."""
from contextlib import ExitStack, contextmanager
import errno
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch

from meme_machine.operational import namespace_canary as ns

MAPS = [('setgroups','deny'), ('uid_map','0 1001 1\n'), ('gid_map','0 1002 1\n')]


@contextmanager
def setup_fixture(write):
    with ExitStack() as stack:
        kernel = Mock()
        stack.enter_context(patch.object(ns,'Kernel',return_value=kernel))
        stack.enter_context(patch.object(ns.os,'geteuid',return_value=1001))
        stack.enter_context(patch.object(ns.os,'getegid',return_value=1002))
        stack.enter_context(patch.object(ns.os,'getppid',return_value=99))
        stack.enter_context(patch.object(ns.os,'listdir',return_value=['single']))
        stack.enter_context(patch.object(ns,'_private',side_effect=lambda path,**kw:Path(path)))
        stack.enter_context(patch.object(ns,'_scratch'))
        writer=stack.enter_context(patch.object(Path,'write_text',autospec=True,side_effect=write))
        fork=stack.enter_context(patch.object(ns.os,'fork'))
        probe=stack.enter_context(patch.object(ns,'_probe'))
        yield dict(root='/fixed/root',work='/fixed/work',parent_pid=99),kernel,writer,fork,probe


class NamespaceMappingErrnoTests(unittest.TestCase):
    def test_each_actual_errno_is_preserved_and_all_later_actions_are_unreached(self):
        for target, _ in MAPS:
            for number in (errno.EPERM,errno.EACCES):
                writes=[]
                def write(path,value):
                    writes.append((path.name,value))
                    if path.name==target:raise PermissionError(number,'PRIVATE-NOT-RETURNED')
                with self.subTest(target=target,number=number), setup_fixture(write) as (spec,kernel,writer,fork,probe):
                    with self.assertRaises(ns.Blocked) as caught:ns._setup(spec)
                    self.assertEqual(caught.exception.code,'namespace_'+target+'_refused')
                    self.assertEqual(caught.exception.number,number)
                    self.assertEqual(writes,MAPS[:[name for name,_ in MAPS].index(target)+1])
                    kernel.unshare.assert_called_once_with(ns.USER)
                    kernel.mount.assert_not_called();fork.assert_not_called();probe.assert_not_called()

    def test_original_successful_mapping_order_and_values_precede_second_unshare(self):
        writes=[];stop=RuntimeError('offline stop before namespace mount')
        with setup_fixture(lambda path,value:writes.append((path.name,value))) as (spec,kernel,writer,fork,probe):
            kernel.unshare.side_effect=[None,stop]
            with self.assertRaises(RuntimeError) as caught:ns._setup(spec)
            self.assertIs(caught.exception,stop)
            self.assertEqual(writes,MAPS)
            self.assertEqual(kernel.unshare.call_args_list,
                [call(ns.USER),call(ns.MOUNT|ns.NET|ns.PID|ns.IPC)])
            kernel.mount.assert_not_called();fork.assert_not_called();probe.assert_not_called()

    def test_main_returns_original_actual_errno_and_keeps_refusal_flags(self):
        def write(path,value):raise PermissionError(errno.EACCES,'PRIVATE-NOT-RETURNED')
        output=io.StringIO()
        with setup_fixture(write) as (spec,kernel,writer,fork,probe), \
                patch.object(ns.sys,'argv',['canary','--setup','{}']), \
                patch.object(ns,'_spec',return_value=spec), patch.object(ns.sys,'stdout',output):
            self.assertEqual(ns.main(),2)
        result=json.loads(output.getvalue())
        self.assertEqual(result['state'],'BLOCKED')
        self.assertEqual(result['code'],'namespace_setgroups_refused')
        self.assertEqual(result['error_number'],errno.EACCES)
        self.assertIs(result['fallback_allowed'],False)
        self.assertIs(result['financial_authority'],False)
        self.assertEqual(result['provider_calls'],0)
        self.assertNotIn('PRIVATE',output.getvalue())
        probe.assert_not_called()

    def test_missing_invalid_or_noninteger_errno_remains_original_error(self):
        for number in (None,0,-1,4096,True,'13'):
            error=OSError('PRIVATE');error.errno=number
            with self.subTest(number=number),patch.object(Path,'write_text',side_effect=error):
                with self.assertRaises(OSError) as caught:ns._write_user_mapping('setgroups','deny')
                self.assertIs(caught.exception,error)

    def test_non_oserror_is_not_translated_even_with_numeric_errno(self):
        error=RuntimeError('PRIVATE');error.errno=errno.EPERM
        with patch.object(Path,'write_text',side_effect=error):
            with self.assertRaises(RuntimeError) as caught:ns._write_user_mapping('setgroups','deny')
            self.assertIs(caught.exception,error)

    def test_generic_missing_errno_stays_nonavailability_failure_without_later_actions(self):
        error=PermissionError('PRIVATE')
        output=io.StringIO()
        with setup_fixture(Mock(side_effect=error)) as (spec,kernel,writer,fork,probe), \
                patch.object(ns.sys,'argv',['canary','--setup','{}']), \
                patch.object(ns,'_spec',return_value=spec), patch.object(ns.sys,'stdout',output):
            self.assertEqual(ns.main(),2)
        result=json.loads(output.getvalue())
        self.assertEqual(result['code'],'namespace_setup_or_probe_failed')
        self.assertNotIn('error_number',result)
        self.assertIs(result['fallback_allowed'],False)
        kernel.unshare.assert_called_once_with(ns.USER)
        kernel.mount.assert_not_called();fork.assert_not_called();probe.assert_not_called()

    def test_unknown_mapping_cannot_select_another_proc_target(self):
        with patch.object(Path,'write_text') as write:
            for name in ('../uid_map','environ','task',''):
                with self.subTest(name=name),self.assertRaisesRegex(ns.Blocked,'mapping_unreviewed'):
                    ns._write_user_mapping(name,'deny')
            write.assert_not_called()


if __name__=='__main__':unittest.main()
