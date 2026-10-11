"""Offline checks of the inactive read-only component and its purchase limits."""
from copy import deepcopy
from decimal import Decimal
import io
import json
import unittest
from unittest.mock import patch

from engineering.pump_first.check import Boundary,Stopped,CU,preflight,acquire,main
from meme_machine.lanes.pump.provider import RPC
from meme_machine.lanes.pump.pumpswap_survivor_evidence import SOL_USD_ACCOUNT
from tests.lanes.pump.test_postgrad_read_efficiency import MeteredRPC,MINT


class Clock:
    def __init__(self):self.at=0.
    def monotonic(self):return self.at
    def wall(self):return 101+self.at
    def sleep(self,seconds):self.at+=seconds


def account():
    return dict(app_id='9bin99s96t7ga5e9',network='SOLANA_MAINNET',
        evidence_kind='AUTHENTICATED_ACCOUNT_RECORD',runtime_application_binding_verified=True,
        shared_obligations_reserved=True,account_source='OFFLINE_SYNTHETIC_FIXTURE',plan='fixture',
        payg_enabled=True,capacity_observed_at_unix=100,reserved_cu=160,
        available_cu_per_ten_seconds=160,reserved_physical_rps=2,maximum_inflight=1,
        maximum_response_bytes=2_000_000,reserved_usd='.01',tariff=dict(source='offline fixture',
            charged_failures_included=True,exceptional_charges_included=True,
            method_max_cu=CU,method_max_usd={m:'.00002' for m in CU},
            fixed_max_usd='0',start_max_usd='0',byte_max_usd='0'))


