import urllib.error
import unittest

from meme_machine import solana_read_rpc as rpc_topology
from meme_machine.provider import Unavailable


ALCHEMY='https://solana-mainnet.g.alchemy.com/v2/example-key'
ONFINALITY='https://solana.api.onfinality.io/rpc?apikey=example-secret'


class Clock:
    def __init__(self):
        self.value=100.0
    def __call__(self):
        return self.value
    def sleep(self,seconds):
        self.value+=float(seconds)


class SolanaReadTopologyTests(unittest.TestCase):
    def test_no_secret_fallback_is_public_but_production_primary_is_alchemy(self):
        meta=rpc_topology.metadata({})
        self.assertEqual(meta['primary_provider'],rpc_topology.PUBLIC_HTTP_PROVIDER)
        self.assertTrue(meta['primary_public'])
        self.assertEqual(meta['minimum_request_interval_seconds'],0.5)
        self.assertFalse(meta['secondary_configured'])
        self.assertFalse(meta['fallback_allowed'])

        env={rpc_topology.ALCHEMY_ENV_NAME:ALCHEMY}
        meta=rpc_topology.metadata(env)
        self.assertEqual(meta['primary_provider'],rpc_topology.PRIMARY_PROVIDER)
        self.assertFalse(meta['primary_public'])
        self.assertEqual(meta['primary_credential'],rpc_topology.ALCHEMY_ENV_NAME)
        self.assertEqual(rpc_topology.primary_rpc_url(env),ALCHEMY)

    def test_onfinality_is_diagnostic_only_and_cannot_override_pump_http_primary(self):
        env={
            rpc_topology.ALCHEMY_ENV_NAME:ALCHEMY,
            rpc_topology.AUTHENTICATED_PRIMARY_ENV_NAME:ONFINALITY,
            rpc_topology.AUTHENTICATED_WS_ENV_NAME:
                'wss://solana.api.onfinality.io/ws?apikey=example-secret',
        }
        self.assertEqual(rpc_topology.primary_rpc_url(env),ALCHEMY)
        self.assertEqual(rpc_topology.onfinality_rpc_url(env,required=True),ONFINALITY)
        self.assertEqual(
            rpc_topology.primary_ws_url(env),
            env[rpc_topology.AUTHENTICATED_WS_ENV_NAME],
        )
        meta=rpc_topology.metadata(env)
        self.assertEqual(meta['onfinality_http_role'],'diagnostic_only_not_pump_evidence')
        self.assertNotIn('example-secret',str(meta))

    def test_shared_primary_pacer_enforces_half_second_across_rpc_objects(self):
        clock=Clock()
        pacer=rpc_topology.SolanaReadPacer()
        env={rpc_topology.ALCHEMY_ENV_NAME:ALCHEMY}
        first=rpc_topology.new_rpc(limit=40,pacer=pacer,environ=env,clock=clock,sleeper=clock.sleep)
        second=rpc_topology.new_rpc(limit=40,pacer=pacer,environ=env,clock=clock,sleeper=clock.sleep)
        urls=[]
        def request(url,request):
            urls.append(url)
            return {'jsonrpc':'2.0','id':request['id'],'result':123}
        first._request_url=request
        second._request_url=request
        self.assertEqual(first.call('getBlockTime',[1],priority=True),123)
        self.assertEqual(second.call('getBlockTime',[2],priority=True),123)
        self.assertAlmostEqual(clock.value,100.5,places=6)
        self.assertEqual(urls,[ALCHEMY,ALCHEMY])
        self.assertEqual(pacer.telemetry()['minimum_interval_seconds'],0.5)

    def test_alchemy_failure_fails_closed_without_hidden_rescue(self):
        env={rpc_topology.ALCHEMY_ENV_NAME:ALCHEMY}
        rpc=rpc_topology.new_rpc(limit=40,environ=env)
        calls=[]
        def fail(url,request):
            calls.append(url)
            raise urllib.error.HTTPError(url,429,'rate limited',{},None)
        rpc._request_url=fail
        with self.assertRaises(Unavailable):
            rpc.call('getGenesisHash',priority=True)
        self.assertTrue(calls)
        self.assertTrue(all(url==ALCHEMY for url in calls))
        self.assertEqual(rpc.failover_count,0)
        telemetry=rpc.provider_telemetry()
        self.assertEqual(telemetry['secondary_provider'],'none')
        self.assertFalse(telemetry['secondary_configured'])
        method_key=f"{rpc_topology.PRIMARY_PROVIDER}:getGenesisHash"
        status_key=f"{method_key}:429"
        self.assertEqual(telemetry['provider_method_failures'][method_key],2)
        self.assertEqual(telemetry['provider_http_status_errors'][status_key],2)
        self.assertEqual(
            telemetry['provider_error_fingerprints'][
                f"{rpc_topology.PRIMARY_PROVIDER}|getGenesisHash|http:429"
            ],
            2,
        )
        self.assertEqual(telemetry['last_provider_error']['http_status'],429)
        self.assertEqual(telemetry['last_provider_error']['method'],'getGenesisHash')

    def test_jsonrpc_error_code_is_attributed_to_method_without_message_or_url(self):
        env={rpc_topology.ALCHEMY_ENV_NAME:ALCHEMY}
        rpc=rpc_topology.new_rpc(limit=40,environ=env,sleeper=lambda _seconds:None)
        def fail(_url,request):
            return {
                'jsonrpc':'2.0','id':request['id'],
                'error':{'code':-32602,'message':'deliberately sensitive provider text'},
            }
        rpc._request_url=fail
        with self.assertRaises(Unavailable):
            rpc.call('getGenesisHash',priority=True)
        telemetry=rpc.provider_telemetry()
        method_key=f"{rpc_topology.PRIMARY_PROVIDER}:getGenesisHash"
        code_key=f"{method_key}:-32602"
        fingerprint=f"{rpc_topology.PRIMARY_PROVIDER}|getGenesisHash|jsonrpc:-32602"
        self.assertEqual(telemetry['provider_method_failures'][method_key],2)
        self.assertEqual(telemetry['provider_jsonrpc_error_codes'][code_key],2)
        self.assertEqual(telemetry['provider_error_fingerprints'][fingerprint],2)
        self.assertEqual(telemetry['last_provider_error']['jsonrpc_error_code'],-32602)
        self.assertNotIn('sensitive',str(telemetry))
        self.assertNotIn(ALCHEMY,str(telemetry))

    def test_shared_pacer_preserves_gettransaction_pressure_state(self):
        clock=Clock();pacer=rpc_topology.SolanaReadPacer()
        env={rpc_topology.ALCHEMY_ENV_NAME:ALCHEMY}
        rpc=rpc_topology.new_rpc(
            limit=80,pacer=pacer,environ=env,clock=clock,sleeper=clock.sleep)
        rounds={"n":0}
        def request(_url,request):
            rounds["n"]+=1
            if isinstance(request,list) and rounds["n"]==1:
                return [
                    {"jsonrpc":"2.0","id":x["id"],"error":{"code":429}}
                    for x in request
                ]
            return [
                {"jsonrpc":"2.0","id":x["id"],"result":{"slot":1,"meta":{"err":None,"logMessages":[]}}}
                for x in request
            ] if isinstance(request,list) else {"jsonrpc":"2.0","id":request["id"],"result":1}
        rpc._request_url=request
        params=[[f"s{i}",{"encoding":"json","maxSupportedTransactionVersion":1}] for i in range(8)]
        rpc.call_many("getTransaction",params,True,batch_size=8)
        self.assertEqual(pacer.gettransaction_batch_size,4)
        telemetry=rpc.provider_telemetry()["pacing"]
        self.assertEqual(telemetry["gettransaction_429_events"],8)
        second=rpc_topology.new_rpc(
            limit=80,pacer=pacer,environ=env,clock=clock,sleeper=clock.sleep)
        self.assertIs(second.read_pacer,pacer)
        self.assertEqual(second.read_pacer.gettransaction_batch_size,4)

if __name__=='__main__':
    unittest.main()
