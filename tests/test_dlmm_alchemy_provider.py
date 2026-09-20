"""Regression coverage for DLMM public-WS / direct-Alchemy Solana routing."""
import urllib.error
import unittest
from types import SimpleNamespace

from meme_machine.provider import Unavailable
from meme_machine import solana_read_rpc as topology
from tests import dlmm_alchemy_provider as provider


ALCHEMY="https://solana-mainnet.g.alchemy.com/v2/example-key"
ONFINALITY="https://solana.api.onfinality.io/rpc?apikey=ignored"
ONFINALITY_WS="wss://solana.api.onfinality.io/ws?apikey=ignored"
ENV={
    provider.ENV_NAME:ALCHEMY,
    topology.ONFINALITY_RPC_ENV_NAME:ONFINALITY,
    topology.ONFINALITY_WS_ENV_NAME:ONFINALITY_WS,
}


class _Clock:
    def __init__(self,now=100.0):
        self.now=float(now);self.sleeps=[]
    def time(self): return self.now
    def sleep(self,seconds):
        self.sleeps.append(float(seconds));self.now+=float(seconds)


class DLMMAlchemyTopologyTests(unittest.TestCase):
    def test_dlmm_uses_alchemy_directly_and_ignores_onfinality(self):
        self.assertEqual(provider.rpc_url(ENV),ALCHEMY)
        meta=provider.metadata(ENV)
        self.assertEqual(meta["topology"],"dlmm_public_ws_alchemy_http")
        self.assertEqual(meta["primary_provider"],topology.SECONDARY_PROVIDER)
        self.assertEqual(meta["primary_credential"],provider.ENV_NAME)
        self.assertIsNone(meta["secondary_provider"])
        self.assertFalse(meta["secondary_configured"])
        self.assertFalse(meta["fallback_allowed"])

    def test_alchemy_is_required(self):
        with self.assertRaisesRegex(Unavailable,"alchemy_rpc_missing"):
            provider.rpc_url({})

    def test_non_alchemy_routes_are_rejected(self):
        for value in (
            "https://api.mainnet-beta.solana.com",
            "https://solana.api.onfinality.io/rpc?apikey=key",
            "https://example.com/v2/key",
            "http://solana-mainnet.g.alchemy.com/v2/key",
            "https://solana-devnet.g.alchemy.com/v2/key",
        ):
            with self.subTest(value=value),self.assertRaises(Unavailable):
                provider.rpc_url({provider.ENV_NAME:value})

    def test_dlmm_five_rps_pacer(self):
        pacer=provider.AlchemyPacer()
        self.assertAlmostEqual(pacer.minimum_interval,0.2)
        meta=provider.metadata(ENV)
        self.assertEqual(meta["dlmm_primary_requests_per_second"],5)
        self.assertAlmostEqual(meta["dlmm_minimum_request_interval_seconds"],0.2)
        clock=_Clock()
        a=SimpleNamespace(clock=clock.time,sleep=clock.sleep,last_request=None)
        b=SimpleNamespace(clock=clock.time,sleep=clock.sleep,last_request=None)
        self.assertEqual(pacer.pace(a,0.0),0.0)
        self.assertAlmostEqual(pacer.pace(b,0.0),0.2)

    def test_rpc_calls_alchemy_once_without_failover(self):
        rpc=provider.new_rpc(limit=40,environ=ENV)
        calls=[]
        def request(url,request):
            calls.append(url)
            return {"jsonrpc":"2.0","id":request["id"],"result":"mainnet"}
        rpc._request_url=request
        self.assertEqual(rpc.call("getGenesisHash",priority=True),"mainnet")
        self.assertEqual(calls,[ALCHEMY])
        self.assertEqual(rpc.calls,1)
        self.assertEqual(rpc.http_requests,1)
        t=rpc.provider_telemetry()
        self.assertEqual(t["topology"],"dlmm_public_ws_alchemy_http")
        self.assertEqual(t["primary_provider"],topology.SECONDARY_PROVIDER)
        self.assertEqual(t["failover_count"],0)
        self.assertEqual(t["provider_http_requests"][topology.SECONDARY_PROVIDER],1)
        self.assertEqual(t["provider_successes"][topology.SECONDARY_PROVIDER],1)

    def test_point_two_second_single_and_batch_spacing(self):
        clock=_Clock()
        rpc=provider.new_rpc(
            limit=40,environ=ENV,clock=clock.time,sleeper=clock.sleep)
        def request(_url,body):
            if isinstance(body,list):
                return [{"jsonrpc":"2.0","id":item["id"],"result":{"slot":i}}
                        for i,item in enumerate(body)]
            return {"jsonrpc":"2.0","id":body["id"],"result":"mainnet"}
        rpc._request_url=request
        self.assertEqual(rpc.call("getGenesisHash",priority=True,fresh=True),"mainnet")
        self.assertEqual(rpc.call("getGenesisHash",priority=True,fresh=True),"mainnet")
        self.assertEqual(len(clock.sleeps),1)
        self.assertAlmostEqual(clock.sleeps[0],0.2)

        clock2=_Clock()
        rpc2=provider.new_rpc(
            limit=40,environ=ENV,clock=clock2.time,sleeper=clock2.sleep)
        rpc2._request_url=request
        params=[[f"sig-{i}",{"encoding":"json","commitment":"finalized"}]
                for i in range(8)]
        self.assertEqual(len(rpc2.call_many(
            "getTransaction",params,True,batch_size=4)),8)
        self.assertEqual(len(clock2.sleeps),1)
        self.assertAlmostEqual(clock2.sleeps[0],0.2)

    def test_signature_reads_use_one_second_method_cadence(self):
        clock=_Clock();pacer=provider.AlchemyPacer()
        rpc=provider.new_rpc(limit=240,pacer=pacer,environ=ENV,
                             clock=clock.time,sleeper=clock.sleep)
        rpc._request_url=lambda _url,request: {
            "jsonrpc":"2.0","id":request["id"],"result":[]}
        rpc.call("getSignaturesForAddress",["pool",{"limit":16,"commitment":"finalized"}],True)
        first=clock.now
        rpc.call("getSignaturesForAddress",["pool",{"limit":16,"commitment":"finalized","before":"x"}],True)
        self.assertGreaterEqual(clock.now-first,provider.DLMM_SIGNATURE_REQUEST_INTERVAL_SECONDS)

    def test_signature_429_installs_fifteen_second_shared_backoff(self):
        clock=_Clock();pacer=provider.AlchemyPacer()
        first=provider.new_rpc(limit=240,pacer=pacer,environ=ENV,
                               clock=clock,sleeper=clock.sleep)
        second=provider.new_rpc(limit=240,pacer=pacer,environ=ENV,
                                clock=clock,sleeper=clock.sleep)
        error=urllib.error.HTTPError(
            "https://example.invalid",429,"rate limited",{},None)
        cooldown=pacer.note_rate_limit(first,error,"getSignaturesForAddress")
        self.assertGreaterEqual(cooldown,provider.DLMM_SIGNATURE_429_MIN_BACKOFF_SECONDS)
        waited=pacer.pace(second,0.0)
        self.assertGreaterEqual(waited,provider.DLMM_SIGNATURE_429_MIN_BACKOFF_SECONDS)
        telemetry=pacer.telemetry()
        self.assertEqual(
            telemetry["method_rate_limit_events"]["getSignaturesForAddress"],1)

    def test_shared_pacer_serializes_rpc_objects(self):
        clock=_Clock();pacer=provider.AlchemyPacer(minimum_interval=1.0)
        a=SimpleNamespace(clock=clock.time,sleep=clock.sleep,last_request=None)
        b=SimpleNamespace(clock=clock.time,sleep=clock.sleep,last_request=None)
        self.assertEqual(pacer.pace(a,0.5),0.0)
        self.assertAlmostEqual(pacer.pace(b,0.5),1.0)
        self.assertEqual(clock.sleeps,[1.0])

    def test_429_cooldown_is_shared_across_rpc_sessions(self):
        clock=_Clock();pacer=provider.AlchemyPacer()
        first=SimpleNamespace(clock=clock.time,sleep=clock.sleep,last_request=None)
        second=SimpleNamespace(clock=clock.time,sleep=clock.sleep,last_request=None)
        error=urllib.error.HTTPError(
            "https://example.invalid",429,"rate limited",{},None)
        cooldown=pacer.note_rate_limit(first,error)
        self.assertGreaterEqual(cooldown,2.0)
        waited=pacer.pace(second,0.0)
        self.assertGreaterEqual(waited,2.0)
        telemetry=pacer.telemetry()
        self.assertEqual(telemetry["rate_limit_events"],1)
        self.assertGreaterEqual(
            telemetry["rate_limit_cooldown_seconds"],2.0)

    def test_repeated_429s_adapt_cooldown_and_successes_decay_streak(self):
        clock=_Clock();pacer=provider.AlchemyPacer()
        rpc=SimpleNamespace(clock=clock.time,sleep=clock.sleep,last_request=None)
        error=urllib.error.HTTPError(
            "https://example.invalid",429,"rate limited",{},None)
        first=pacer.note_rate_limit(rpc,error)
        second=pacer.note_rate_limit(rpc,error)
        self.assertGreaterEqual(second,first)
        self.assertGreaterEqual(pacer.rate_limit_streak,2)
        for _ in range(8):
            pacer.note_success()
        self.assertEqual(pacer.rate_limit_streak,1)

    def test_429_retry_wait_keeps_two_second_floor(self):
        error=urllib.error.HTTPError(
            "https://example.invalid",429,"rate limited",{},None)
        self.assertGreaterEqual(
            provider.AlchemyPoolScanRPC._retry_delay(error),
            provider.ALCHEMY_429_MIN_BACKOFF_SECONDS,
        )

    def test_new_rpc_objects_keep_independent_logical_budgets(self):
        pacer=provider.AlchemyPacer()
        first=provider.new_rpc(limit=240,pacer=pacer,environ=ENV,
            transport=lambda _request:{"result":"ok"})
        second=provider.new_rpc(limit=240,pacer=pacer,environ=ENV,
            transport=lambda _request:{"result":"ok"})
        self.assertIsNot(first,second)
        self.assertEqual(first.limit,240);self.assertEqual(second.limit,240)
        self.assertIs(first.read_pacer,second.read_pacer)


if __name__=="__main__":
    unittest.main()
