"""Real fixed copied main with an explicitly missing Landlock boundary.

The private fixture installs actual seccomp to deny all external socket paths,
but can never satisfy public kernel validation. Providers remain offline.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from dataclasses import replace
import tempfile
from unittest.mock import patch

from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational import isolated_native_image as image
from meme_machine.operational import isolated_native_kernel_validation as validation
from meme_machine.operational.isolated_native_landlock_launcher import NativeLandlockChild,_entry_command
from meme_machine.operational.isolated_native_layout import NativeChildLayout,PROFILE


def copied_seccomp_fixture(scope,approval,transport,facts):
    """No public selector: this test-only dependency can never attest Landlock."""
    staged=image.build(scope,approval,profile=PROFILE)
    root=Path(scope);work=root/'native-work';work.mkdir(mode=0o700)
    (work/'native').mkdir(mode=0o700);(work/'tmp').mkdir(mode=0o700)
    layout=NativeChildLayout(PROFILE,str(staged['root']),str(work),os.getpid(),staged['manifest_sha256'])
    source=Path(__file__).resolve().parents[1]
    code=('import ctypes,os,sys;sys.path.insert(0,'+repr(str(source))+');'+
        'from meme_machine.operational.isolated_native_landlock_launcher import _prune_native_descriptors;'+
        '_prune_native_descriptors('+str(transport.fileno())+','+str(facts)+');'+
        'from meme_machine.operational.native_landlock_policy import NativePolicy;'+
        'k=NativePolicy();'+
        'k.call(157,ctypes.c_int(38),ctypes.c_ulong(1),ctypes.c_ulong(0),ctypes.c_ulong(0),ctypes.c_ulong(0),code="fixture_nnp");'+
        'k.call(157,ctypes.c_int(1),ctypes.c_ulong(9),ctypes.c_ulong(0),ctypes.c_ulong(0),ctypes.c_ulong(0),code="fixture_pdeath");'+
        'k.seccomp();os.execve('+repr(str(layout.executable))+','+
        repr([str(layout.executable),'-I','-B','-S','-c',_entry_command(layout)])+','+repr(layout.environment())+')')
    child=subprocess.Popen([sys.executable,'-I','-B','-S','-c',code],stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=layout.native_directory,
        env={},close_fds=True,pass_fds=(transport.fileno(),facts),start_new_session=True)
    return NativeLandlockChild(child,time.monotonic())


class NativeKernelValidationTests(unittest.TestCase):
    def test_post_join_output_reader_refuses_symlink_ancestors_and_hardlinked_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);owned=root/'owned';owned.mkdir(mode=0o700)
            source=owned/'report.json';source.write_text('{}')
            alias=root/'alias';alias.symlink_to(owned,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'output_root'):validation.native_outputs(alias,endpoint_identity='a'*64)
            with self.assertRaisesRegex(ValueError,'file_bound'):validation._json_file(alias/'report.json')
            with self.assertRaisesRegex(ValueError,'database_inode'):validation._readonly(alias/'report.json')
            link=owned/'hardlink.json';os.link(source,link)
            with self.assertRaisesRegex(ValueError,'file_bound'):validation._json_file(link)
            with self.assertRaisesRegex(ValueError,'database_inode'):validation._readonly(link)
            link.unlink();self.assertEqual(validation._json_file(source),{})

    def test_policy_receipt_requires_one_exact_supported_install_observation(self):
        raw=b'NATIVE_POLICY_INSTALLED {"profile":"'+PROFILE.encode()+b'","landlock_abi":8,"installed":true}\n'
        self.assertEqual(validation._policy_record(raw)['landlock_abi'],8)
        for bad in (b'',raw+raw,raw.replace(b'8',b'5'),raw.replace(b'true',b'false'),
                raw.replace(b'8',b'8,"extra":true')):
            self.assertIsNone(validation._policy_record(bad))

    def test_unknown_partial_and_injected_kernel_observations_never_pass(self):
        for value in (None,{},dict(schema='synthetic-native-kernel-validation-v1',kernel_applied=False),
                dict(schema='synthetic-native-kernel-validation-v1',kernel_applied=True,landlock_abi=8),
                {'child':None},{'child':{'observation':[]},'native_outputs':{}},
                {'child':{'observation':{},'native_kernel_lifecycle':[]},'native_outputs':{}}):
            self.assertFalse(validation.verified(value))

    def test_acceptance_predicate_requires_exact_counts_and_retains_probe_distinction(self):
        # Pure schema/predicate fixture, never a receipt from an executed kernel.
        child=dict(status='COMPLETED',observation=dict(graceful_shutdown=True,
            all_workers_joined=True,source_joined=True,workers={name:dict(started=True,completed=True)
                for name in ('pump','pons','sizing')}),native_kernel_lifecycle=dict(
            tracker_spawned=True,tracker_joined=True,spawn_owner_joined=True,
            workers_spawned=dict(decoder=2,history=1),executors={role:dict(state='JOINED',
                spawned=count,joined=count,zero_exit=count,successful=3 if role=='decoder' else 1,
                probe_successful=2 if role=='decoder' else 0,nonprobe_successful=1,broken=False)
                for role,count in (('decoder',2),('history',1))}))
        base=dict(schema='synthetic-native-kernel-validation-v1',kernel_applied=True,landlock_abi=8,
            owned_process_reaped=True,parent_cleanup_joined=True,external_provider_calls=0,
            financial_authority=False,production_state_writes=0,parent_cwd_unchanged=True,child=child,
            native_outputs=dict(financial_tables_absent=True,canonical_full_ack=1,candidate_references=4,
                regimes={key:True for key in ('pump_current','pump_survivor','pons_current','pons_survivor')}))
        self.assertTrue(validation.verified(base))
        paths=[('child',),('native_outputs',),('child','observation'),
            ('child','native_kernel_lifecycle'),('child','observation','workers'),
            ('child','observation','workers','pump'),('child','native_kernel_lifecycle','executors'),
            ('child','native_kernel_lifecycle','executors','decoder')]
        for path in paths:
            for invalid in (None,[],True,'unknown'):
                bad=copy.deepcopy(base);target=bad
                for part in path[:-1]:target=target[part]
                target[path[-1]]=invalid
                with self.subTest(path=path,invalid=invalid):self.assertFalse(validation.verified(bad))
        for key in ('landlock_abi','external_provider_calls','production_state_writes'):
            for invalid in (False,True,None,'0',float('nan')):
                bad=copy.deepcopy(base);bad[key]=invalid
                with self.subTest(key=key,invalid=invalid):self.assertFalse(validation.verified(bad))
        for field in ('spawned','joined','zero_exit','successful','probe_successful','nonprobe_successful'):
            bad=copy.deepcopy(base);bad['child']['native_kernel_lifecycle']['executors']['history'][field]=True
            with self.subTest(field=field):self.assertFalse(validation.verified(bad))
        bad=copy.deepcopy(base);bad['child']['native_kernel_lifecycle']['executors']['decoder']['probe_successful']=3
        self.assertFalse(validation.verified(bad))
        for role in ('decoder','history'):
            bad=copy.deepcopy(base);worker=bad['child']['native_kernel_lifecycle']['executors'][role]
            worker['probe_successful']=worker['successful'];worker['nonprobe_successful']=0
            with self.subTest(probe_only=role):self.assertFalse(validation.verified(bad))

    def test_actual_fixed_copied_main_all_four_native_adapters_and_shutdown(self):
        import asyncio
        from tests.test_isolated_native_launcher import offline_software_approval
        from tests.test_provider_clock_domain import identity
        with Scratch() as scope,patch('meme_machine.runtime.provider_clock.current_identity',return_value=identity()):
            result=asyncio.run(validation._exercise(scope.path,offline_software_approval(),
                launcher=copied_seccomp_fixture))
            print(json.dumps(result,sort_keys=True))
            self.assertIs(result['kernel_applied'],False)
            self.assertFalse(validation.verified(result))
            self.assertEqual(result['status'],'BLOCKED')
            self.assertTrue(result['owned_process_reaped'] and result['parent_cleanup_joined'],result)
            self.assertEqual(result['child']['status'],'COMPLETED',result)
            self.assertTrue(result['child']['observation']['all_workers_joined'],result)
            self.assertTrue(all(result['native_outputs']['regimes'].values()),result)
            self.assertGreater(result['native_outputs']['canonical_full_ack'],0,result)
            self.assertGreater(result['native_outputs']['candidate_references'],0,result)
            self.assertTrue(result['native_outputs']['financial_tables_absent'],result)
            self.assertEqual(result['fixture_counters']['external_provider_calls'],0)
            self.assertFalse(result['financial_authority'])
            scope.check();scope.success=True


class NativeKernelRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests.test_provider_clock_domain import identity
        from meme_machine.operational.isolated_native_kernel_corpus import SolanaKernelCorpus
        from meme_machine.operational.isolated_native_kernel_parent import SyntheticParent
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.enterContext(patch('meme_machine.runtime.provider_clock.current_identity',return_value=identity()))
        self.parent=SyntheticParent(self.root,SolanaKernelCorpus(1000))
        self.addAsyncCleanup(self.parent.close)

    async def test_complete_registry_matches_actual_child_and_all_native_port_selectors(self):
        import asyncio,socket
        from meme_machine.operational.parent_channel import serve_connected
        from meme_machine.operational.child_transport import ChildChannel
        from meme_machine.operational.source_ports import native_reference
        from meme_machine.runtime.isolated_native_bootstrap import NativeRunnerPorts
        from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
        from tests.test_isolated_native_resources import authenticated,receipt
        parent,child=socket.socketpair()
        reader,writer=await asyncio.open_connection(sock=parent)
        serving=asyncio.create_task(serve_connected(reader,writer,self.parent.channel))
        channel=await asyncio.to_thread(ChildChannel,child)
        resources=IsolatedNativeResources(self.root/'private',sizing_facts=authenticated(receipt()),clock=lambda:1000)
        ports=NativeRunnerPorts(resources,channel)
        try:
            for lane in ('pump','pons'):
                for regime in ('current','survivor','discovery'):
                    self.assertEqual(ports.rpc_port(lane,regime).source.alias,lane+'-'+regime)
            for operation,expected in (('history_receipt','pump_history_receipt'),
                    ('recovery_restart','pump_recovery_restart'),('unattributed','pump_source_identity')):
                for priority in range(1,7):
                    source=ports.source_rpc(priority,operation=operation).source
                    self.assertEqual((source.operation,source.read_class),(expected,'solana_evidence_'+str(priority)))
            self.assertEqual(ports.source_config().identity,ports.rpc_port('pump','discovery').source.endpoint_identity)
            for transport,alias in (('yellowstone','yellowstone'),('solana_websocket','solana-websocket')):
                self.assertEqual(native_reference(channel,transport).alias,alias)
            await asyncio.to_thread(ports.require_pons_profiles)
            self.assertEqual(ports.require_pons_feed_source().alias,'pons-discovery')
            self.assertEqual([row['alias'] for row in channel.streams if row['transport']=='robinhood_sequencer'],
                ['pons-discovery'])
            self.assertEqual(self.parent.calls,0)
            self.assertEqual(self.parent.budget.snapshot()['native_opens'],'0')
        finally:
            ports.close();resources.close()
            await asyncio.to_thread(channel.close)
            await asyncio.wait_for(serving,3)

    async def test_registry_refuses_missing_duplicate_roles_source_or_stream_identity_and_method_change(self):
        from meme_machine.operational.isolated_native_kernel_parent import require_registry,KernelFixtureRefused
        from meme_machine.operational.parent_transport import NativeSourceBinding
        from meme_machine.operational.transport_bridge import EndpointAlias
        sources=dict(self.parent.http.sources);native=tuple(self.parent.channel.native_sources.values())
        require_registry(sources,native)
        for alias in sources:
            missing=dict(sources);del missing[alias]
            with self.subTest(missing=alias),self.assertRaises(KernelFixtureRefused):require_registry(missing,native)
        for alias in ('yellowstone','solana-websocket'):
            duplicate=dict(sources);duplicate[alias]=replace(sources[alias],operation='pump_discovery')
            with self.subTest(duplicate=alias),self.assertRaises(KernelFixtureRefused):require_registry(duplicate,native)
        foreign=dict(sources);foreign['pump-current']=replace(foreign['pump-current'],identity='0'*64)
        with self.assertRaises(KernelFixtureRefused):require_registry(foreign,native)
        widened=dict(sources);row=widened['pump-current']
        widened['pump-current']=replace(row,alias=EndpointAlias(row.alias.name,'solana',row.alias.methods-{'getSlot'}))
        with self.assertRaises(KernelFixtureRefused):require_registry(widened,native)
        for altered in (native[:-1],native+(native[0],),
                (NativeSourceBinding(replace(native[0].source),native[0].transport),)+native[1:]):
            with self.assertRaises(KernelFixtureRefused):require_registry(sources,altered)
        self.assertEqual(self.parent.calls,0)
        self.assertEqual(self.parent.budget.snapshot()['native_opens'],'0')


if __name__=='__main__':unittest.main()
