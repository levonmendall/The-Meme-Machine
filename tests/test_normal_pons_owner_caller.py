"""Caller ownership/order; actual root/IPC acquisition has separate tests.

Mocks below are explicit call-order premises, never issued owner capabilities.
The failed-launch child and original group stop/reap are actual OS processes.
"""
from pathlib import Path
import os
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

from meme_machine.operational import lane,normal_pons_boot,supervisor


class PonsOwnerCallerTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        (self.root/'pons').mkdir()
        self.service=supervisor.Supervisor(self.root,offline=True)
        self.service.environment=lambda name:{'MM_RUNTIME_LANE':name}

    def test_default_lane_launch_has_original_arguments_and_no_private_channel(self):
        process=SimpleNamespace(pid=123)
        with patch.object(supervisor.subprocess,'Popen',return_value=process) as opened, \
                patch.object(normal_pons_boot,'PonsOwnerLaunch',side_effect=AssertionError('unexpected context')):
            self.service.start_lane('pons')
        args,kwargs=opened.call_args
        self.assertEqual(args[0],[sys.executable,'-m','meme_machine.operational.lane',
            '--lane','pons','--state-root',str(self.root),'--offline'])
        self.assertNotIn('pass_fds',kwargs)
        self.assertEqual(kwargs['env']['MM_LANE_PROCESS_INSTANCE'],self.service.process_instances['pons'])
        self.assertIs(self.service.processes['pons'],process)

    def test_private_launch_binds_actual_generated_lane_instance_and_closes_channel(self):
        context=object();self.service.normal_boot=context;self.service.offline=False
        process=SimpleNamespace(pid=123)
        channel=SimpleNamespace(child_fd=17,bind=Mock(return_value={'metadata':'accepted'}),close=Mock())
        with patch.object(supervisor.subprocess,'Popen',return_value=process) as opened, \
                patch.object(normal_pons_boot,'PonsOwnerLaunch',return_value=channel) as issuing:
            self.service.start_lane('pons')
        issuing.assert_called_once_with(context)
        args,kwargs=opened.call_args
        self.assertEqual(args[0][-2:],['--normal-owner-channel','17'])
        self.assertEqual(kwargs['pass_fds'],(17,))
        self.assertTrue(kwargs['start_new_session'])
        self.assertIs(channel.bind.call_args.args[0],process)
        self.assertEqual(channel.bind.call_args.kwargs['process_instance'],
            kwargs['env']['MM_LANE_PROCESS_INSTANCE'])
        self.assertEqual(self.service.pons_owner_generation,{'metadata':'accepted'})
        channel.close.assert_called_once()

    def test_failed_handoff_reaps_actual_owned_group_and_retains_original_failure(self):
        self.service.normal_boot=object();self.service.offline=False
        left,right=socket.socketpair();self.addCleanup(left.close);self.addCleanup(right.close)
        channel=SimpleNamespace(child_fd=right.fileno(),
            bind=Mock(side_effect=RuntimeError('original_handoff_failure')),close=Mock())
        original=subprocess.Popen;children=[]
        def opened(command,**options):
            self.assertEqual(command[-2:],['--normal-owner-channel',str(right.fileno())])
            process=original([sys.executable,'-c','import time; time.sleep(30)'],
                start_new_session=options['start_new_session'],pass_fds=options['pass_fds'])
            children.append(process);return process
        def cleanup():
            for process in children:
                if process.poll() is None:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                process.wait(timeout=5)
        self.addCleanup(cleanup)
        with patch.object(supervisor.subprocess,'Popen',side_effect=opened), \
                patch.object(normal_pons_boot,'PonsOwnerLaunch',return_value=channel):
            with self.assertRaisesRegex(RuntimeError,'original_handoff_failure'):
                self.service.start_lane('pons')
        self.assertEqual(len(children),1)
        self.assertIsNotNone(children[0].poll())
        self.assertIs(self.service.processes['pons'],children[0])
        self.assertIn('pons',self.service.process_instances)
        channel.close.assert_called_once()

    def test_lane_entry_rechecks_original_context_before_install_or_native_constructor(self):
        calls=[];context=SimpleNamespace(close=lambda:calls.append('close'),
            identity=lambda:{'root':str(self.root)})
        with patch.object(sys,'argv',['lane','--lane','pons','--state-root',str(self.root),
                '--normal-owner-channel','17']),patch.object(lane.signal,'signal'), \
                patch.object(normal_pons_boot,'accept_pons_owner_launch',return_value=context), \
                patch.object(normal_pons_boot,'require_pons_owner_context',
                    side_effect=RuntimeError('original_entry_expired')) as checked, \
                patch('meme_machine.operational.bounded_provider.install',side_effect=AssertionError('provider install')), \
                patch.object(lane,'run_native',side_effect=AssertionError('native constructor')):
            with self.assertRaisesRegex(RuntimeError,'original_entry_expired'):lane.main()
        checked.assert_called_once_with(context,initial=True)
        self.assertEqual(calls,['close'])

    def test_lane_lock_open_failure_still_invalidates_acquired_context(self):
        context=SimpleNamespace(close=Mock(),identity=lambda:{'root':str(self.root/'missing')})
        with patch.object(sys,'argv',['lane','--lane','pons','--state-root',str(self.root/'missing'),
                '--normal-owner-channel','17']),patch.object(lane.signal,'signal'), \
                patch.object(normal_pons_boot,'accept_pons_owner_launch',return_value=context), \
                patch('meme_machine.operational.bounded_provider.install',side_effect=AssertionError('provider install')):
            with self.assertRaises(FileNotFoundError):lane.main()
        context.close.assert_called_once()

    def test_crossed_cli_root_refuses_before_lock_or_native_constructors(self):
        foreign=self.root/'foreign';(foreign/'pons').mkdir(parents=True)
        context=SimpleNamespace(close=Mock(),identity=lambda:{'root':str(self.root)})
        before=tuple(foreign.rglob('*'))
        with patch.object(sys,'argv',['lane','--lane','pons','--state-root',str(foreign),
                '--normal-owner-channel','17']),patch.object(lane.signal,'signal'), \
                patch.object(normal_pons_boot,'accept_pons_owner_launch',return_value=context), \
                patch.object(normal_pons_boot,'require_pons_owner_context',
                    side_effect=AssertionError('post-lock entry check')) as checked, \
                patch('meme_machine.operational.bounded_provider.install',
                    side_effect=AssertionError('provider install')) as installed, \
                patch.object(lane,'run_native',side_effect=AssertionError('native constructor')) as native:
            with self.assertRaisesRegex(RuntimeError,'pons_owner_entry_root'):lane.main()
        self.assertEqual(tuple(foreign.rglob('*')),before)
        self.assertFalse((foreign/'pons'/'lane.lock').exists())
        checked.assert_not_called();installed.assert_not_called();native.assert_not_called()
        context.close.assert_called_once()
