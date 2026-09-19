from collections import Counter
from dataclasses import replace
import base64
import hashlib
import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch

from robinhood_research import BoundaryError
from robinhood_research.abi import calldata
from robinhood_research.evidence import Stamp, Store
from robinhood_research.finality import Finality
from robinhood_research.paper import Quote
from robinhood_research.pons_natural_paper import LocalFreshQuote, _fresh_stamp
from robinhood_research.pons_selective_ledger import SelectivePaper, STRATEGY_NAMESPACE
from robinhood_research.pons_selective_acquisition import (
    ImmutableEvidenceCache, SelectiveEvidenceContext,
    _authenticate_window, _trajectory,
)
import robinhood_research.pons_selective_cohort as selective_cohort
import robinhood_research.pons_selective_acquisition as selective_acquisition
from robinhood_research.sequencer_feed import (
    SequencerBlockClock, SequencerTransportError, _WebSocket,
)
from robinhood_research.pons import CurveState
from robinhood_research.pons_selective_continuation import (
    POLICY, POLICY_HASH, ENTRY_THRESHOLDS, POST_GRAD_THRESHOLDS, EXIT_POLICY,
    breakout_vector, demand_metrics, post_graduation_vector,
    qualification_vector, relative_strength_bps, runner_action,
    wallet_convergence,
)

ZERO="0x0000000000000000000000000000000000000000"
CREATOR="0x"+"11"*20


def state(**kw):
    base=CurveState(
        quote_reserve=2*10**18,
        token_reserve=800*10**24,
        real_quote=8*10**17,
        reserved_tokens=100*10**24,
        fee_bps=100,
        creator_tax_bps=50,
        graduated=False,
        launched_at=100,
        snipe_start_bps=9900,
        snipe_seconds=3,
        timestamp=200,
    )
    return replace(base,**kw)


def snapshots():
    return [
        dict(at=185,progress_bps=6500),
        dict(at=195,progress_bps=7400),
        dict(at=200,progress_bps=8000),
    ]


def trade(identity, group, quote, at, side="buy"):
    return dict(
        identity=identity,side=side,quote=quote,tokens=10**20,event_at=at,
        actor=group,recipient=group,group=group,
    )


def events():
    groups=["0x"+f"{i:040x}" for i in range(20,26)]
    rows=[
        trade("p0",groups[0],10**14,178),
        trade("p1",groups[1],10**14,180),
    ]
    for i,g in enumerate(groups):
        rows.append(trade(f"c{i}",g,10**15,190+i%3))
    return rows


def vector(**overrides):
    args=dict(
        state=state(),graduation_threshold=10**18,launch_at=100,
        snapshots=snapshots(),events=events(),creator_groups=(CREATOR,),
        current_snipe_bps=0,lifecycle_gas_quote=10**10,
        strategy_capital_quote=10**18,asof=200,evidence_available_at=202,
        pair_token=ZERO,wallet_histories=None,creator_history=dict(adverse=False),
    )
    args.update(overrides)
    return qualification_vector(**args)


