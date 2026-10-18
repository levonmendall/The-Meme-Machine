"""Actual local Pump child/anonymous IPC; unavailable root/unit/clock simulated.

The existing four-regime prewrite fixture really replays its native financial
corpus. These tests do not claim protected root acquisition on this Cloud host.
No provider or financial constructor runs in the child owner protocol.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from meme_machine.operational import normal_boot as boot
from meme_machine.operational import normal_boot_record as wire
from meme_machine.operational import normal_pump_boot as pump
from tests import test_normal_boot_context as fixtures


CHILD=r'''
import copy,json,os,pickle,sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from operational.tests import network_guard
network_guard()
from meme_machine.operational import normal_boot as boot
from meme_machine.operational import normal_pump_boot as pump
fixture=json.loads(sys.stdin.readline());locator,record=fixture['locator'],fixture['record']
fields='MainPID='+str(record['supervisor']['pid'])+'\nInvocationID='+record['supervisor']['invocation_id']+'\nActiveState=active\n'
try:
    with patch.object(pump,'_read_record',return_value=(locator,record)), \
         patch.object(pump,'_clock_sha256',return_value='e'*64), \
         patch.object(boot,'_source_identity',return_value=(record['application_commit'],record['application_tree'])), \
         patch.object(pump.subprocess,'run',return_value=SimpleNamespace(stdout=fields)):
        cap=pump.accept_pump_owner_launch(int(sys.argv[1]))
        mode=fixture.get('mode')
        if mode in ('revoke','expire','clock','source','process_instance','late_identity_work'):
            sys.stdin.readline()
            if mode=='revoke':
                locator=dict(locator,state='REVOKED',record_sha256=None)
            if mode=='process_instance':os.environ['MM_LANE_PROCESS_INSTANCE']='f'*32
            with patch.object(pump,'_read_record',return_value=(locator,record)), \
                 patch.object(pump,'_clock_sha256',return_value='f'*64 if mode=='clock' else 'e'*64), \
                 patch.object(boot,'_source_identity',return_value=('f'*40,record['application_tree']) if mode=='source'
                    else (record['application_commit'],record['application_tree'])):
                if mode=='expire':
                    with patch.object(pump.time,'monotonic',return_value=record['not_after_monotonic']):
                        pump.require_pump_owner_context(cap,initial=True)
                elif mode=='late_identity_work':
                    now=[record['not_after_monotonic']-1]
                    def last_identity():now[0]=record['not_after_monotonic'];return 'e'*64
                    with patch.object(pump.time,'monotonic',side_effect=lambda:now[0]), \
                         patch.object(pump,'_clock_sha256',side_effect=last_identity):
                        pump.require_pump_owner_context(cap,initial=True)
                else:pump.require_pump_owner_context(cap,initial=True)
                raise AssertionError('provider_or_native_constructor_reached')
        pump.require_pump_owner_context(cap,initial=True)
        support=cap.boot_support()
        support_sha=support.identity_sha256
        assert support.outbox_support('program:pump')['upper_sequence'] is None
        # This is a genuinely accepted Pump object. Neither other exact private
        # capability API may accept it as its own owner/source generation.
        from meme_machine.operational.normal_pons_boot import require_pons_owner_context
        from meme_machine.operational.normal_source_boot import require_native_generation
        crossed_refused=[]
        for require_other in (require_pons_owner_context,require_native_generation):
            try:require_other(cap)
            except Exception:crossed_refused.append(True)
            else:crossed_refused.append(False)
        with ThreadPoolExecutor(max_workers=1) as pool:
            thread_same=pool.submit(lambda:pump.current_pump_owner_context() is cap).result(2)
        copied=cap.identity();copied['owner']['pid']=0
        assert cap.identity()['owner']['pid']==os.getpid()
        try:pickle.dumps(cap)
        except TypeError:unpicklable=True
        else:unpicklable=False
        if mode=='fork':
            child=os.fork()
            if child==0:
                try:pump.require_pump_owner_context(cap)
                except Exception:os._exit(0)
                os._exit(3)
            _,status=os.waitpid(child,0);assert os.waitstatus_to_exitcode(status)==0
        with patch.object(pump.time,'monotonic',return_value=record['not_after_monotonic']+3600):
            ongoing=pump.require_pump_owner_context(cap) is cap
        cap.close();assert pump.current_pump_owner_context() is None
        try:support.value()
        except Exception:support_closed=True
        else:support_closed=False
        try:pump.require_pump_owner_context(cap)
        except Exception:closed_refuses=True
        else:closed_refuses=False
        closed=False
        try:os.fstat(int(sys.argv[1]))
        except OSError:closed=True
        print(json.dumps(dict(identity_sha256=cap.identity_sha256,pid=os.getpid(),closed_fd=closed,
            owner_generation=cap.owner_generation,thread_same=thread_same,unpicklable=unpicklable,
            ongoing=ongoing,closed_refuses=closed_refuses,crossed_refused=crossed_refused,
            fields=sorted(cap.identity()),support_sha=support_sha,support_closed=support_closed)),flush=True)
    sys.stdin.readline()
except BaseException as error:
    print(type(error).__name__+':'+str(error),file=sys.stderr,flush=True)
    raise SystemExit(2)
'''


class NativePumpOwnerTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.NativePrewriteReplayTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.record=self.case.record;self.locator=self.case.locator
        actual_boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.record['boot_id']=self.record['boot_eligibility']['boot_id']=self.locator['boot_id']=actual_boot
        self.record['supervisor']['start_ticks']=pump._process_start(os.getpid())
        fixtures.rehash(self.record['boot_eligibility'])
        self.locator['record_sha256']=hashlib.sha256(wire.canonical(self.record)).hexdigest()
        self.case.launch._locator=deepcopy(self.locator);self.case.launch._record=deepcopy(self.record)
        self.context=boot.consume_normal_boot(self.case.supervisor,cancelled=lambda:False)
        self.enterContext(patch.object(pump,'_ISSUED_CONTEXT',None))
        self.enterContext(patch.object(pump,'_clock_sha256',return_value='e'*64))
        self.instance='d'*32

    def launch(self,channel,mode=None,env_changes=None):
        env=dict(os.environ,MM_STATE_ROOT=str(self.case.root),MM_RUNTIME_LANE='pump',
            MM_PAPER_EPOCH=self.record['boot_eligibility']['epoch_id'],
            MM_LANE_PROCESS_INSTANCE=self.instance,
            MM_SOLANA_EVIDENCE_PLANE_DB=str(self.case.root/'shared/solana-evidence.sqlite'),
            MM_SOLANA_CANDIDATE_HISTORY_DB=str(self.case.root/'shared/solana-candidate-history.sqlite'),
            MM_SOLANA_EVIDENCE_BROKER_DB=str(self.case.root/'pump/solana-evidence-broker.sqlite3'))
        env.update(env_changes or {})
        child=subprocess.Popen([sys.executable,'-c',CHILD,str(channel.child_fd)],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,pass_fds=(channel.child_fd,),
            start_new_session=True,env=env)
        def cleanup():
            if child.poll() is None:child.kill()
            child.wait(timeout=5)
            for stream in (child.stdin,child.stdout,child.stderr):
                if stream is not None:stream.close()
        self.addCleanup(cleanup)
        child.stdin.write(json.dumps(dict(locator=self.locator,record=self.record,mode=mode))+'\n');child.stdin.flush()
        return child

    def bind(self,channel,child):
        return channel.bind(child,deadline=time.monotonic()+5,process_instance=self.instance)

    def finish(self,child):
        child.stdin.write('stop\n');child.stdin.flush();child.stdin.close()
        self.assertEqual(child.wait(timeout=5),0,child.stderr.read())

    def test_real_child_identity_fd_lifecycle_thread_scope_and_no_authority(self):
        channel=pump.PumpOwnerLaunch(self.context);child=self.launch(channel)
        value=self.bind(channel,child);row=json.loads(child.stdout.readline())
        self.assertEqual(row['identity_sha256'],wire.digest(value))
        self.assertEqual(value['owner'],dict(pid=child.pid,start_ticks=pump._process_start(child.pid),process_instance=self.instance))
        self.assertEqual(value['launch']['record_sha256'],self.locator['record_sha256'])
        self.assertEqual(row['owner_generation'],value['owner_generation'])
        self.assertTrue(all(row[k] for k in ('closed_fd','thread_same','unpicklable','ongoing','closed_refuses')))
        self.assertEqual(row['crossed_refused'],[True,True])
        self.assertEqual(set(row['fields']),pump._SUPPORT_KEYS)
        self.assertEqual(row['support_sha'],self.context.boot_support().identity_sha256)
        self.assertTrue(row['support_closed'])
        self.assertEqual(value['schema'],'normal-pump-owner-subcap-v2')
        self.assertFalse(any('funding' in k or 'ready' in k or 'source_complete' in k for k in row['fields']))
        self.assertTrue(channel.closed);self.finish(child)
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'already_issued'):pump.PumpOwnerLaunch(self.context)

    def test_real_fork_cannot_reuse_accepted_pump_context(self):
        channel=pump.PumpOwnerLaunch(self.context);child=self.launch(channel,mode='fork')
        self.bind(channel,child);self.assertTrue(json.loads(child.stdout.readline())['closed_refuses']);self.finish(child)

    def test_support_from_wrong_native_certificate_refuses_real_child_before_ack(self):
        for field in ('native_input_sha256','physical_generation_sha256'):
            with self.subTest(field=field),patch.object(pump,'_ISSUED_CONTEXT',None):
                channel=pump.PumpOwnerLaunch(self.context);child=self.launch(channel);send=pump._send
                def changed(connected,value):
                    value=deepcopy(value);value['boot_support']['association'][field]='f'*64
                    send(connected,value)
                with patch.object(pump,'_send',side_effect=changed):
                    with self.assertRaisesRegex(wire.NormalBootUnavailable,'channel_eof'):self.bind(channel,child)
                self.assertTrue(channel.closed);self.assertIsNone(channel.identity)
                self.assertEqual(child.wait(timeout=5),2)
                self.assertIn('support_certificate_changed',child.stderr.read())
                self.assertEqual(child.stdout.read(),'')

    def test_crossed_packet_identity_cannot_ack_or_publish_context(self):
        for field in ('epoch','source','pid','instance'):
            with self.subTest(field=field),patch.object(pump,'_ISSUED_CONTEXT',None):
                channel=pump.PumpOwnerLaunch(self.context);child=self.launch(channel);send=pump._send
                def changed(connected,value):
                    value=deepcopy(value)
                    if field=='epoch':value['launch']['epoch_id']='different'
                    elif field=='source':value['launch']['application_tree']='f'*40
                    elif field=='pid':value['owner']['pid']=os.getpid()
                    else:value['owner']['process_instance']='f'*32
                    send(connected,value)
                with patch.object(pump,'_send',side_effect=changed):
                    with self.assertRaisesRegex(wire.NormalBootUnavailable,'channel_eof'):self.bind(channel,child)
                self.assertTrue(channel.closed);self.assertIsNone(channel.identity)
                self.assertEqual(child.wait(timeout=5),2)
                self.assertNotIn('provider_or_native_constructor',child.stderr.read());self.assertEqual(child.stdout.read(),'')

    def test_wrong_fixed_environment_refuses_acquisition(self):
        for key in ('MM_SOLANA_EVIDENCE_PLANE_DB','MM_SOLANA_CANDIDATE_HISTORY_DB',
                    'MM_SOLANA_EVIDENCE_BROKER_DB','MM_RUNTIME_LANE'):
            with self.subTest(key=key),patch.object(pump,'_ISSUED_CONTEXT',None):
                channel=pump.PumpOwnerLaunch(self.context)
                child=self.launch(channel,env_changes={key:'/tmp/foreign.sqlite' if key!='MM_RUNTIME_LANE' else 'pons'})
                with self.assertRaisesRegex(wire.NormalBootUnavailable,'channel_eof'):self.bind(channel,child)
                self.assertEqual(child.wait(timeout=5),2)
                self.assertIn('pump_owner_environment',child.stderr.read())

    def test_entry_revocation_expiry_clock_source_and_instance_refuse_before_constructors(self):
        for mode in ('revoke','expire','clock','source','process_instance','late_identity_work'):
            with self.subTest(mode=mode),patch.object(pump,'_ISSUED_CONTEXT',None):
                channel=pump.PumpOwnerLaunch(self.context);child=self.launch(channel,mode=mode);self.bind(channel,child)
                child.stdin.write('cross acquisition boundary\n');child.stdin.flush();child.stdin.close()
                self.assertEqual(child.wait(timeout=5),2)
                error=child.stderr.read();self.assertIn('normal_boot_pump_owner_',error)
                self.assertNotIn('provider_or_native_constructor_reached',error);self.assertEqual(child.stdout.read(),'')

    def test_unissued_dictionary_and_other_capability_types_never_supply_pump_scope(self):
        from meme_machine.operational.normal_pons_boot import NativePonsOwnerContext
        from meme_machine.operational.normal_source_boot import NativeSourceGeneration
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'private_issuer'):
            pump.NativePumpOwnerContext({})
        for value in ({'owner_generation':'a'*32},object(),self.context,
                object.__new__(NativePonsOwnerContext),object.__new__(NativeSourceGeneration)):
            with self.subTest(value=type(value)),self.assertRaisesRegex(wire.NormalBootUnavailable,'context_required'):
                pump.require_pump_owner_context(value)
        self.assertIsNone(pump.current_pump_owner_context())

    def test_invalid_parent_context_instance_and_deadline_close_before_handoff(self):
        with self.assertRaisesRegex(wire.NormalBootUnavailable,'private_context_required'):pump.PumpOwnerLaunch(object())
        for instance,deadline in (('wrong',time.monotonic()+5),(self.instance,float('nan')),(self.instance,time.monotonic()+30)):
            with self.subTest(instance=instance,deadline=deadline),patch.object(pump,'_ISSUED_CONTEXT',None):
                channel=pump.PumpOwnerLaunch(self.context)
                child=self.launch(channel)
                with self.assertRaises(wire.NormalBootUnavailable):channel.bind(child,deadline=deadline,process_instance=instance)
                self.assertTrue(channel.closed);self.assertIsNone(channel.identity)
                self.assertEqual(child.wait(timeout=5),2)
