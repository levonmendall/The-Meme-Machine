"""Offline regressions for lost trigger evidence and terminal attribution."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import MagicMock,patch

from meme_machine.lanes.meteora.pipeline import Pipeline
from tests.lanes.meteora import solana_dlmm_independent_v1 as strategy


class MeteoraEvidenceRecoveryTests(unittest.TestCase):
    def run_trigger(self,status,authenticate,*,post=None,deadline=3.0,
                    pool="pool",baseline_slot=10):
        clock=[0.0]
        broker=MagicMock()
        broker.cursor.return_value={"slot":0}
        broker.stream_status.side_effect=lambda *_:status(clock[0])
        broker.recent_events.return_value=[]
        adapter=MagicMock();adapter.rpc.calls=0
        calls=[]
        def auth(*args):
            calls.append(clock[0])
            return authenticate(len(calls),clock[0])
        def sleep(seconds):clock[0]+=seconds
        with patch.object(strategy.time,"monotonic",side_effect=lambda:clock[0]), \
             patch.object(strategy.time,"sleep",side_effect=sleep), \
             patch.object(strategy,"_new_finalized_swaps",side_effect=auth), \
             patch.object(strategy,"_fresh_supported_start",side_effect=post or [{"slot":12}]) as fresh, \
             patch.object(strategy,"_stage") as stage:
            result=strategy._await_fresh_swap_trigger(
                adapter,{"address":pool},{"slot":baseline_slot},strategy.load_policy(),
                MagicMock(),[],deadline=deadline,broker=broker)
        return result,calls,broker,fresh,stage

    @staticmethod
    def empty():
        return [],dict(rate_limited=False,head_slot=10,head_signature=None)

    @staticmethod
    def swap():
        return [dict(signature="sig",slot=11,swap_count=1)],dict(
            rate_limited=False,head_slot=11,head_signature="sig")

    def test_gap_authentication_waits_for_reconnect_instead_of_acknowledging_open_gap(self):
        def status(now):
            return dict(gaps=int(now>=.25),covered=now<.25 or now>=1.0)
        result,calls,broker,_,_=self.run_trigger(status,
            lambda count,now:self.empty() if count==1 else self.swap())
        trigger,post,*_=result
        self.assertEqual(calls,[0.,1.])
        self.assertTrue(trigger["triggered"])
        self.assertEqual(trigger["gap_recoveries"],1)
        self.assertFalse(trigger["gap_recovery_pending"])
        self.assertEqual(trigger["wake_source"],"stream_gap_auth")
        self.assertEqual(trigger["gap_recovery_scope"],
            "bounded_candidate_trigger_authentication_not_stream_backfill")
        self.assertEqual(post["slot"],12)
        broker.advance_cursor.assert_called_once_with("dlmm_fresh:pool",11,"sig")

    def test_pending_hydration_keeps_gap_obligation_without_another_wakeup(self):
        def auth(count,now):
            if count==1:return self.empty()
            if count==2:return [],dict(rate_limited=False,head_slot=10,
                head_signature=None,hydration={"pending":1})
            return self.swap()
        result,calls,broker,_,_=self.run_trigger(
            lambda now:dict(gaps=int(now>=.25),covered=True),auth)
        self.assertTrue(result[0]["triggered"])
        self.assertEqual(calls,[0.,.25,.75])
        self.assertEqual(result[0]["gap_recoveries"],1)
        broker.advance_cursor.assert_called_once_with("dlmm_fresh:pool",11,"sig")

    def test_rate_limited_recovery_is_not_acknowledged_or_cursor_advanced(self):
        def auth(count,now):
            if count==1:return self.empty()
            if count==2:return [],dict(rate_limited=True,head_slot=10)
            return self.swap()
        result,calls,broker,_,_=self.run_trigger(
            lambda now:dict(gaps=int(now>=.25),covered=True),auth)
        self.assertTrue(result[0]["triggered"])
        self.assertEqual(calls,[0.,.25,.75])
        self.assertEqual(result[0]["gap_recoveries"],1)
        broker.advance_cursor.assert_called_once()

    def test_authenticated_trigger_survives_lagging_account_endpoint_without_rehydration(self):
        result,calls,_,fresh,stages=self.run_trigger(
            lambda now:dict(gaps=0,covered=True),lambda *_:self.swap(),
            post=[{"slot":10},{"slot":11}])
        self.assertEqual(calls,[0.])
        self.assertEqual(fresh.call_count,2)
        self.assertEqual(result[0]["signature"],"sig")
        self.assertEqual(result[0]["post_trigger_slot"],11)
        self.assertEqual([c.args[1] for c in stages.call_args_list],
            ["trigger_observed","trigger_authenticated"])

    def test_pending_trigger_still_expires_at_original_campaign_deadline(self):
        result,calls,_,fresh,_=self.run_trigger(
            lambda now:dict(gaps=0,covered=True),lambda *_:self.swap(),
            post=[{"slot":10}],deadline=.4)
        self.assertFalse(result[0]["triggered"])
        self.assertEqual(result[0]["reason"],"experiment_runtime_deadline")
        self.assertTrue(result[0]["authenticated_trigger_pending_fresh_state"])
        self.assertIsNone(result[1])
        self.assertEqual(calls,[0.]);self.assertEqual(fresh.call_count,1)

    def test_captured_authenticated_trigger_is_not_reclassified_as_no_activity(self):
        fixture=json.loads((Path(__file__).parent/"fixtures"/
            "meteora_trigger_account_lag.json").read_text())
        signature=fixture["signature_row"]
        swaps=strategy.transaction_swaps(fixture["transaction"],fixture["pool"],trigger_only=True)
        self.assertTrue(swaps)
        self.assertEqual(signature["slot"],449910506)
        self.assertEqual(fixture["lagging_account_slot"],449910499)
        authenticated=dict(signature=signature["signature"],slot=signature["slot"],
            swap_count=len(swaps),swaps=swaps)
        def auth(*_):return [authenticated],dict(rate_limited=False,
            head_slot=signature["slot"],head_signature=signature["signature"])
        result,calls,_,_,_=self.run_trigger(
            lambda now:dict(gaps=0,covered=True),auth,
            post=[{"slot":fixture["lagging_account_slot"]}],deadline=.4,
            pool=fixture["pool"],baseline_slot=fixture["baseline_slot"])
        self.assertFalse(result[0]["triggered"])
        self.assertTrue(result[0]["authenticated_trigger_pending_fresh_state"])
        self.assertEqual(result[0]["reason"],"experiment_runtime_deadline")
        self.assertEqual(calls,[0.])
        # No successor snapshot is invented: the captured lag stays fail-closed.
        self.assertIsNone(result[1])

    def test_disconnected_at_admission_recovers_after_initial_bootstrap(self):
        result,calls,_,_,_=self.run_trigger(
            lambda now:dict(gaps=3,covered=now>=.5),
            lambda count,now:self.empty() if count==1 else self.swap())
        self.assertEqual(calls,[0.,.5])
        self.assertTrue(result[0]["triggered"])
        self.assertEqual(result[0]["gap_recoveries"],1)

    def test_original_trigger_wait_limit_keeps_failed_fresh_state_distinct_from_no_activity(self):
        result,calls,_,_,_=self.run_trigger(
            lambda now:dict(gaps=0,covered=True),lambda *_:self.swap(),
            post=lambda *_:{"slot":10},deadline=121.)
        self.assertFalse(result[0]["triggered"])
        self.assertEqual(result[0]["waited_seconds"],120.)
        self.assertEqual(result[0]["reason"],"fresh_state_unavailable_after_authenticated_trigger")
        self.assertEqual(calls,[0.])

    def test_unclosed_stream_gap_is_not_reported_as_proven_no_activity(self):
        result,calls,_,_,_=self.run_trigger(
            lambda now:dict(gaps=1,covered=False),lambda *_:self.empty(),deadline=121.)
        self.assertFalse(result[0]["triggered"])
        self.assertEqual(result[0]["waited_seconds"],120.)
        self.assertEqual(result[0]["reason"],"stream_gap_unresolved_at_trigger_timeout")
        self.assertTrue(result[0]["gap_recovery_pending"])
        self.assertEqual(calls,[0.])

    def test_completed_rejection_closes_trigger_and_supersession_is_separate(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"pipeline.sqlite"
            pipeline=Pipeline(path,"meteora","frozen");active={}
            def record(stage,reason=None,**details):
                strategy._record_progress(pipeline,active,"pool",stage,reason,**details)
            record("trigger_authenticated",slot=10)
            record("trigger_authenticated",slot=11)
            record("evidence_complete")
            record("terminal","qualification_rejection",failed=["two_way"])
            stats=pipeline.snapshot()
            self.assertEqual(active,{})
            self.assertEqual(stats["unresolved_triggers"],0)
            self.assertEqual(stats["authenticated_triggers"],2)
            self.assertEqual(stats["unique_classes"]["reconstruction_incomplete"],0)
            self.assertEqual(stats["unique_classes"]["superseded_candidate_state"],1)
            self.assertEqual(stats["unique_classes"]["strategy_rejection"],1)
            self.assertEqual(stats["stages"]["evidence_complete"],1)
            self.assertEqual(stats["stages"]["evidence_required"],1)
            observations=[(stage,json.loads(details).get("observation_id"))
                for stage,details in pipeline.db.execute(
                    "SELECT stage,details FROM progress WHERE candidate='pool' AND stage IN "
                    "('evidence_required','evidence_superseded','evidence_complete','terminal') ORDER BY sequence")]
            self.assertEqual(observations,[("evidence_required","pool:10"),
                ("evidence_superseded","pool:10"),("evidence_required","pool:11"),
                ("evidence_complete","pool:11"),("terminal","pool:11")])
            pipeline.close()
            restored=Pipeline(path,"meteora","frozen")
            self.assertEqual(restored.snapshot(),stats)
            restored.close()

    def test_explicit_missing_public_evidence_classification_remains_visible(self):
        with tempfile.TemporaryDirectory() as td:
            pipeline=Pipeline(Path(td)/"pipeline.sqlite","meteora","frozen")
            strategy._record_progress(pipeline,{},"pool","rejected",
                "public_fee_context_incomplete",classification="reconstruction_incomplete")
            self.assertEqual(pipeline.snapshot()["unique_classes"]["reconstruction_incomplete"],1)
            pipeline.close()

    def test_native_run_persists_completed_rejection_without_shutdown_failure(self):
        candidate=dict(address="pool",signal_observed_at=0)
        adapter=MagicMock()
        def candidates(*_):yield candidate
        def warmup(*_):
            strategy._stage("pool","trigger_authenticated",slot=11)
            strategy._stage("pool","warmup_started")
            strategy._stage("pool","warmup_complete")
            return {"aligned":True},object(),{"slot":12},{"slot":11},adapter,candidate
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"report.json"
            with patch.object(strategy,"EVIDENCE_PLANE",MagicMock(frontier=lambda *_:0,telemetry=lambda:{})), \
                 patch.object(strategy,"OUT",output), \
                 patch.object(strategy,"DLMM_BROKER_DB",Path(td)/"broker.sqlite"), \
                 patch.object(strategy,"_prove_network_identity",return_value={"verified":True}), \
                 patch.object(strategy,"ProgramAccountWakeStream") as stream, \
                 patch.object(strategy,"_campaign_candidates",side_effect=candidates), \
                 patch.object(strategy,"_new_adapter",return_value=adapter), \
                 patch.object(strategy,"_fresh_supported_start",return_value={"slot":10}), \
                 patch.object(strategy,"_triggered_warmup",side_effect=warmup), \
                 patch.object(strategy,"pre_entry_features",return_value={}), \
                 patch.object(strategy,"qualify",return_value={"passes":False,"failed":["two_way"]}), \
                 patch("builtins.print"):
                stream.return_value.run.side_effect=lambda stop,ready:ready.set()
                result=strategy.run_live(target=1,max_attempted=1,max_runtime_seconds=60)
            persisted=json.loads(output.read_text())
            pipeline=Pipeline(output.with_suffix(".pipeline.sqlite"),"meteora",strategy.digest(strategy.load_policy()))
            stats=pipeline.snapshot();pipeline.close()
            self.assertEqual(persisted["opportunity_coverage"],stats)
            self.assertEqual(result["opportunity_coverage"],stats)
            self.assertEqual(stats["unresolved_triggers"],0)
            self.assertEqual(stats["unique_classes"]["strategy_rejection"],1)
            self.assertEqual(stats["unique_classes"]["reconstruction_incomplete"],0)
            self.assertEqual(stats["stages"]["evidence_required"],1)
            self.assertEqual(stats["stages"]["evidence_requested"],1)
            self.assertEqual(stats["stages"]["trigger_evidence_requested"],1)
            self.assertNotIn("campaign_shutdown_unresolved_trigger",stats["unique_terminal_reasons"])
            self.assertEqual(persisted["accounting"]["cash"],1_000_000_000)

    def test_preentry_cutoff_is_pending_context_without_full_evidence_obligation(self):
        with tempfile.TemporaryDirectory() as td:
            pipeline=Pipeline(Path(td)/"pipeline.sqlite","meteora","frozen")
            strategy._record_progress(pipeline,{},"pool","evidence_pending",
                "campaign_window_insufficient_preentry_time")
            strategy._record_progress(pipeline,{},"pool","terminal",
                "campaign_window_insufficient_preentry_time")
            stats=pipeline.snapshot()
            self.assertEqual(stats["stages"]["evidence_pending"],1)
            self.assertEqual(stats["stages"].get("evidence_required",0),0)
            self.assertEqual(stats["unique_classes"]["reconstruction_incomplete"],0)
            self.assertEqual(stats["unique_classes"]["pending_at_observation_close"],1)
            pipeline.close()

    def test_verified_zero_warmup_cancels_only_full_vector_obligation(self):
        adapter=MagicMock();candidate={"address":"pool"}
        tape=MagicMock();tape.events=[]
        with patch.object(strategy,"_await_fresh_swap_trigger",return_value=(
                {"triggered":True}, {"slot":11},adapter,candidate)), \
             patch.object(strategy,"_observe_window",return_value=(
                {"verified":True},tape,{"slot":12},{"slot":11},adapter)), \
             patch.object(strategy,"_stage") as stages:
            result,*_=strategy._triggered_warmup(adapter,candidate,{"slot":10},
                strategy.load_policy(),MagicMock(),[])
        self.assertFalse(result["aligned"])
        self.assertEqual(result["reason"],"verified_zero_warmup_after_fresh_swap")
        stage_names=[call.args[1] for call in stages.call_args_list]
        self.assertIn("warmup_complete",stage_names)
        self.assertIn("evidence_not_required",stage_names)
        self.assertNotIn("evidence_complete",stage_names)


if __name__=="__main__":unittest.main()