class PonsSelectivePolicyTests(unittest.TestCase):
    def test_policy_is_distinct_and_frozen(self):
        self.assertEqual(POLICY,"pons-selective-continuation-v1")
        self.assertEqual(len(POLICY_HASH),64)
        self.assertEqual(ENTRY_THRESHOLDS["min_curve_progress_bps"],5500)
        self.assertEqual(ENTRY_THRESHOLDS["max_curve_progress_bps"],9200)
        self.assertEqual(ENTRY_THRESHOLDS["capital_size_bps"],25)
        self.assertEqual(EXIT_POLICY["first_profit_bps"],2500)
        self.assertEqual(EXIT_POLICY["max_total_hold_seconds"],900)

    def test_clean_late_curve_acceleration_can_qualify(self):
        v=vector()
        self.assertTrue(v["complete"])
        self.assertTrue(v["current_threshold_pass"],v["all_rejections"])
        self.assertEqual(v["trajectory"]["progress_15s_bps"],1500)
        self.assertTrue(v["trajectory"]["accelerating"])
        self.assertGreaterEqual(v["demand"]["independent_groups"],5)
        self.assertGreaterEqual(v["demand"]["new_independent_groups_15s"],3)
        self.assertEqual(v["current_snipe_bps"],0)
        self.assertGreater(v["proposed_size"]["amount_quote"],0)
        self.assertLessEqual(v["roundtrip_loss_bps"],500)

    def test_chain_timestamp_lag_is_telemetry_not_selective_freshness(self):
        v=vector(
            evidence_available_at=1002,
            evidence_observed_at=1000.0,
            evidence_acquisition_latency_seconds=2.0,
        )
        self.assertNotIn("stale_state_after_evidence",v["all_rejections"])
        self.assertEqual(v["evidence_acquisition_latency_seconds"],2.0)
        self.assertEqual(v["chain_timestamp_lag_seconds"],800.0)
        self.assertTrue(v["current_threshold_pass"],v["all_rejections"])

    def test_selective_freshness_still_rejects_slow_local_acquisition(self):
        v=vector(
            evidence_available_at=1007,
            evidence_observed_at=1000.0,
            evidence_acquisition_latency_seconds=6.0,
        )
        self.assertIn("stale_state_after_evidence",v["all_rejections"])
        self.assertEqual(v["chain_timestamp_lag_seconds"],800.0)


    def test_snipe_tax_must_be_actually_zero(self):
        v=vector(current_snipe_bps=1)
        self.assertIn("snipe_tax_nonzero",v["all_rejections"])
        self.assertFalse(v["current_threshold_pass"])

    def test_static_high_curve_does_not_qualify(self):
        flat=[
            dict(at=185,progress_bps=8000),
            dict(at=195,progress_bps=8050),
            dict(at=200,progress_bps=8100),
        ]
        v=vector(snapshots=flat)
        self.assertIn("curve_velocity",v["all_rejections"])

    def test_non_native_pair_is_research_only(self):
        v=vector(pair_token="0x"+"99"*20,quote_relative_strength_bps=321)
        self.assertIn("non_native_quote_allocation_disabled",v["all_rejections"])
        self.assertEqual(v["quote_relative_strength_bps"],321)

    def test_demand_uses_equal_recent_windows_and_concentration(self):
        m=demand_metrics(events(),asof=200,creator_groups=(CREATOR,))
        self.assertEqual(m["current_buy_quote"],6*10**15)
        self.assertEqual(m["prior_net_quote"],2*10**14)
        self.assertGreater(m["current_net_quote"],m["prior_net_quote"])
        self.assertLessEqual(m["largest_buyer_flow_bps"],2500)
        self.assertLessEqual(m["top3_buyer_flow_bps"],5500)

    def test_wallet_skill_is_point_in_time_overlay_not_authority(self):
        gs=list(demand_metrics(events(),asof=200)["current_net_by_group"])
        history=[
            dict(group=gs[0],complete=True,history_asof=199,completed_trades=25,
                 realized_after_cost_pnl=100,profitable_tokens=4,candidate_related=False),
            dict(group=gs[1],complete=True,history_asof=198,completed_trades=40,
                 realized_after_cost_pnl=200,profitable_tokens=6,candidate_related=False),
        ]
        w=wallet_convergence(history,gs,asof=200)
        self.assertTrue(w["converged"])
        self.assertFalse(w["qualification_authority"])
        with self.assertRaisesRegex(BoundaryError,"future_wallet_skill"):
            wallet_convergence([dict(history[0],history_asof=201)],gs,asof=200)

    def test_post_graduation_second_wave_gate(self):
        good=post_graduation_vector(
            observed_seconds=10,price_retention_bps=9500,new_independent_buyers=4,
            buy_quote=3_000,sell_quote=1_000,net_quote=2_000,
            preholder_sell_quote=200,largest_buyer_flow_bps_before=2400,
            largest_buyer_flow_bps_now=2000,
        )
        self.assertTrue(good["continuation_pass"])
        bad=post_graduation_vector(
            observed_seconds=10,price_retention_bps=9000,new_independent_buyers=1,
            buy_quote=1_000,sell_quote=2_000,net_quote=-1_000,
            preholder_sell_quote=1500,largest_buyer_flow_bps_before=2000,
            largest_buyer_flow_bps_now=4000,
        )
        self.assertFalse(bad["continuation_pass"])
        self.assertIn("price_retention",bad["all_rejections"])
        self.assertIn("second_wave_breadth",bad["all_rejections"])

    def test_profit_then_runner_is_asymmetric(self):
        first=runner_action(
            tokens=1000,partial_taken=False,after_cost_return_bps=2600,
            high_water_return_bps=2600,seconds_since_high=0,new_buyer_growth=2,
            buy_quote=10,sell_quote=2,
        )
        self.assertEqual((first["action"],first["exit_tokens"]),("partial_exit",500))
        trail=runner_action(
            tokens=500,partial_taken=True,after_cost_return_bps=2000,
            high_water_return_bps=4000,seconds_since_high=10,new_buyer_growth=1,
            buy_quote=10,sell_quote=2,
        )
        self.assertEqual(trail["reason"],"runner_trailing_stop")
        risk=runner_action(
            tokens=500,partial_taken=False,after_cost_return_bps=-1000,
            high_water_return_bps=0,seconds_since_high=0,new_buyer_growth=1,
            buy_quote=1,sell_quote=1,
        )
        self.assertEqual(risk["action"],"full_exit")

    def test_relative_strength_separates_quote_asset_move(self):
        # Token +10%, quote +8% -> +2% excess return in this simple feature.
        self.assertEqual(relative_strength_bps(
            token_usd_start=100,token_usd_now=110,
            quote_usd_start=100,quote_usd_now=108,
        ),200)

    def test_breakout_is_separate_and_never_has_allocation_authority(self):
        b=breakout_vector(
            seconds_after_graduation=60,pullback_bps=1000,
            current_price_index=12_000,consolidation_high_index=11_500,
            new_independent_buyers_15s=4,buy_quote_15s=3000,
            sell_quote_15s=1000,previous_buy_quote_15s=1500,
        )
        self.assertTrue(b["candidate"])
        self.assertFalse(b["allocation_authority"])