class PumpFirstCheck(unittest.TestCase):
    def fixture(self,*,edit=None,delay=0):
        from tests.lanes.pump.test_pumpswap_survivor_evidence import EvidenceTests
        clock=Clock();native=MeteredRPC();calls=[]
        def opener(request,timeout):
            call=json.loads(request.data);calls.append((clock.at,call));clock.sleep(delay)
            if call['method']=='getMultipleAccounts' and call['params'][0]==[SOL_USD_ACCOUNT]:
                value=dict(context=dict(slot=1000),value=[EvidenceTests().oracle()])
            else:value=native.call(call['method'],call['params'],True)
            reply=dict(jsonrpc='2.0',id=call['id'],result=value)
            if edit:reply=edit(reply)
            return io.BytesIO(json.dumps(reply).encode())
        boundary=Boundary('https://offline.invalid', {m:Decimal('.00002') for m in CU},Decimal(0),
            expires=116,opener=opener,clock=clock.monotonic,wall=clock.wall,sleep=clock.sleep)
        rpc=RPC('https://offline.invalid',limit=40,transport=boundary.transport,
            clock=clock.wall,sleeper=clock.sleep)
        return clock,native,calls,boundary,rpc

    def test_default_does_not_read_configuration_or_open_provider(self):
        with (patch('engineering.pump_first.check.protected',side_effect=AssertionError('no configuration')),
              patch('engineering.pump_first.check.build_opener',side_effect=AssertionError('no network'))):
            self.assertEqual(main([]),0)

    def test_ci_cannot_dispatch_an_execute_invocation(self):
        with patch.dict('os.environ',CI='true'),patch('engineering.pump_first.check.protected',side_effect=AssertionError('no configuration')):
            with self.assertRaises(SystemExit):main(['--execute'])

    def test_native_cold_and_warm_quantity_quotes_and_real_decoder(self):
        clock,native,calls,boundary,rpc=self.fixture()
        with patch('time.time',side_effect=clock.wall):result=acquire(rpc,boundary,MINT)
        self.assertEqual(boundary.starts,7)
        self.assertEqual(boundary.methods,dict(getGenesisHash=1,getMultipleAccounts=4,getBlockTime=2))
        self.assertEqual(boundary.receipt()['modeled_cu'],130)
        self.assertTrue(all(b[0]-a[0]>=.5 for a,b in zip(calls,calls[1:])))
        self.assertFalse(result['paper_ready']);self.assertFalse(result['complete_protection_proven'])
        cold,warm=result['native_samples']
        self.assertEqual(cold['buy'],warm['buy']);self.assertEqual(cold['full_sell'],warm['full_sell'])
        self.assertEqual(cold['partial_sell'],warm['partial_sell'])
        self.assertLessEqual(clock.at,15)
        self.assertTrue(all(s['elapsed_seconds']<=5 for s in result['native_samples']))
        self.assertEqual(result['usd']['valid_until'],220)

    def test_non_swap_reserve_change_still_changes_the_fresh_warm_sell_value(self):
        from tests.lanes.pump.test_postgrad import token_account,WSOL
        reads=0
        def edit(reply):
            nonlocal reads
            value=reply['result']
            if isinstance(value,dict) and len(value.get('value',[]))==6:
                reads+=1
                if reads==2:
                    reply=deepcopy(reply)
                    reply['result']['value'][3]=token_account(WSOL,native.pool,30_000_000_000)
                    reply['result']['context']['slot']=1002
            return reply
        clock,native,_,b,rpc=self.fixture(edit=edit)
        with patch('time.time',side_effect=clock.wall):result=acquire(rpc,b,MINT)
        cold,warm=result['native_samples']
        self.assertLess(warm['full_sell']['output_amount'],cold['full_sell']['output_amount'])
        self.assertEqual(b.starts,7)

    def test_response_error_id_null_and_transport_failure_never_retry(self):
        for edit in (lambda r:dict(r,error={'code':429}),lambda r:dict(r,id=999),
                     lambda r:dict(r,result=None),lambda r:[]):
            with self.subTest(edit=edit):
                _,_,calls,b,rpc=self.fixture(edit=edit)
                with self.assertRaises(Stopped):rpc.call('getGenesisHash',priority=True)
                self.assertEqual(len(calls),1);self.assertEqual(rpc.retries,0)
                with self.assertRaises(Stopped):rpc.call('getGenesisHash',priority=True)
                self.assertEqual(len(calls),1)
        _,_,_,b,rpc=self.fixture()
        b.opener=lambda *_a,**_kw:(_ for _ in ()).throw(TimeoutError())
        with self.assertRaises(Stopped):rpc.call('getGenesisHash',priority=True)
        self.assertEqual(b.starts,1);self.assertEqual(rpc.retries,0)

    def test_request_and_method_caps_stop_before_dispatch(self):
        _,_,calls,b,_=self.fixture()
        for n in range(8):b.transport(dict(jsonrpc='2.0',id=n,method='getGenesisHash',params=[]))
        with self.assertRaises(Stopped):b.transport(dict(jsonrpc='2.0',id=9,method='getGenesisHash',params=[]))
        self.assertEqual(len(calls),8)
        _,_,calls,b,_=self.fixture()
        with self.assertRaises(Stopped):b.transport(dict(method='getTransaction'))
        self.assertEqual(calls,[])

    def test_hard_time_and_spend_stop_before_dispatch(self):
        for resource in ('time','spend','concurrency'):
            with self.subTest(resource=resource):
                clock,_,calls,b,_=self.fixture()
                if resource=='time':clock.at=15
                elif resource=='spend':b.spending=Decimal('.01')
                else:b.active=True
                with self.assertRaises(Stopped):b.transport(dict(jsonrpc='2.0',id=1,method='getGenesisHash'))
                self.assertEqual(calls,[])

    def test_quote_deadline_and_stale_oracle_cannot_publish_component_pass(self):
        for delay in (3,21):
            with self.subTest(delay=delay):
                clock,_,_,b,rpc=self.fixture(delay=delay)
                with patch('time.time',side_effect=clock.wall),self.assertRaises((Stopped,ValueError)):
                    acquire(rpc,b,MINT)
        clock,_,_,b,rpc=self.fixture()
        with patch('time.time',return_value=221),self.assertRaises(ValueError):acquire(rpc,b,MINT)

    def test_response_and_aggregate_bytes_remain_bounded(self):
        _,_,_,b,_=self.fixture()
        b.opener=lambda *_args,**_kw:io.BytesIO(b'x'*2_000_001)
        with self.assertRaises(Stopped):b.transport(dict(jsonrpc='2.0',id=1,method='getGenesisHash',params=[]))
        self.assertEqual(b.bytes,2_000_000)
        self.assertFalse(b.active)
        _,_,_,b,_=self.fixture();b.bytes=4*1024**2-1
        with self.assertRaises(Stopped):b.transport(dict(jsonrpc='2.0',id=1,method='getGenesisHash',params=[]))
        self.assertEqual(b.bytes,4*1024**2)

    def test_unverified_tariff_binding_capacity_or_high_charge_refuses(self):
        self.assertLess(preflight(account(),now=101)[2],Decimal('.01'))
        for field,value in [('runtime_application_binding_verified',False),('payg_enabled',None),
                ('capacity_observed_at_unix',0),('reserved_cu',159),('reserved_usd',None),
                ('shared_obligations_reserved',False)]:
            with self.subTest(field=field):
                row=deepcopy(account());row[field]=value
                check_time=401 if field=='capacity_observed_at_unix' else 101
                with self.assertRaises(ValueError):preflight(row,now=check_time)
        row=deepcopy(account());row['tariff']['method_max_usd']['getMultipleAccounts']='1'
        with self.assertRaises(ValueError):preflight(row,now=101)
        row=deepcopy(account());row['tariff']['charged_failures_included']=False
        with self.assertRaises(ValueError):preflight(row,now=101)
