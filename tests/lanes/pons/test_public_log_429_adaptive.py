from email.message import Message
from urllib.error import HTTPError
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.provider import Rpc
from meme_machine.lanes.pons.provider_topology import ObservationFallbackRpc, ProviderPacer


class Clock:
    def __init__(self):
        self.now=0.0
    def time(self):
        return self.now
    def sleep(self,seconds):
        self.now+=float(seconds)


class Recovery:
    def __init__(self):
        self.calls=[]
    def call(self,method,params,scope="connectivity"):
        self.calls.append((method,params,scope))
        return [{"recovered":True}]
    def telemetry(self):
        return {"calls":len(self.calls)}


class PublicLog429AdaptiveTests(unittest.TestCase):
    def rpc(self,transport,recovery=None,limit=100):
        clock=Clock()
        pacer=ProviderPacer(2.0,clock=clock.time,sleeper=clock.sleep)
        rpc=ObservationFallbackRpc(
            "https://rpc.mainnet.chain.robinhood.com",
            role="pons_discovery_public_observation",
            requests_per_second=2.0,
            pacer=pacer,
            recovery_rpc=recovery,
            transport=transport,
            retries=0,limit=limit,per_scope=limit,
        )
        return rpc,clock

    def test_public_log_429_retries_identical_range_once_before_recovery(self):
        calls=[]
        def transport(method,params):
            calls.append((method,params))
            if len(calls)==1:
                raise BoundaryError("provider_http_429")
            return [{"ok":True}]
        recovery=Recovery();rpc,clock=self.rpc(transport,recovery)
        params=[{"fromBlock":"0x10","toBlock":"0x19","topics":[["0xaa"]]}]
        result=rpc.call("eth_getLogs",params,scope="pons_natural")
        self.assertEqual(result,[{"ok":True}])
        self.assertEqual(calls,[("eth_getLogs",params),("eth_getLogs",params)])
        self.assertEqual(recovery.calls,[])
        ctl=rpc.telemetry()["public_eth_getLogs_429_control"]
        self.assertEqual(ctl["public_429s"],1)
        self.assertEqual(ctl["same_endpoint_retry_successes"],1)
        self.assertEqual(ctl["alchemy_exact_range_recoveries"],0)
        self.assertAlmostEqual(ctl["cooldown_seconds"],0.6)
        self.assertEqual(ctl["effective_requests_per_second"],1.5)

    def test_second_429_uses_exact_alchemy_recovery_once(self):
        calls=[]
        def transport(method,params):
            calls.append((method,params))
            raise BoundaryError("provider_http_429")
        recovery=Recovery();rpc,_=self.rpc(transport,recovery)
        params=[{"fromBlock":"0x20","toBlock":"0x29","topics":[["0xbb"]]}]
        result=rpc.call("eth_getLogs",params,scope="pons_natural")
        self.assertEqual(result,[{"recovered":True}])
        self.assertEqual(calls,[("eth_getLogs",params),("eth_getLogs",params)])
        self.assertEqual(recovery.calls,[("eth_getLogs",params,"pons_natural")])
        ctl=rpc.telemetry()["public_eth_getLogs_429_control"]
        self.assertEqual(ctl["same_endpoint_retry_failures"],1)
        self.assertEqual(ctl["alchemy_exact_range_recoveries"],1)
        self.assertEqual(ctl["unrecovered_ranges"],0)

    def test_non_log_429_keeps_existing_direct_recovery_without_retry(self):
        calls=[]
        def transport(method,params):
            calls.append((method,params))
            raise BoundaryError("provider_http_429")
        recovery=Recovery();rpc,_=self.rpc(transport,recovery)
        rpc.call("eth_getBlockByNumber",["0x20",False],scope="pons_natural")
        self.assertEqual(len(calls),1)
        self.assertEqual(len(recovery.calls),1)
        self.assertEqual(rpc.telemetry()["public_eth_getLogs_429_control"]["public_429s"],0)

    def test_twenty_public_log_successes_cautiously_recover_rate(self):
        attempts=[0]
        def transport(method,params):
            attempts[0]+=1
            if attempts[0]==1:
                raise BoundaryError("provider_http_429")
            return []
        rpc,_=self.rpc(transport)
        params=[{"fromBlock":"0x1","toBlock":"0x1","topics":[]}]
        rpc.call("eth_getLogs",params)
        self.assertEqual(rpc.pacer.requests_per_second,1.5)
        for _ in range(19):
            rpc.call("eth_getLogs",params)
        self.assertAlmostEqual(rpc.pacer.requests_per_second,1.6)
        self.assertLessEqual(rpc.pacer.requests_per_second,2.0)

    def test_retry_after_header_is_captured_only_when_short(self):
        for header,expected in (("0.25",0.25),("5",None),("invalid",None)):
            headers=Message();headers["Retry-After"]=header
            error=HTTPError("https://redacted.invalid",429,"rate",headers,None)
            rpc=Rpc("https://example.invalid",limit=40,retries=0)
            with self.subTest(header=header),patch(
                    "meme_machine.lanes.pons.provider.urlopen",side_effect=error):
                with self.assertRaisesRegex(BoundaryError,"provider_http_429"):
                    rpc._http("eth_getLogs",[{}])
                self.assertEqual(rpc.last_retry_after_seconds,expected)


if __name__=="__main__":
    unittest.main()
