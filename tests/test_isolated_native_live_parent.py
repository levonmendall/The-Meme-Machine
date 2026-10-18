"""Real replay/native USD/anonymous IPC; offline sockets, no kernel/live claim."""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.operational import isolated_native_landlock_launcher as launcher
from meme_machine.operational import isolated_native_live_parent as live
from meme_machine.operational.isolated_native_live_scope import (
    LiveNativeScope,verify_live_scope,CLASSIFICATION,
)
from meme_machine.operational.isolated_native_image import encoded
from tests.test_isolated_native_launcher import approval,fixture_image
from tests import test_parent_sizing as sizing_fixtures
from tests import test_shared_portfolio_epoch as epoch_fixtures
from tests import test_parent_native_transport as transport_fixtures
from tests.test_robinhood_usd_valuation import NOW


def request(approved):
    value=approved.value()
    return dict(action='diagnose',request_id='offline-live-parent-component',
        application_commit=value['source_commit'],application_tree=value['source_tree'],
        administration_commit='c'*40,output='/var/lib/meme-machine-operations/offline/output')


def unit():
    return dict(MainPID=os.getpid(),invocation_id='d'*32,ExecMainStartTimestampMonotonic=1,NRestarts=0)


class ProtectedFinancialInputTests(unittest.TestCase):
    harness=epoch_fixtures.SharedEpochTests.harness

    def test_real_original_1000_epoch_replay_is_detached_and_callbacks_are_owner_bound(self):
        financial,state=sizing_fixtures.actual_snapshot(self.harness());before=deepcopy([financial,state]);calls=[]
        port=live.ProtectedFinancialInput(lambda:(financial,state),lambda:calls.append('validated') or True)
        detached=port.capture();detached[1]['initial_capital']='0'
        self.assertEqual(port.detached(),before)
        self.assertEqual(state['initial_capital'],'1000.00')
        failures=[]
        def foreign():
            try:port.validate()
            except BaseException as error:failures.append(error)
        owner=threading.Thread(target=foreign);owner.start();owner.join()
        self.assertIsInstance(failures[0],live.LiveParentRefused)
        self.assertEqual(str(failures[0]),'live_financial_owner')
        with self.assertRaisesRegex(ValueError,'one_snapshot'):port.capture()

    def test_false_scope_and_real_nonflat_replay_refuse_without_provider_construction(self):
        reads=[];port=live.ProtectedFinancialInput(lambda:reads.append(True),lambda:False)
        with self.assertRaisesRegex(ValueError,'scope_unverified'):port.capture()
        self.assertFalse(reads)
        financial,state=sizing_fixtures.actual_snapshot(self.harness());financial['obligations']['legacy_native_pending']=1
        with self.assertRaisesRegex(ValueError,'not_flat'):
            live.ProtectedFinancialInput(lambda:(financial,state),lambda:True).capture()