class SelectiveEvidenceThroughputTests(unittest.TestCase):
    @staticmethod
    def _word(value):
        return "0x"+int(value).to_bytes(32,"big").hex()

    class BatchContext:
        def __init__(self):
            self.cache=ImmutableEvidenceCache()
            self.completed_sessions=[]
            self.rpc=None
            self.batches=[]
        def batch(self,calls,scope):
            calls=list(calls)
            self.batches.append((scope,calls))
            out=[]
            for method,params in calls:
                if method=="eth_getBlockByNumber":
                    block=int(params[0],16)
                    out.append(dict(
                        number=hex(block),
                        hash="0x"+f"{block:064x}",
                        timestamp=hex(800+block),
                    ))
                elif method=="eth_getBlockByHash":
                    block=int(str(params[0])[-4:],16)
                    out.append(dict(
                        number=hex(block),
                        hash=params[0],
                        timestamp=hex(block),
                    ))
                elif method=="eth_getTransactionReceipt":
                    tx=params[0]
                    block=int(tx[-2:],16)
                    out.append(dict(
                        transactionHash=tx,
                        blockHash="0x"+f"{block:064x}",
                    ))
                elif method=="eth_call":
                    data=params[0]["data"]
                    block=int(params[1],16)
                    if data==calldata("launchedAt()"):
                        out.append(
                            SelectiveEvidenceThroughputTests._word(900)
                        )
                    else:
                        out.append(
                            SelectiveEvidenceThroughputTests._word(
                                max(1,block*2)
                            )
                        )
                else:
                    raise AssertionError(method)
            return out

    def _candidate(self,block=200):
        return dict(
            block=block,
            curve=CREATOR,
            header=dict(
                number=hex(block),
                hash="0x"+f"{block:064x}",
                timestamp=hex(800+block),
            ),
            state=state(
                timestamp=800+block,
                real_quote=800,
            ),
            record=dict(graduationThreshold=1000),
        )

    def test_trajectory_batches_both_anchors_and_reuses_recent_headers(self):
        ctx=self.BatchContext()
        first,launch,meta=_trajectory(
            "https://unused",self._candidate(200),
            evidence_context=ctx,
        )
        self.assertEqual(launch,900)
        self.assertEqual([x["block"] for x in first[:2]],[185,195])
        self.assertTrue(meta["batched_recent_headers"])
        self.assertEqual(len(ctx.batches),2)
        self.assertEqual(len(ctx.batches[0][1]),50)
        self.assertEqual(len(ctx.batches[1][1]),2)

        before=len(ctx.batches)
        second,_,meta2=_trajectory(
            "https://unused",self._candidate(201),
            evidence_context=ctx,
        )
        self.assertEqual([x["block"] for x in second[:2]],[186,196])
        self.assertEqual(len(ctx.batches)-before,1)
        self.assertGreater(meta2["cache"].get("header_number_hit",0),0)
        self.assertGreater(meta2["cache"].get("launch_hit",0),0)

    def test_market_window_combines_missing_headers_and_receipts_then_hits_cache(self):
        ctx=self.BatchContext()
        curve=CREATOR
        events=[]
        for block in (190,191):
            events.append(dict(
                address=curve,blockNumber=hex(block),
                blockHash="0x"+f"{block:064x}",
                transactionHash="0x"+f"{block:064x}",
                transactionIndex="0x0",logIndex=hex(block-190),
            ))
        candidate=dict(
            block=200,curve=curve,
            stamp=type("StampLike",(),{"event_at":200})(),
        )
        def fake_raw(_abi,event,**kwargs):
            header=kwargs["header"]
            return dict(
                decoded=dict(name="CurveBuy",args={}),
                block=int(event["blockNumber"],16),
                transaction_hash=event["transactionHash"],
                log_index=int(event["logIndex"],16),
                event_at=int(header["timestamp"],16),
            )
        with patch.object(selective_acquisition,"raw_event",side_effect=fake_raw), \
             patch.object(
                 selective_acquisition,"normalized_trade",
                 side_effect=lambda decoded,identity,event_at: dict(
                     identity=identity,event_at=event_at,decoded=decoded
                 ),
             ):
            rows,_=_authenticate_window(
                "https://unused",candidate,events,
                seconds=60,evidence_context=ctx,
            )
            self.assertEqual(len(rows),2)
            self.assertEqual(len(ctx.batches),1)
            self.assertEqual(len(ctx.batches[0][1]),4)
            before=len(ctx.batches)
            rows2,_=_authenticate_window(
                "https://unused",candidate,events,
                seconds=60,evidence_context=ctx,
            )
        self.assertEqual(len(rows2),2)
        self.assertEqual(len(ctx.batches),before)
        tele=ctx.cache.telemetry()
        self.assertGreaterEqual(tele.get("header_hash_hit",0),2)
        self.assertGreaterEqual(tele.get("receipt_hit",0),2)

    def test_authoritative_rpc_session_is_reused_until_bounded_rotation(self):
        created=[]
        class FakeRpc:
            def __init__(self):
                self.used=1
                self.counts=Counter()
                self.per_scope=190
            def batch(self,calls,scope="x"):
                self.used+=len(calls)
                self.counts[scope]+=len(calls)
                return [f"r{i}" for i in range(len(calls))]
            def telemetry(self):
                return dict(requests=self.used,scopes=dict(self.counts))
        def make(_endpoint):
            rpc=FakeRpc();created.append(rpc);return rpc
        with patch.object(selective_acquisition,"_rpc",side_effect=make):
            ctx=SelectiveEvidenceContext("https://unused")
            ctx.batch([("eth_chainId",[])],"a")
            ctx.batch([("eth_chainId",[])],"a")
        self.assertEqual(len(created),1)
        self.assertIs(ctx.rpc,created[0])


