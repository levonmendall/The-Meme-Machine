"""Failed-run limit reproduction and SDK headroom; all providers are offline."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational.bounded_provider import Budget,CeilingReached,DeliveredResponse,MAX_FRAME

MIB=1024**2
LIMITS=dict(rpc_cu=150000,rpc_elements=1800,http_attempts=1200,http_bytes=128*MIB,
    native_bytes=1024*MIB,native_stop_bytes=512*MIB,native_inflight_bytes=512*MIB)


def observation_file(root,budget):
    state=budget.snapshot()
    row=dict(schema='bounded-provider-observation-v1',limits=budget.limits,
        wall_seconds=budget.seconds,modeled_spend_limit=state['modeled_spend_limit'],
        maximum_native_opens=int(state['reconnect_limit']),lanes=['pump'])
    path=Path(root)/'observation-envelope.json';path.write_text(json.dumps(row))
    return path


class ProviderPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'usage.sqlite'
        self.budget=Budget.create(self.path,limits=LIMITS,wall_seconds=900,
            modeled_spend_limit='0.20',maximum_native_opens=8)
        self.file=observation_file(self.root,self.budget)

    def test_persisted_custom_envelope_and_restart_preserve_consumption_and_clocks(self):
        preflight=self.budget.preflight_file(self.file)
        self.assertEqual(preflight['limits'],LIMITS);self.assertEqual(preflight['lanes'],['pump'])
        response=self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        with DeliveredResponse(io.BytesIO(b'authentic-fixture-shape'),response) as r:r.read()
        before=self.budget.snapshot()
        self.assertEqual(before['rpc_cu'],'20');self.assertEqual(before['http_reserved'],'0')
        resumed=Budget(self.path);resumed.preflight_file(self.file)
        self.assertEqual(resumed.snapshot(),before);self.assertEqual(resumed.limits,LIMITS)
        with self.assertRaises(FileExistsError):Budget.create(self.path,limits=LIMITS)
        self.assertEqual(resumed.snapshot(),before)

    def test_original_absent_limits_row_never_substitutes_defaults(self):
        self.budget.change(dict(rpc_cu=20))
        with self.budget.db() as db:db.execute("DELETE FROM run WHERE key='limits'")
        with self.assertRaisesRegex(CeilingReached,'configuration_unverified'):Budget(self.path)
        with self.budget.db() as db:
            state=dict(db.execute('SELECT key,value FROM run'))
        self.assertEqual(state['rpc_cu'],'20');self.assertNotIn('limits',state)
        self.assertEqual(state['reason'],'bounded_provider_configuration_unverified')

    def test_missing_or_mismatched_observation_file_prevents_transport_installation(self):
        from meme_machine.operational.bounded_provider import install
        before=self.budget.snapshot()
        with patch.dict(os.environ,MM_BOUNDED_PROVIDER_DB=str(self.path),MM_BOUNDED_PROVIDER_ENVELOPE=''), \
                patch('urllib.request.urlopen') as network:
            with self.assertRaisesRegex(CeilingReached,'envelope_unverified'):install()
        network.assert_not_called()
        after=self.budget.snapshot()
        for key in before.keys()-{'reason'}:self.assertEqual(after[key],before[key])
        self.assertTrue(after['reason'])

    def test_missing_invalid_or_changed_configuration_is_durable_before_dispatch(self):
        before=self.budget.snapshot()
        for key,value in [('limits','{}'),('limits','null'),('wall_seconds','-1'),
                ('modeled_spend_limit','NaN'),('reconnect_limit','0'),('started_wall','nan')]:
            with self.subTest(key=key,value=value):
                path=self.root/(key+value.replace('/','_')+'.sqlite')
                b=Budget.create(path,limits=LIMITS)
                with b.db() as db:db.execute('UPDATE run SET value=? WHERE key=?',(value,key))
                with self.assertRaises(CeilingReached):Budget(path)
                with b.db() as db:state=dict(db.execute('SELECT key,value FROM run'))
                self.assertEqual(state['http_attempts'],'0');self.assertTrue(state['reason'])
        # A live instance checks the persisted envelope before its next request.
        with self.budget.db() as db:db.execute("UPDATE run SET value='1' WHERE key='modeled_spend_limit'")
        with self.assertRaisesRegex(CeilingReached,'configuration_changed'):
            self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        self.assertEqual(self.budget.snapshot()['http_attempts'],before['http_attempts'])

    def test_accounted_512_mib_stop_includes_active_and_uncertain_sdk_buffers(self):
        tokens=[self.budget.stream_open('yellowstone'),self.budget.stream_open('solana_websocket')]
        observed_stop=False
        for _ in range(40):
            try:self.budget.native('yellowstone',MAX_FRAME,token=tokens[0])
            except CeilingReached as error:
                self.assertEqual(error.reason,'native_payload_stop');observed_stop=True;break
        self.assertTrue(observed_stop)
        def accounted():
            row=self.budget.snapshot()
            return sum(int(row[k]) for k in ('native_bytes','native_uncertain_bytes','native_reserved'))
        stopping=accounted();self.assertLessEqual(stopping,512*MIB)
        # One already received tail replaces its reserved buffer exactly.
        with self.assertRaises(CeilingReached):self.budget.native('yellowstone',MAX_FRAME,token=tokens[0])
        self.assertEqual(accounted(),stopping)
        for token in tokens:
            self.budget.stream_close(token,unread_possible=True)
            self.budget.stream_close(token,unread_possible=True)
        self.assertEqual(accounted(),stopping);self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        before=self.budget.snapshot()
        with self.assertRaises(CeilingReached):Budget(self.path).preflight_file(self.file)
        with self.assertRaises(CeilingReached):self.budget.stream_open('yellowstone')
        self.assertEqual(self.budget.snapshot(),before)

    def test_stream_cannot_open_without_its_full_stop_and_next_frame_reservation(self):
        self.budget.change(dict(native_bytes=450*MIB))
        before=self.budget.snapshot()
        with self.assertRaisesRegex(CeilingReached,'native_inflight_limit'):self.budget.stream_open('solana_websocket')
        after=self.budget.snapshot()
        for key in ('http_attempts','native_opens','native_reserved','native_bytes'):
            self.assertEqual(after[key],before[key])

    def test_restart_reaps_lost_buffers_once_and_preserves_live_peers(self):
        self.budget.stream_open('yellowstone')
        self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        live=self.budget.snapshot();Budget(self.path).preflight_file(self.file)
        self.assertEqual(self.budget.snapshot(),live)
        with patch('meme_machine.shared_capital.runtime.process_identity',side_effect=OSError):
            resumed=Budget(self.path);resumed.preflight_file(self.file);resumed.preflight_file(self.file)
        after=self.budget.snapshot()
        self.assertEqual(after['native_uncertain_bytes'],str(2*MAX_FRAME))
        self.assertEqual(after['http_uncertain_bytes'],str(MAX_FRAME))
        self.assertEqual(after['native_reserved'],'0');self.assertEqual(after['http_reserved'],'0')
        for key in ('rpc_cu','http_attempts','native_opens','started','started_wall'):
            self.assertEqual(after[key],live[key])

    def test_http_error_and_unknown_tail_consume_existing_response_reservation(self):
        receipt=self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        with DeliveredResponse(io.BytesIO(b'12345'),receipt) as response:
            self.assertEqual(response.read(2),b'12')
        after=self.budget.snapshot()
        self.assertEqual(after['http_bytes'],'2');self.assertEqual(after['http_uncertain_bytes'],str(MAX_FRAME-2))
        self.assertEqual(after['http_reserved'],'0');self.assertEqual(after['rpc_elements'],'1')
        receipt.close();self.assertEqual(self.budget.snapshot(),after)

    def test_failure_between_http_reservation_and_dispatch_closes_receipt(self):
        import urllib.request
        from meme_machine.operational.bounded_provider import install
        with patch.dict(os.environ,MM_BOUNDED_PROVIDER_DB=str(self.path),MM_BOUNDED_PROVIDER_ENVELOPE=str(self.file)), \
                patch('urllib.request.urlopen'),patch('urllib.request.build_opener') as opener, \
                patch('meme_machine.lanes.pons.provider.urlopen'), \
                patch('grpc.aio.secure_channel'),patch('meme_machine.solana_selective_source.connect'):
            install()
            with patch.object(Budget,'admission',side_effect=CeilingReached('bounded_run_wall_limit')):
                with self.assertRaises(CeilingReached):
                    urllib.request.urlopen(urllib.request.Request(
                        'https://solana-mainnet.g.alchemy.com/v2/offline',
                        data=json.dumps(dict(method='getSlot')).encode()))
            opener.return_value.open.assert_not_called()
        row=self.budget.snapshot();self.assertEqual(row['http_reserved'],'0')
        self.assertEqual(row['http_uncertain_bytes'],str(MAX_FRAME))
        self.assertEqual(row['rpc_cu'],'20')

    def test_first_failure_survives_expiration_without_replenishment(self):
        self.budget.change(reason='original_stream_failure',check=False);before=self.budget.snapshot()
        with patch('time.monotonic',return_value=self.budget.started+901):
            with self.assertRaisesRegex(CeilingReached,'original_stream_failure'):Budget(self.path).admission()
        self.assertEqual(self.budget.snapshot(),before)

    def test_invalid_custom_create_allocates_no_allowance(self):
        for key,value in [('native_stop_bytes',2*1024**3),('native_inflight_bytes',1024*MIB),('http_bytes',True)]:
            limits=deepcopy(LIMITS);limits[key]=value
            path=self.root/(key+'.sqlite')
            with self.assertRaises(ValueError):Budget.create(path,limits=limits)
            self.assertFalse(path.exists())

    def test_concurrent_stream_open_counts_and_limits_are_shared_not_reset(self):
        from concurrent.futures import ThreadPoolExecutor
        path=self.root/'concurrent.sqlite'
        Budget.create(path,limits=LIMITS,maximum_native_opens=2)
        def opened(_):
            try:return Budget(path).stream_open('yellowstone')
            except CeilingReached:return None
        with ThreadPoolExecutor(max_workers=4) as pool:tokens=list(pool.map(opened,range(4)))
        self.assertEqual(len([t for t in tokens if t]),2)
        row=Budget(path).snapshot();self.assertEqual(row['native_opens'],'2')
        self.assertEqual(row['http_attempts'],'2');self.assertEqual(row['native_reserved'],str(4*MAX_FRAME))
        self.assertTrue(row['reason'])

    def test_pump_only_observation_cannot_hide_foreign_protection_obligations(self):
        from types import SimpleNamespace
        from meme_machine.operational.supervisor import Supervisor
        state=dict(runtime_admission={},positions={'foreign':dict(status='OPEN',regime='pons_survivor')})
        authority=SimpleNamespace(ledger=lambda:deepcopy(state))
        service=Supervisor(self.root,offline=True,admission='OBSERVATION');service.shared_capital=authority
        with patch.dict(os.environ,MM_BOUNDED_PROVIDER_DB=str(self.path),MM_BOUNDED_PROVIDER_ENVELOPE=str(self.file)):
            with self.assertRaisesRegex(CeilingReached,'cannot_omit_existing_owner'):service.configure_admission()
        self.assertEqual(state['positions']['foreign']['status'],'OPEN')
        self.assertEqual(self.budget.snapshot()['http_attempts'],'0')

    def test_inactive_window_preparation_cannot_repair_an_unverified_resource_envelope(self):
        from meme_machine.operational.bounded_provider import PhaseBudget
        from meme_machine.operational.exceptional_window import prepare
        from tests.test_position_continuation import envelope
        path=self.root/'continuation.sqlite';Budget.create(path,continuation=envelope())
        b=PhaseBudget(path)
        with b.bootstrap.db() as db:
            db.execute("UPDATE run SET value='1' WHERE key='continuation.modeled_spend_limit'")
        with self.assertRaisesRegex(ValueError,'resource_configuration_unverified'):
            prepare(b,maintenance_until=int(b.bootstrap.started_wall)+3600)
        with b.bootstrap.db() as db:row=dict(db.execute('SELECT key,value FROM run'))
        self.assertNotIn('exceptional_operational_window',row)
        self.assertEqual(row['continuation.modeled_spend_limit'],'1')
        self.assertEqual(row['continuation.wall_seconds'],str(envelope()['maximum_seconds']))

if __name__=='__main__':unittest.main()
