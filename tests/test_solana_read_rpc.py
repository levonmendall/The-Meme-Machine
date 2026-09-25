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

class SolanaAuthorityBoundaryTests(unittest.TestCase):
    def test_canonical_endpoint_derivation_and_strict_validation(self):
        from meme_machine.solana_provider_config import AlchemyEndpoint
        endpoint=AlchemyEndpoint.parse(ALCHEMY)
        self.assertEqual(endpoint.stream_url,ALCHEMY.replace('.g.', '.streaming.').replace('https:', 'wss:'))
        self.assertEqual(endpoint.identity,AlchemyEndpoint.parse(ALCHEMY.replace('.com/', '.com:443/')).identity)
        self.assertNotIn('example-key',repr(endpoint))
        for url in ('',ALCHEMY+'/',ALCHEMY+'?x=1',ALCHEMY+'#',ALCHEMY.replace('/v2/','//v2/'),
                    ALCHEMY.replace('mainnet','devnet'),ALCHEMY.replace('https','http'),
                    ALCHEMY.replace('example-key','a/b'),ALCHEMY.replace('example-key','%41key'),
                    ALCHEMY.replace('.com/','.com:bad/'),ALCHEMY+'\n',ONFINALITY):
            with self.subTest(kind=url.split('/')[0]),self.assertRaises(ValueError):AlchemyEndpoint.parse(url)

    def test_production_missing_endpoint_ignores_legacy_aliases_and_rejects_history(self):
        from unittest.mock import patch
        import os
        env={'MM_SOLANA_EVIDENCE_PLANE_DB':'offline.db','MM_ONFINALITY_SOLANA_RPC_URL':ONFINALITY,
             'MM_SOLANA_PUBLIC_RPC_URL':rpc_topology.PUBLIC_RPC_URL}
        with patch.dict(os.environ,env,clear=True):
            with self.assertRaises(Unavailable):rpc_topology.new_rpc()
            with self.assertRaises(Unavailable):rpc_topology.ReadOnlyFailoverRPC(rpc_topology.PUBLIC_RPC_URL)
            with self.assertRaises(Unavailable):rpc_topology.ReadOnlyFailoverRPC(ALCHEMY,secondary_url=ONFINALITY)
            rpc=rpc_topology.ReadOnlyFailoverRPC(ALCHEMY)
            with patch.object(rpc,'_provider_attempt') as attempt:
                for method in ('getSignaturesForAddress','getTransaction','getTransactionsForAddress','getBlock'):
                    with self.assertRaises(Unavailable):rpc._http(dict(method=method))
                attempt.assert_not_called()
                rpc._http(dict(method='getMultipleAccounts'))
                self.assertEqual(attempt.call_count,1)

    def test_http_error_and_payload_never_publish_credentials(self):
        from unittest.mock import patch,MagicMock
        import traceback
        from meme_machine.solana_provider_config import AlchemyEndpoint
        endpoint=AlchemyEndpoint.parse(ALCHEMY)
        with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError(ALCHEMY,429,ALCHEMY,{'Retry-After':'12'},None)):
            try:rpc_topology._ReadOnlyFailoverMixin._request_url(ALCHEMY,{'id':1})
            except urllib.error.HTTPError as exc:
                self.assertEqual(rpc_topology._ReadOnlyFailoverMixin._retry_delay(exc),12)
                diagnostic=traceback.format_exc()
                self.assertNotIn(endpoint.credential,diagnostic)
                self.assertNotIn(ALCHEMY,diagnostic)
        response=MagicMock();response.__enter__.return_value.read.return_value=(
            '{"result":"'+endpoint.credential+'"}').encode()
        with patch('urllib.request.urlopen',return_value=response):
            with self.assertRaises(Unavailable):rpc_topology._ReadOnlyFailoverMixin._request_url(ALCHEMY,{'id':1})

    def test_repair_transport_telemetry_and_identity_are_safe(self):
        from certification.evidence_worker import RepairRPC
        from unittest.mock import MagicMock,patch
        from meme_machine.solana_provider_config import GENESIS
        governor=MagicMock();rpc=RepairRPC(ALCHEMY,governor)
        response=MagicMock();response.__enter__.return_value.read.return_value=(
            '{"id":1,"result":"'+GENESIS+'"}').encode()
        with patch('urllib.request.urlopen',return_value=response):rpc.validate_network()
        with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError(ALCHEMY,429,ALCHEMY,{},None)):
            with self.assertRaises(ValueError):rpc.call('getTransactionsForAddress',[])
        result=rpc.telemetry()
        self.assertEqual(result['counters']['physical_requests'],2)
        self.assertEqual(result['counters']['429s'],1)
        self.assertEqual(result['estimated_alchemy']['unpriced_methods'],{'getTransactionsForAddress':1})
        self.assertNotIn('example-key',str(result))
        governor.rate_limited.assert_called_once()