class SelectiveDiscoveryFrontierTests(unittest.TestCase):
    class Rpc:
        used=0
        def __init__(self,frontier):
            self.frontier=frontier
            self.last=None
        def call(self,method,params,scope=None):
            self.last=(method,params,scope)
            if method=="eth_blockNumber":
                return hex(self.frontier)
            raise AssertionError(method)
        def telemetry(self):
            return {}

    def test_provider_frontier_clamps_sequencer_range_without_advancing_past_it(self):
        rpc=self.Rpc(103)
        with patch.object(selective_cohort,"_next_discovery_end",return_value=105), \
             patch.object(
                 selective_cohort,"_current_curve_events",
                 side_effect=[BoundaryError("provider_rpc_-32602"),["e"]],
             ) as events:
            new_rpc,cursor,fresh=selective_cohort._poll(
                "https://unused",rpc,100,[],object(),[]
            )
        self.assertIs(new_rpc,rpc)
        self.assertEqual(cursor,103)
        self.assertEqual(fresh,["e"])
        self.assertEqual(events.call_args_list[0].args,(rpc,101,105))
        self.assertEqual(events.call_args_list[1].args,(rpc,101,103))
        self.assertEqual(rpc.last[0],"eth_blockNumber")

    def test_provider_frontier_behind_start_leaves_cursor_unchanged(self):
        rpc=self.Rpc(100)
        with patch.object(selective_cohort,"_next_discovery_end",return_value=105), \
             patch.object(
                 selective_cohort,"_current_curve_events",
                 side_effect=BoundaryError("provider_rpc_-32602"),
             ):
            _,cursor,fresh=selective_cohort._poll(
                "https://unused",rpc,100,[],object(),[]
            )
        self.assertEqual(cursor,100)
        self.assertEqual(fresh,[])

    def test_full_frontier_range_rejection_splits_exactly_by_block(self):
        rpc=self.Rpc(105)
        responses=[
            BoundaryError("provider_rpc_-32602"),
            ["101"],["102"],["103"],["104"],["105"],
        ]
        with patch.object(selective_cohort,"_next_discovery_end",return_value=105), \
             patch.object(
                 selective_cohort,"_current_curve_events",side_effect=responses
             ) as events:
            _,cursor,fresh=selective_cohort._poll(
                "https://unused",rpc,100,[],object(),[]
            )
        self.assertEqual(cursor,105)
        self.assertEqual(fresh,["101","102","103","104","105"])
        self.assertEqual(
            [call.args for call in events.call_args_list],
            [
                (rpc,101,105),(rpc,101,101),(rpc,102,102),
                (rpc,103,103),(rpc,104,104),(rpc,105,105),
            ],
        )

    def test_non_frontier_invalid_params_still_fails_closed(self):
        rpc=self.Rpc(105)
        with patch.object(selective_cohort,"_next_discovery_end",return_value=105), \
             patch.object(
                 selective_cohort,"_current_curve_events",
                 side_effect=BoundaryError("provider_rpc_-32602"),
             ):
            with self.assertRaisesRegex(BoundaryError,"provider_rpc_-32602"):
                selective_cohort._poll(
                    "https://unused",rpc,100,[],object(),[]
                )




