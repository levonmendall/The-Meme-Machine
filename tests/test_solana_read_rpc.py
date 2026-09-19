import urllib.error
import unittest

from meme_machine import solana_read_rpc as rpc_topology


ALCHEMY='https://solana-mainnet.g.alchemy.com/v2/example-key'


class Clock:
    def __init__(self):
        self.value=100.0
    def __call__(self):
        return self.value
    def sleep(self,seconds):
        self.value+=float(seconds)


class SolanaReadTopologyTests(unittest.TestCase):
    def test_public_primary_is_five_requests_per_second_and_no_load_balancing(self):
        meta=rpc_topology.metadata({})
        self.assertEqual(meta['primary_provider'],rpc_topology.PRIMARY_PROVIDER)
        self.assertEqual(meta['minimum_request_interval_seconds'],0.2)
        self.assertFalse(meta['load_balancing'])
        self.assertFalse(meta['secondary_configured'])

    def test_shared_primary_pacer_enforces_point_two_seconds_across_rpc_objects(self):
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
        self.assertAlmostEqual(clock.value,100.2,places=6)
        self.assertEqual(urls,[rpc_topology.PRIMARY_RPC_URL,rpc_topology.PRIMARY_RPC_URL])
        self.assertEqual(pacer.telemetry()['minimum_interval_seconds'],0.2)

    def test_healthy_primary_never_spends_alchemy_and_failure_uses_rescue(self):
        env={rpc_topology.ALCHEMY_ENV_NAME:ALCHEMY}
        rpc=rpc_topology.new_rpc(limit=40,environ=env)
        calls=[]
        def healthy(url,request):
            calls.append(url)
            return {'jsonrpc':'2.0','id':request['id'],'result':'ok'}
        rpc._request_url=healthy
        self.assertEqual(rpc.call('getGenesisHash',priority=True),'ok')
        self.assertEqual(calls,[rpc_topology.PRIMARY_RPC_URL])
        self.assertEqual(rpc.failover_count,0)

        rpc2=rpc_topology.new_rpc(limit=40,environ=env)
        calls=[]
        def failover(url,request):
            calls.append(url)
            if url==rpc_topology.PRIMARY_RPC_URL:
                raise urllib.error.HTTPError(url,429,'rate limited',{},None)
            return {'jsonrpc':'2.0','id':request['id'],'result':'rescued'}
        rpc2._request_url=failover
        self.assertEqual(rpc2.call('getGenesisHash',priority=True),'rescued')
        self.assertEqual(calls,[rpc_topology.PRIMARY_RPC_URL,ALCHEMY])
        self.assertEqual(rpc2.calls,1)
        self.assertEqual(rpc2.http_requests,2)
        self.assertEqual(rpc2.failover_count,1)


if __name__=='__main__':
    unittest.main()