class LiveScopeTests(unittest.TestCase):
    def test_live_scope_has_exact_binding_original_growth_and_refuses_offline_launcher_path(self):
        from meme_machine.operational.namespace_canary import _scratch,Blocked
        approved=approval()
        with LiveNativeScope(request(approved),approved,unit_identity=unit(),validate_scope=lambda:True) as scope:
            marker=json.loads((scope.path/'engineering-artifact.json').read_bytes())
            self.assertEqual(marker['classification'],CLASSIFICATION)
            self.assertFalse(marker['financial_authority'])
            self.assertEqual(scope.require_launch(approved),scope.path)
            statement=scope.statement(approved)
            self.assertEqual(verify_live_scope(scope.path,statement,parent_pid=os.getpid(),approval=approved.value()),scope.path)
            with self.assertRaises(Blocked):_scratch(scope.path,os.getpid())
            bad=dict(statement,source_tree='f'*40)
            with self.assertRaisesRegex(ValueError,'source_binding'):
                verify_live_scope(scope.path,bad,parent_pid=os.getpid(),approval=approved.value())
            bad=dict(statement,marker_inode=statement['marker_inode']+1)
            with self.assertRaisesRegex(ValueError,'marker_changed'):
                verify_live_scope(scope.path,bad,parent_pid=os.getpid(),approval=approved.value())
            scope.check();scope.success=True

    def test_live_scope_marker_replacement_or_changed_host_scope_refuses(self):
        approved=approval();current=[True]
        with LiveNativeScope(request(approved),approved,unit_identity=unit(),validate_scope=lambda:current[0]) as scope:
            marker=scope.path/'engineering-artifact.json';raw=marker.read_bytes()
            marker.write_bytes(raw+b' ')
            with self.assertRaisesRegex(ValueError,'marker_changed'):scope.require_launch(approved)
            marker.write_bytes(raw)
            current[0]=False
            with self.assertRaisesRegex(ValueError,'host_fence'):scope.require_launch(approved)
            current[0]=True;scope.success=True

    def test_diagnostic_source_and_unit_are_fixed_not_a_path_or_action_selector(self):
        approved=approval()
        for bad in (dict(request(approved),action='start'),dict(request(approved),application_tree='f'*40),
                    dict(request(approved),selector='arbitrary')):
            with self.subTest(request=bad),self.assertRaises(ValueError):
                LiveNativeScope(bad,approved,unit_identity=unit(),validate_scope=lambda:True)
        with self.assertRaisesRegex(ValueError,'unit_binding'):
            LiveNativeScope(request(approved),approved,unit_identity=dict(unit(),MainPID=os.getpid()+1),validate_scope=lambda:True)

    def test_lost_fence_at_successful_exit_restores_original_temp_state_and_retains_tree(self):
        approved=approval();current=[True]
        previous=(tempfile.tempdir,os.environ.get('TMPDIR'))
        scope=LiveNativeScope(request(approved),approved,unit_identity=unit(),validate_scope=lambda:current[0])
        scope.__enter__();path=scope.path;scope.success=True;current[0]=False
        with self.assertRaisesRegex(ValueError,'host_fence'):scope.__exit__(None,None,None)
        self.assertEqual((tempfile.tempdir,os.environ.get('TMPDIR')),previous)
        self.assertTrue(scope._finished);self.assertTrue(path.exists())
        self.assertEqual(json.loads((path/'engineering-artifact.json').read_bytes())['status'],
            'FAILED_EVIDENCE_RETAINED')


class PreparedImageTests(unittest.TestCase):
    def test_one_shot_preparation_preserves_live_scope_and_original_child_image_checks(self):
        approved=approval()
        with LiveNativeScope(request(approved),approved,unit_identity=unit(),validate_scope=lambda:True) as scope:
            with patch.object(launcher.image,'build',side_effect=lambda path,value,profile:fixture_image(Path(path))) as build:
                prepared=launcher.prepare_native(scope.path,approved,scope_capability=scope)
            self.assertEqual(build.call_count,1)
            staged=prepared._take(scope.path,approved)
            self.assertEqual(staged['root'],scope.path/'native-image')
            self.assertIs(prepared._live_scope,scope)
            with self.assertRaisesRegex(launcher.image.Refused,'preparation_scope'):prepared._take(scope.path,approved)
            with self.assertRaises(AttributeError):prepared._used=False
            scope.success=True

    def test_changed_manifest_or_foreign_approval_cannot_consume_prebuilt_capability(self):
        approved=approval()
        with LiveNativeScope(request(approved),approved,unit_identity=unit(),validate_scope=lambda:True) as scope:
            with patch.object(launcher.image,'build',side_effect=lambda path,value,profile:fixture_image(Path(path))):
                prepared=launcher.prepare_native(scope.path,approved,scope_capability=scope)
            with self.assertRaisesRegex(launcher.image.Refused,'preparation_scope'):prepared._take(scope.path,approval())
            manifest=prepared._staged['root']/'manifest.json';manifest.chmod(0o600);manifest.write_bytes(b'{}')
            with self.assertRaisesRegex(launcher.image.Refused,'preparation_changed'):prepared._take(scope.path,approved)
            scope.success=True


class LiveParentIPCTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=sizing_fixtures.ParentSizingPortTests.asyncSetUp
    harness=epoch_fixtures.SharedEpochTests.harness

    def configured(self,scope=None):
        if scope is not None:
            from meme_machine.operational.bounded_provider import Budget
            from meme_machine.runtime.governor import Governor
            from meme_machine.lanes.pons.provider_admission import Admission
            root=scope.path/'parent';root.mkdir(mode=0o700)
            self.budget=Budget.create(root/'usage.sqlite')
            self.governor=Governor(root/'governor.sqlite')
            self.admission=Admission(root/'pons.sqlite',self.pons._url,lane='pons')
            self.physical.budget=self.budget
        else:root=self.root
        for path in (self.budget.path,self.governor.path,self.admission.path):Path(path).chmod(0o600)
        return live.LiveNativeParent(root,budget=self.budget,governor=self.governor,
            admission=self.admission,environ=dict(MM_SOLANA_READ_RPC_URL=self.sol._url,
                MM_ROBINHOOD_READ_RPC_URL=self.pons._url,MM_SOLANA_YELLOWSTONE_TOKEN='offline-only'))

    def prepare(self,path,approved,*,scope_capability):
        self.assertEqual(scope_capability.require_launch(approved),path)
        return object()  # Explicit offline orchestration dependency; never kernel evidence.

    def launch(self,path,approved,transport,facts,*,prepared):
        source=approved.value();self.launches+=1
        code=r'''
import json,os,signal,socket,sys,time
signal.signal(signal.SIGTERM,lambda *_stop:None) # Complete this fixture's accepted read/receipt.
sys.path.insert(0,sys.argv[1])
from meme_machine.operational.child_transport import ChildChannel,ChildRPCPort
from meme_machine.operational.isolated_native_entry import ParentSizingReader
from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
channel=ChildChannel(socket.socket(fileno=int(sys.argv[2])),seconds=30)
reader=ParentSizingReader(int(sys.argv[3]),session=channel.session,source_commit=sys.argv[4],
 source_tree=sys.argv[5],stopped=lambda:False)
facts=reader.receive();value=facts.value();now=int(sys.argv[6])
facts.require_fresh('pump',now);facts.require_fresh('pons',now)
assert value['lanes']['pump']['realized_equity']>0 and value['lanes']['pons']['realized_equity']>0
resources=IsolatedNativeResources(sys.argv[7]+'/private-native-child',sizing_facts=facts,clock=lambda:now)
assert resources.facts.value()['portfolio_sequence']==int(sys.argv[8])
assert resources.basis('pump',100)['target']>0 and resources.basis('pons',100)['target']>0
reply=ChildRPCPort(channel,'pump-discovery').envelope(dict(jsonrpc='2.0',id=1,method='getGenesisHash',params=[]))
assert reply['result']==sys.argv[9]
renewed=False
if sys.argv[10]=='renew':
 for _ in range(8):
  fresh=reader.receive(seconds=4)
  if fresh.value()['observed_at']>value['observed_at']:
   now=fresh.value()['observed_at'];resources.replace_authenticated_sizing_facts(fresh)
   assert resources.basis('pons',100)['target']>0
   assert fresh.value()['portfolio_sequence']==value['portfolio_sequence']
   renewed=True;break
 assert renewed
resources.close();reader.close();channel.close()
print(json.dumps(dict(status='COMPLETED',financial_authority=False,
 provenance='OFFLINE_IPC_SIZING_FIXTURE_NO_NATIVE_PIPELINES',normal_readiness=False,
 positive_native_sizing=True,genuine_renewal_observed=renewed,portfolio_sequence=value['portfolio_sequence'],
 observation=dict(all_workers_joined=True))),flush=True)
'''
        child=subprocess.Popen([sys.executable,'-I','-B','-S','-c',code,str(Path(__file__).resolve().parents[1]),
            str(transport.fileno()),str(facts),source['source_commit'],source['source_tree'],str(NOW),
            str(path),str(self.sequence),self.genesis,'renew' if getattr(self,'renew',False) else 'once'],
            env={},close_fds=True,pass_fds=(transport.fileno(),facts),
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        return launcher.NativeLandlockChild(child,time.monotonic())

    async def test_real_replay_positive_sizing_real_ipc_original_metering_and_joined_cleanup(self):
        self.launches=0
        financial,state=sizing_fixtures.actual_snapshot(self.harness());self.sequence=financial['combined_sequence']
        reader=live.ProtectedFinancialInput(lambda:(financial,state),lambda:True)
        approved=approval()
        with LiveNativeScope(request(approved),approved,unit_identity=unit(),validate_scope=lambda:True) as scope:
            parent=self.configured(scope)
            result=await parent._run(scope,approved,reader,seconds=.5,_prepare=self.prepare,
                _launch=self.launch,_opener=self.http.opener)
            (scope.path/'parent-result.json').write_text(json.dumps(result,sort_keys=True))
            self.assertTrue(parent.parent_owners_joined(),result)
            self.assertFalse(result['kernel_applied'],result)
            self.assertFalse(result['financial_authority'])
            self.assertFalse(result['normal_readiness'])
            self.assertIn('child',result,result)
            self.assertTrue(result['child'].get('positive_native_sizing'),result)
            self.assertEqual(result['child']['portfolio_sequence'],self.sequence)
            self.assertEqual(result['financial_before']['cash_usd'],'1000.00')
            self.assertEqual(result['budget_counters']['http_reserved'],0)
            self.assertEqual(result['budget_counters']['native_reserved'],0)
            self.assertGreater(result['budget_counters']['http_attempts'],0)
            self.assertEqual(self.launches,1)
            scope.success=True

    async def test_unverified_financial_scope_stops_before_image_or_provider_and_still_joins(self):
        approved=approval();reads=[]
        reader=live.ProtectedFinancialInput(lambda:reads.append(True),lambda:False)
        with LiveNativeScope(request(approved),approved,unit_identity=unit(),validate_scope=lambda:True) as scope:
            parent=self.configured(scope)
            result=await parent._run(scope,approved,reader,seconds=.1,_prepare=self.prepare)
            self.assertEqual(result['failure']['stage'],'financial_capture')
            self.assertEqual(result['failure']['error_class'],'LiveParentRefused')
            self.assertTrue(parent.parent_owners_joined())
            self.assertFalse(reads);self.assertFalse(self.physical.calls)
            scope.success=True

    async def test_real_quote_renewal_replaces_fd4_facts_without_changing_financial_sequence(self):
        self.renew=True;self.launches=0
        original=self.market.call
        def advancing(method,params,*,scope=None):
            if method=='eth_getBlockByNumber':
                number=0x4bdc170+(self.now[0]-NOW) if params[0]=='latest' else int(params[0],16)
                at=NOW+number-0x4bdc170
                return dict(number=hex(number),hash='0x'+hashlib.sha256(str(number).encode()).hexdigest(),timestamp=hex(at))
            return original(method,params,scope=scope)
        self.market.call=advancing
        financial,state=sizing_fixtures.actual_snapshot(self.harness());self.sequence=financial['combined_sequence']
        approved=approval();reader=live.ProtectedFinancialInput(lambda:(financial,state),lambda:True)
        with LiveNativeScope(request(approved),approved,unit_identity=unit(),validate_scope=lambda:True) as scope:
            parent=self.configured(scope)
            task=asyncio.create_task(parent._run(scope,approved,reader,seconds=8,
                _prepare=self.prepare,_launch=self.launch,_opener=self.http.opener))
            deadline=time.monotonic()+10
            while parent._publisher is None and not task.done() and time.monotonic()<deadline:await asyncio.sleep(.01)
            self.now[0]=NOW+1
            result=await task
            (scope.path/'parent-result.json').write_text(json.dumps(result,sort_keys=True))
            (scope.path/'offline-child-stderr.txt').write_bytes(bytes(parent._child.output['stderr']))
            (scope.path/'offline-child-exit.txt').write_text(str(parent._child.child.returncode))
            self.assertTrue(result['child'].get('genuine_renewal_observed'),result)
            self.assertGreaterEqual(result['sizing']['genuine_renewals'],1)
            self.assertTrue(parent.parent_owners_joined(),result)
            self.assertFalse(result['kernel_applied'])
            self.assertEqual(result['budget_counters']['http_reserved'],0)
            scope.success=True

    async def test_cancelled_real_accepted_provider_owner_joins_before_scope_release(self):
        approved=approval();financial,state=sizing_fixtures.actual_snapshot(self.harness())
        reader=live.ProtectedFinancialInput(lambda:(financial,state),lambda:True)
        with LiveNativeScope(request(approved),approved,unit_identity=unit(),validate_scope=lambda:True) as scope:
            parent=self.configured(scope);self.physical.gate.clear()
            task=asyncio.create_task(parent._run(scope,approved,reader,seconds=.1,
                _prepare=self.prepare,_opener=self.http.opener))
            self.assertTrue(await asyncio.to_thread(self.physical.entered.wait,2))
            task.cancel();await asyncio.sleep(.05)
            self.assertFalse(task.done())
            self.assertFalse(parent.parent_owners_joined())
            self.physical.gate.set()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue(parent.parent_owners_joined())
            self.assertEqual(self.budget.snapshot()['http_reserved'],'0')
            self.assertEqual(len(self.physical.calls),1)
            scope.success=True

    async def test_configured_registry_preserves_all_roles_priorities_and_actual_identities(self):
        from meme_machine.operational.isolated_native_kernel_parent import require_registry
        parent=self.configured();require_registry({row.alias.name:row for row in parent.sources},parent.native)
        self.assertEqual(len(parent.sources),26)
        self.assertEqual({row.identity for row in parent.sources if row.alias.family=='solana'},{self.sol.identity})
        self.assertEqual({row.identity for row in parent.sources if row.alias.family=='robinhood'},{self.pons.identity})
        bad=dict(MM_SOLANA_READ_RPC_URL=self.sol._url,MM_ROBINHOOD_READ_RPC_URL='https://foreign.invalid')
        with self.assertRaises(Exception):live._sources(bad,self.governor,self.admission)

    async def test_failed_native_close_drains_independent_http_ipc_and_sizing_owners_then_retains_first_cause(self):
        from meme_machine.operational.parent_channel import ParentChannel
        from meme_machine.operational.parent_transport import ParentHTTP,ParentNativeStream,validate_subscription
        from meme_machine.operational.pons_native_profile import ParentPonsProfiles
        parent=self.configured()
        class ClosingFailure(transport_fixtures._Native):
            async def aclose(self):
                self.closed=True
                raise OSError('private native close failure')
        raw=ClosingFailure()
        async def factory():return raw
        stream=await ParentNativeStream.open(self.budget,'yellowstone',factory,
            lambda body:validate_subscription('yellowstone',body))
        first=ParentHTTP(self.budget,parent.sources,opener=self.http.opener)
        second=ParentHTTP(self.budget,parent.sources,workers=1,opener=self.http.opener)
        parent._http=[first,second]
        bad=ParentChannel(first,streams={'yellowstone':stream})
        good=ParentChannel(second,workers=1,pons_profiles=ParentPonsProfiles.configured(second,environ={}))
        parent._channels=[bad,good]
        server,client=socket.socketpair();await parent._server(good,server)
        parent._sizing=live._SizingOwner(self.root,parent._stop,30)
        await parent._sizing.call(parent._sizing.connect,client)
        original=ValueError('original private source failure')
        result=dict(failure=dict(stage='original_source',error_class='ValueError'))
        with self.assertRaises(live.NativeOwnerDrainFailure) as caught:
            await parent._cleanup(None,None,None,None,result,original)
        self.assertIs(caught.exception.__cause__,original)
        self.assertIn(parent,caught.exception._retained)
        self.assertTrue(raw.closed and good.closed)
        self.assertTrue(all(task.done() for task in parent._servers))
        self.assertTrue(parent._sizing.joined)
        self.assertTrue(all(not thread.is_alive() for thread in parent._sizing.executor._threads))
        self.assertTrue(first._closed and second._closed)
        self.assertFalse(parent.parent_owners_joined())
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        self.assertGreater(int(self.budget.snapshot()['native_uncertain_bytes']),0)
        self.assertEqual(result['failure']['stage'],'original_source')


if __name__=='__main__':unittest.main()
