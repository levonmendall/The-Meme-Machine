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


if __name__=='__main__':
    unittest.main()
