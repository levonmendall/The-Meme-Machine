"""Actual process exit under blocked native/default-executor owners, no providers.

The subprocess mocks fixed-entry image/descriptor admission ONLY to isolate its
terminal behavior. It is not a kernel/launcher/provider/full-pipeline proof.
Actual private CandidateHistory ownership, asyncio.Runner, source lifetime and
nonblocking FD1 termination execute normally. Production drain remains65s; the
private lifecycle fixture uses a tenth-second deadline.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPT=r'''
import socket
left,right=socket.socketpair()
assert left.fileno()==3
import asyncio,json,os,threading,time
from pathlib import Path
from unittest.mock import patch
from meme_machine.operational import isolated_native_entry as entry
from meme_machine.operational import isolated_native_source as source
from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
from tests.test_isolated_native_resources import authenticated,receipt
root=Path(os.environ['MM_FATAL_FIXTURE_ROOT'])
resources=IsolatedNativeResources(root/'owned',sizing_facts=authenticated(receipt()),clock=lambda:1000)
unsafe=root/'unsafe-close'
def unsafe_close():unsafe.write_text('closed under live owner')
resources.close=unsafe_close
entered=threading.Event();block=threading.Event()
class Channel:
    session='s'*43
    abort=staticmethod(unsafe_close)
    abort_and_join=staticmethod(unsafe_close)
class Reader:
    close=staticmethod(unsafe_close)
    def receive(self):return resources.facts
    def apply_next(self,resources,*,seconds):time.sleep(.01)
class Ports:
    close=staticmethod(unsafe_close)
def owned_worker():
    history=resources.candidate_history()
    entered.set()
    while True:
        history.telemetry()
        block.wait(.01)
async def native_source(event):
    path=resources.root/'solana-evidence.sqlite'
    path.touch()
    # A real default executor task demonstrates why Runner.close() cannot own a
    # second indefinite join after the original native shutdown fence expired.
    background=asyncio.create_task(asyncio.to_thread(block.wait))
    try:await event.wait()
    finally:
        if os.environ.get('MM_FATAL_SOURCE_STUCK')=='1':
            while True:
                try:await asyncio.sleep(10)
                except asyncio.CancelledError:pass
def run_contained(**values):
    return source._run_owned_loop(source._run_lifecycle(resources=resources,
        stopped=values['stopped'],sizing_reader=values['sizing_reader'],source=native_source,
        workers=[('pump',owned_worker)],source_path=resources.root/'solana-evidence.sqlite',
        source_ready=lambda:True if (resources.root/'solana-evidence.sqlite').is_file() else None,
        seconds=.15,startup_seconds=1,shutdown_seconds=.1))
if os.environ.get('MM_FATAL_FULL_PIPE')=='1':
    read,write=os.pipe2(os.O_NONBLOCK)
    try:
        while True:os.write(write,b'x'*4096)
    except BlockingIOError:pass
    os.dup2(write,1)
with patch.object(entry,'_image_identity',return_value=dict(source_commit='a'*40,source_tree='b'*40)), \
        patch.object(entry,'_new_resources',return_value=resources), \
        patch.object(Path,'cwd',return_value=Path('/work/native')), \
        patch('meme_machine.operational.child_transport.ChildChannel',return_value=Channel()), \
        patch.object(entry,'ParentSizingReader',return_value=Reader()), \
        patch('meme_machine.runtime.isolated_native_bootstrap.NativeRunnerPorts',return_value=Ports()), \
        patch.object(source,'run_contained',side_effect=run_contained):
    raise SystemExit(entry.main())
'''


class NativeFatalDrainTests(unittest.TestCase):
    def run_child(self,*,full_pipe=False,source_stuck=False):
        with tempfile.TemporaryDirectory() as directory:
            env=dict(os.environ,MM_FATAL_FIXTURE_ROOT=directory,
                MM_FATAL_FULL_PIPE='1' if full_pipe else '0',
                MM_FATAL_SOURCE_STUCK='1' if source_stuck else '0')
            began=time.monotonic()
            result=subprocess.run([sys.executable,'-B','-c',SCRIPT],env=env,
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=4)
            self.assertLess(time.monotonic()-began,3)
            self.assertEqual(result.returncode,2,result.stderr.decode())
            self.assertFalse((Path(directory)/'unsafe-close').exists())
            partial=json.loads((Path(directory)/'owned/native-execution.json').read_text())
            self.assertEqual(partial['status'],'FAILED')
            self.assertEqual(partial['failure_code'],'isolated_native_shutdown_incomplete')
            self.assertFalse(partial['all_workers_joined'])
            self.assertFalse(partial['graceful_shutdown'])
            self.assertFalse(partial['financial_authority'])
            self.assertEqual(partial['source_joined'],not source_stuck)
            self.assertFalse(partial['workers']['pump']['completed'])
            if full_pipe:
                self.assertEqual(result.stdout,b'')
            else:
                final=json.loads(result.stdout)
                self.assertEqual(final['status'],'BLOCKED')
                self.assertEqual(final['failure_code'],'isolated_native_shutdown_incomplete')
                self.assertFalse(final['graceful_shutdown'])
                self.assertFalse(final['all_workers_joined'])
                self.assertFalse(final['financial_authority'])
                self.assertEqual(final['physical_process_cleanup'],'UNVERIFIED_UNTIL_PARENT_REAP')

    def test_fixed_entry_exits_with_failed_receipt_without_closing_live_owner_or_atexit_join(self):
        self.run_child()

    def test_pending_uncooperative_async_source_does_not_enter_runner_cancel_join(self):
        self.run_child(source_stuck=True)

    def test_full_result_pipe_cannot_prevent_bounded_owned_process_exit(self):
        self.run_child(full_pipe=True)


if __name__=='__main__':unittest.main()