class SequencerFramingTests(unittest.TestCase):
    class CoalescedSocket:
        def __init__(self,frame):
            self.frame=frame
            self.buffer=bytearray()
            self.closed=False
            self.timeout=None
        def settimeout(self,value):
            self.timeout=value
        def sendall(self,data):
            if data.startswith(b"GET "):
                request=data.decode("iso-8859-1")
                key=[
                    line.split(":",1)[1].strip()
                    for line in request.split("\r\n")
                    if line.lower().startswith("sec-websocket-key:")
                ][0]
                accept=base64.b64encode(
                    hashlib.sha1(
                        (key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                    ).digest()
                ).decode()
                response=(
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n"
                    "Sec-WebSocket-Extensions: permessage-deflate\r\n"
                    "\r\n"
                ).encode()+self.frame
                self.buffer.extend(response)
        def recv(self,size):
            if not self.buffer:
                return b""
            # Deliberately return the entire upgrade response + first frame in
            # one TCP read when the caller permits it.
            take=min(int(size),len(self.buffer))
            out=bytes(self.buffer[:take])
            del self.buffer[:take]
            return out
        def close(self):
            self.closed=True

    class Context:
        def __init__(self,sock):
            self.sock=sock
        def wrap_socket(self,raw,server_hostname=None):
            return self.sock

    def test_upgrade_remainder_is_first_websocket_frame_not_discarded(self):
        payload=b'{"messages":[]}'
        frame=bytes([0x81,len(payload)])+payload
        sock=self.CoalescedSocket(frame)
        ws=_WebSocket("wss://feed.example",timeout=1.0)
        with patch("robinhood_research.sequencer_feed.socket.create_connection",
                   return_value=object()), \
             patch("robinhood_research.sequencer_feed.ssl.create_default_context",
                   return_value=self.Context(sock)):
            ws.connect()
        self.assertEqual(ws.recv_message(),payload.decode())
        self.assertEqual(bytes(ws._recv_buffer),b"")
        ws.close()

    def test_genuine_rsv2_and_rsv3_frames_still_fail_closed(self):
        class Idle:
            def recv(self,size):
                return b""
            def close(self):
                pass
        for bit in (0x20,0x10):
            ws=_WebSocket("wss://feed.example")
            ws.sock=Idle()
            ws._recv_buffer=bytearray(bytes([0x80|bit|0x01,0x00]))
            with self.subTest(bit=bit):
                with self.assertRaisesRegex(
                    BoundaryError,"sequencer_feed_reserved_bits"
                ):
                    ws.recv_message()



class SelectiveLocalFreshQuoteTests(unittest.TestCase):
    def test_fresh_stamp_local_mode_preserves_large_chain_lag(self):
        header=dict(number=hex(12),hash="0xabc",timestamp=hex(100))
        with patch("robinhood_research.pons_natural_paper.time.time",
                   return_value=320.0):
            local=_fresh_stamp(
                header,local_freshness_seconds=2.0,observed_at=320
            )
            self.assertEqual(local.event_at,100)
            self.assertEqual(local.observed_at,320)
            with self.assertRaisesRegex(BoundaryError,"stale_state"):
                _fresh_stamp(header,observed_at=320)

    def test_local_fresh_quote_accepts_chain_lag_but_not_slow_acquisition(self):
        s=Store(":memory:")
        stamp=Stamp(
            4663,12,"0xabc",100,320,"confirmed","natural"
        )
        ledger=Finality(s,scope="local-fresh",max_blocks=4)
        ledger.observe(
            stamp,"0xparent",local_freshness_seconds=2.0,max_local_age=5
        )
        good=LocalFreshQuote(
            "market","buy",100,1000,2,0,stamp,
            acquisition_latency_seconds=2.0,
            chain_timestamp_lag_seconds=220.0,
        )
        good.check(
            320,"market","buy",100,"natural",finality_ledger=ledger
        )
        slow=LocalFreshQuote(
            "market","buy",100,1000,2,0,stamp,
            acquisition_latency_seconds=6.0,
            chain_timestamp_lag_seconds=220.0,
        )
        with self.assertRaisesRegex(BoundaryError,"stale_state"):
            slow.check(
                320,"market","buy",100,"natural",finality_ledger=ledger
            )
        s.close()


class SelectiveSequencerRecoveryTests(unittest.TestCase):
    class Sock:
        def settimeout(self,value):
            self.timeout=value

    class FailingClient:
        def __init__(self):
            self.sock=SelectiveSequencerRecoveryTests.Sock()
            self.closed=False
        def recv_message(self):
            raise ssl.SSLEOFError(8,"EOF occurred in violation of protocol")
        def close(self):
            self.closed=True

    def test_tls_eof_becomes_recoverable_transport_loss(self):
        clock=SequencerBlockClock(url="wss://example.invalid")
        client=self.FailingClient()
        clock.client=client
        with self.assertRaises(SequencerTransportError):
            clock.wait_for_range_after(100,timeout=0.1,max_blocks=10)
        self.assertIsNone(clock.client)
        self.assertTrue(client.closed)
        self.assertEqual(clock.transport_failures,1)

    def test_recovery_does_not_advance_cursor_until_rpc_gap_is_read(self):
        rpc=SelectiveDiscoveryFrontierTests.Rpc(105)
        recoveries=[]
        with patch.object(
            selective_cohort,"_next_discovery_end",
            side_effect=[SequencerTransportError("SSLEOFError"),105],
        ), patch.object(
            selective_cohort,"_recover_sequencer",return_value=105
        ) as recover, patch.object(
            selective_cohort,"_current_curve_events",return_value=["covered"]
        ) as events:
            _,cursor,fresh=selective_cohort._poll(
                "https://unused",rpc,100,[],object(),[],recoveries
            )
        recover.assert_called_once()
        self.assertEqual(recover.call_args.args[1],100)
        self.assertEqual(events.call_args.args,(rpc,101,105))
        self.assertEqual(cursor,105)
        self.assertEqual(fresh,["covered"])

    def test_reconnect_records_observation_anchor_without_cursor_authority(self):
        class Feed:
            def __init__(self):
                self.reconnect_calls=0
            def reconnect(self):
                self.reconnect_calls+=1
            def wait_for_after(self,sequence,timeout=1.0):
                self.sequence=sequence
                return 120
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"recoveries.jsonl"
            recoveries=[]
            with patch.object(selective_cohort,"RECOVERY_LOG",path):
                anchor=selective_cohort._recover_sequencer(
                    Feed(),100,recoveries
                )
            self.assertEqual(anchor,120)
            self.assertEqual(recoveries[0]["canonical_cursor_before"],100)
            self.assertFalse(recoveries[0]["canonical_cursor_advanced"])
            self.assertEqual(
                recoveries[0]["catchup_authority"],
                "authenticated_discovery_rpc",
            )
            persisted=json.loads(path.read_text().strip())
            self.assertEqual(persisted["catchup_from"],101)
            self.assertEqual(persisted["catchup_to"],120)

    def test_checkpoint_persists_cursor_summary_provider_and_sequencer(self):
        class Feed:
            def status(self):
                return dict(
                    authority="observation_only",reconnects=1,
                    transport_failures=1,
                )
        class Rpc:
            def telemetry(self):
                return dict(role="pons_discovery",logical_requests=17)
        result=dict(
            started_at=10.0,rows=[
                dict(vector=dict(all_rejections=["curve_progress"]))
            ],qualifiers=[],lifecycles=[],
            discovery_sessions=[dict(role="old")],
            sequencer_recoveries=[dict(canonical_cursor_before=90)],
        )
        with tempfile.TemporaryDirectory() as td:
            progress=Path(td)/"progress.json"
            with patch.object(selective_cohort,"PROGRESS",progress):
                selective_cohort._checkpoint(
                    result,cursor=100,feed=Feed(),rpc=Rpc(),phase="discovery"
                )
            saved=json.loads(progress.read_text())
        self.assertEqual(saved["canonical_discovery_cursor"],100)
        self.assertEqual(saved["summary"]["enrolled"],1)
        self.assertEqual(
            saved["summary"]["rejection_counts"],{"curve_progress":1}
        )
        self.assertEqual(saved["active_discovery_provider"]["logical_requests"],17)
        self.assertEqual(saved["sequencer_discovery"]["reconnects"],1)


class PartialPaperExitTests(unittest.TestCase):
    def _stamp(self,at):
        return Stamp(4663,at,f"h{at}",at,at,"finalized","natural")

    def _features(self,at,market):
        return dict(
            asof=at,market=market,authority="frozen_policy_paper",
            qualification="qualified",policy_hash=POLICY_HASH,
            strategy_namespace=STRATEGY_NAMESPACE,shared_allocator=False,
        )

    def test_partial_profit_then_runner_settlement_survives_accounting(self):
        s=Store(":memory:")
        p=SelectivePaper(
            s,STRATEGY_NAMESPACE+"-unit-partial",1000,delay=1,
            natural_policy_hash=POLICY_HASH,
        )
        p.reserve(
            "x",market="market",amount=100,gas_budget=20,now=10,
            features=self._features(10,"market"),kind="natural",
        )
        opened=p.advance(
            "x",now=11,action="entry",
            quote=Quote("market","buy",100,1000,2,0,self._stamp(11)),
        )
        self.assertEqual(opened["remaining_cost"],102)

        p.advance("x",now=12,action="exit_intent",exit_tokens=500)
        partial=p.advance(
            "x",now=13,action="exit",
            quote=Quote("market","sell",500,70,2,0,self._stamp(13)),
        )
        self.assertEqual((partial["status"],partial["tokens"]),("open",500))
        self.assertEqual(partial["remaining_cost"],51)
        self.assertEqual(partial["realized_pnl"],17)

        p.advance("x",now=14,action="exit_intent")
        final=p.advance(
            "x",now=15,action="exit",
            quote=Quote("market","sell",500,82,2,0,self._stamp(15)),
        )
        self.assertEqual(final["status"],"settled")
        self.assertEqual(final["pnl"],46)
        self.assertEqual(p.reconcile()["available"],1046)
        s.close()



    def test_pending_full_exit_survives_proven_market_transition(self):
        s=Store(":memory:")
        p=SelectivePaper(
            s,STRATEGY_NAMESPACE+"-unit-transition",1000,delay=1,
            natural_policy_hash=POLICY_HASH,
        )
        p.reserve(
            "x",market="curve",amount=100,gas_budget=20,now=10,
            features=self._features(10,"curve"),kind="natural",
        )
        p.advance(
            "x",now=11,action="entry",
            quote=Quote("curve","buy",100,1000,2,0,self._stamp(11)),
        )
        pending=p.advance("x",now=12,action="exit_intent")
        self.assertEqual(pending["pending_exit_tokens"],1000)
        transition=dict(
            previous_market="curve",market="v4",proof_hash="proof",
        )
        s.put("graduation","proof",transition)
        moved=p.advance("x",now=13,action="transition",transition=transition)
        self.assertEqual((moved["status"],moved["market"]),("exit_pending","v4"))
        final=p.advance(
            "x",now=13,action="exit",
            quote=Quote("v4","sell",1000,120,2,0,self._stamp(13)),
        )
        self.assertEqual(final["status"],"settled")
        self.assertEqual(final["tokens"],0)
        s.close()

if __name__=="__main__":
    unittest.main()
