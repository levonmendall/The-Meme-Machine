import os
import tempfile
import unittest

from meme_machine.solana_evidence_broker import EvidenceBroker


class _Clock:
    def __init__(self):
        self.value=1000.0
    def __call__(self):
        return self.value
    def sleep(self,seconds):
        self.value+=float(seconds)


class _Rpc:
    def __init__(self):
        self.batches=[]
    def call_many(self,method,params,priority=False,batch_size=8):
        self.batches.append((method,[p[0] for p in params],priority,batch_size))
        return [
            {
                "slot":100+i,
                "blockTime":1000+i,
                "meta":{"err":None,"logMessages":[]},
                "transaction":{"message":{"accountKeys":[]}},
            }
            for i,_ in enumerate(params)
        ]


class SolanaEvidenceBrokerTests(unittest.TestCase):
    def make_broker(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        clock=_Clock()
        broker=EvidenceBroker(
            os.path.join(td.name,"broker.sqlite3"),
            clock=clock,sleeper=clock.sleep)
        self.addCleanup(broker.close)
        return broker,clock

    def test_stream_coverage_is_fail_closed_across_gap(self):
        broker,clock=self.make_broker()
        broker.stream_begin("pump",int(clock()))
        broker.record_event(
            "pump",signature="sig1",slot=10,observed_at=int(clock()))
        self.assertFalse(broker.stream_status("pump",int(clock()),30)["covered"])
        clock.value+=31
        self.assertTrue(broker.stream_status("pump",int(clock()),30)["covered"])
        broker.stream_gap("pump",int(clock()),30)
        self.assertFalse(broker.stream_status("pump",int(clock()),30)["covered"])
        clock.value+=1
        broker.stream_begin("pump",int(clock()))
        clock.value+=31
        self.assertTrue(broker.stream_status("pump",int(clock()),30)["covered"])

    def test_transaction_hydration_is_durable_and_deduplicated(self):
        broker,clock=self.make_broker()
        rpc=_Rpc()
        first,meta=broker.hydrate_transactions(
            rpc,["a","b"],kind="pump_window",deadline=clock()+10,batch_size=8)
        self.assertEqual(set(first),{"a","b"})
        self.assertEqual(meta["pending"],0)
        self.assertEqual(len(rpc.batches),1)
        second,meta2=broker.hydrate_transactions(
            rpc,["b","a"],kind="pump_window",deadline=clock()+10,batch_size=8)
        self.assertEqual(meta2["pending"],0)
        self.assertEqual(len(rpc.batches),1)
        self.assertEqual(second["a"]["blockTime"],1000)

    def test_deadline_queue_prioritizes_monitoring_over_background_history(self):
        broker,clock=self.make_broker()
        rpc=_Rpc()
        broker.queue_transaction(
            "low",kind="research_history",deadline=clock()+100)
        result,meta=broker.hydrate_transactions(
            rpc,["high"],kind="position_monitor",deadline=clock()+10,batch_size=2)
        self.assertEqual(meta["pending"],0)
        self.assertTrue(rpc.batches)
        self.assertEqual(rpc.batches[0][1][0],"high")
        self.assertIn("high",result)

    def test_shared_queue_claims_are_atomic_and_leases_recover(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        clock=_Clock()
        path=os.path.join(td.name,"shared.sqlite3")
        first=EvidenceBroker(path,clock=clock,sleeper=clock.sleep)
        second=EvidenceBroker(path,clock=clock,sleeper=clock.sleep)
        self.addCleanup(first.close);self.addCleanup(second.close)

        first.queue_transaction(
            "a",kind="pump_window",deadline=clock()+100)
        first.queue_transaction(
            "b",kind="research_history",deadline=clock()+100)
        claimed_first=first._claim_jobs(1,clock(),lease_seconds=15)
        self.assertEqual([x[0] for x in claimed_first],["tx:a"])

        # A duplicate request must not clear another process's active lease.
        second.queue_transaction(
            "a",kind="position_monitor",deadline=clock()+100)
        claimed_second=second._claim_jobs(2,clock(),lease_seconds=15)
        self.assertEqual([x[0] for x in claimed_second],["tx:b"])
        self.assertEqual(first.telemetry()["inflight_jobs"],2)

        # If the worker disappears, its lease becomes reclaimable.
        clock.value+=16
        reclaimed=second._claim_jobs(2,clock(),lease_seconds=15)
        self.assertIn("tx:a",[x[0] for x in reclaimed])

    def test_global_transport_pacing_is_shared_across_broker_processes(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        clock=_Clock()
        path=os.path.join(td.name,"shared.sqlite3")
        first=EvidenceBroker(path,clock=clock,sleeper=clock.sleep)
        second=EvidenceBroker(path,clock=clock,sleeper=clock.sleep)
        self.addCleanup(first.close);self.addCleanup(second.close)

        wait1=first._reserve_hydration_transport(clock()+10)
        wait2=second._reserve_hydration_transport(clock()+10)
        self.assertEqual(wait1,0.0)
        self.assertAlmostEqual(wait2,0.2,places=6)
        pressure=second.telemetry()["pressure"]
        self.assertEqual(pressure["transport_reservations"],2)
        self.assertGreaterEqual(pressure["transport_ready_in_seconds"],0.19)

    def test_rate_limit_cooldown_is_global_and_recovers(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        clock=_Clock()
        path=os.path.join(td.name,"shared.sqlite3")
        first=EvidenceBroker(path,clock=clock,sleeper=clock.sleep)
        second=EvidenceBroker(path,clock=clock,sleeper=clock.sleep)
        self.addCleanup(first.close);self.addCleanup(second.close)

        first._note_pressure_failure()
        before=clock()
        wait=second._reserve_hydration_transport(clock()+10)
        self.assertGreaterEqual(wait,2.0)
        self.assertGreaterEqual(clock()-before,2.0)
        self.assertEqual(second.telemetry()["pressure"]["rate_streak"],1)

        for _ in range(8):
            second._note_pressure_success()
        recovered=first.telemetry()["pressure"]
        self.assertEqual(recovered["rate_streak"],0)
        self.assertGreaterEqual(recovered["batch_size"],5)

    def test_missing_cache_entry_requeues_formerly_complete_job(self):
        broker,clock=self.make_broker()
        rpc=_Rpc()
        first,meta=broker.hydrate_transactions(
            rpc,["a"],kind="pump_window",deadline=clock()+10,batch_size=1)
        self.assertEqual(meta["pending"],0)
        self.assertIsNotNone(first["a"])
        self.assertEqual(len(rpc.batches),1)
        with broker.lock,broker.db:
            broker.db.execute("DELETE FROM tx_cache WHERE signature='a'")
        second,meta2=broker.hydrate_transactions(
            rpc,["a"],kind="position_monitor",deadline=clock()+10,batch_size=1)
        self.assertEqual(meta2["pending"],0)
        self.assertIsNotNone(second["a"])
        self.assertEqual(len(rpc.batches),2)

    def test_stream_events_prune_only_expired_cache_rows(self):
        broker,clock=self.make_broker()
        broker.stream_begin("s",int(clock()))
        broker.record_event(
            "s",signature="old",slot=1,observed_at=int(clock())-4000)
        broker.record_event(
            "s",signature="new",slot=2,observed_at=int(clock()))
        got=broker.recent_events("s",since=int(clock())-5000)
        self.assertEqual([row["signature"] for row in got],["new"])

    def test_cursor_cannot_regress(self):
        broker,_clock=self.make_broker()
        broker.advance_cursor("pool:x",100,"a")
        broker.advance_cursor("pool:x",101,"b")
        self.assertEqual(broker.cursor("pool:x"),{"slot":101,"signature":"b"})
        with self.assertRaisesRegex(ValueError,"evidence_cursor_regression"):
            broker.advance_cursor("pool:x",99,"c")

    def test_signature_ledger_is_incremental(self):
        broker,_clock=self.make_broker()
        rows=[
            {
                "signature":"s2","slot":102,"blockTime":1002,
                "err":None,"confirmationStatus":"finalized",
                "transactionIndex":1,
            },
            {
                "signature":"s1","slot":101,"blockTime":1001,
                "err":None,"confirmationStatus":"finalized",
                "transactionIndex":0,
            },
        ]
        broker.remember_signatures(
            "dlmm","pool",rows,covered_through_slot=102)
        coverage=broker.signature_coverage("dlmm","pool")
        self.assertEqual(coverage["newest_signature"],"s2")
        self.assertEqual(coverage["oldest_slot"],101)
        self.assertEqual(coverage["covered_through_slot"],102)
        got=broker.signature_rows(
            "dlmm","pool",start_slot=102,end_slot=102)
        self.assertEqual([x["signature"] for x in got],["s2"])


if __name__=="__main__":
    unittest.main()
