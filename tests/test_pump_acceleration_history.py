import os
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_broker import EvidenceBroker
from meme_machine.pump_acceleration_history import IncrementalPumpSwapHistory


class FakeRPC:
    def __init__(self):
        self.signature_calls=[]
        self.tx_calls=[]
        self.tx_configs=[]
        self.round=0

    def call(self,method,params,priority=False):
        self.assert_priority=priority
        if method!="getSignaturesForAddress":
            raise AssertionError(method)
        cfg=params[1];self.signature_calls.append(dict(cfg))
        before=cfg.get("before");until=cfg.get("until")
        if until=="s3":
            return [
                {"signature":"s5","blockTime":105,"slot":5,"err":None},
                {"signature":"s4","blockTime":104,"slot":4,"err":None},
            ]
        if before=="s2":
            return [{"signature":"s1","blockTime":99,"slot":1,"err":None}]
        return [
            {"signature":"s3","blockTime":103,"slot":3,"err":None},
            {"signature":"s2","blockTime":102,"slot":2,"err":None},
        ]

    def call_many(self,method,params_list,priority=False,batch_size=8):
        self.tx_calls.extend(x[0] for x in params_list)
        self.tx_configs.extend(dict(x[1]) for x in params_list)
        if any(x[1].get("maxSupportedTransactionVersion") != 1 for x in params_list):
            raise AssertionError("v1 transaction reads must opt in")
        return [
            {"slot":int(x[0][1:]),"meta":{"err":None,"logMessages":[]}}
            for x in params_list
        ]


class IncrementalHistoryTests(unittest.TestCase):
    def test_backfills_once_then_only_fetches_new_head(self):
        rpc=FakeRPC()
        h=IncrementalPumpSwapHistory(
            "pool",100,page_limit=2,max_backfill_pages=2,max_new_pages=2)
        self.assertEqual(h.refresh(rpc,103),[])
        self.assertTrue(h.complete(103))
        first_calls=len(rpc.signature_calls)
        first_txs=list(rpc.tx_calls)
        self.assertIn("s1",h.processed)
        self.assertEqual(h.refresh(rpc,105),[])
        self.assertGreater(len(rpc.signature_calls),first_calls)
        self.assertEqual(rpc.signature_calls[-1].get("until"),"s3")
        self.assertEqual(first_txs.count("s2"),1)
        self.assertEqual(rpc.tx_calls.count("s2"),1)
        self.assertIn("s4",rpc.tx_calls)
        self.assertIn("s5",rpc.tx_calls)
        self.assertTrue(rpc.tx_configs)
        self.assertTrue(all(x["maxSupportedTransactionVersion"]==1 for x in rpc.tx_configs))

    def test_new_pool_bootstraps_decision_window_once_then_stays_stream_first(self):
        class R:
            def __init__(self):
                self.signature_calls=[];self.tx_calls=[]
            def call(self,method,params,priority=False):
                self.signature_calls.append((method,params,priority))
                return [
                    {"signature":"s2","blockTime":105,"slot":2,"err":None},
                    {"signature":"s1","blockTime":104,"slot":1,"err":None},
                ]
            def call_many(self,method,params_list,priority=False,batch_size=8):
                self.tx_calls.extend(x[0] for x in params_list)
                return [
                    {"slot":2 if x[0]=="s2" else 1,
                     "blockTime":105 if x[0]=="s2" else 104,
                     "meta":{"err":None,"logMessages":[]},
                     "transaction":{"message":{"accountKeys":[]}}}
                    for x in params_list
                ]
        with tempfile.TemporaryDirectory() as td:
            broker=EvidenceBroker(os.path.join(td,"broker.sqlite3"))
            self.addCleanup(broker.close)
            rpc=R()
            history=IncrementalPumpSwapHistory(
                "pool",100,broker=broker,stream_key="pool:one")
            self.assertEqual(history.refresh(rpc,105),[])
            self.assertTrue(history.decision_window_status(105,30)["complete"])
            self.assertEqual(history.decision_bootstrap_attempts,1)
            self.assertEqual(len(rpc.signature_calls),1)
            self.assertEqual(set(rpc.tx_calls),{"s1","s2"})
            self.assertEqual(history.refresh(rpc,106),[])
            self.assertEqual(len(rpc.signature_calls),1)

    def test_decision_bootstrap_continues_behind_streamed_prefix_across_attempts(self):
        class B:
            def signature_rows(self,*_args,**_kwargs): return []
            def remember_signatures(self,*_args,**_kwargs): return None
            def stream_status(self,*_args,**_kwargs): return {"covered":False}
        class R:
            def __init__(self): self.befores=[]
            def call(self,method,params,priority=False):
                self.befores.append(params[1].get("before"))
                pages={
                    "live":[
                        {"signature":"p1a","blockTime":198,"slot":198,"err":None},
                        {"signature":"p1b","blockTime":197,"slot":197,"err":None},
                    ],
                    "p1b":[
                        {"signature":"p2a","blockTime":190,"slot":190,"err":None},
                        {"signature":"p2b","blockTime":180,"slot":180,"err":None},
                    ],
                    "p2b":[
                        {"signature":"p3a","blockTime":169,"slot":169,"err":None},
                        {"signature":"p3b","blockTime":168,"slot":168,"err":None},
                    ],
                }
                return pages[params[1].get("before")]
        h=IncrementalPumpSwapHistory(
            "pool",100,page_limit=2,max_backfill_pages=0,
            broker=B(),stream_key="pool:gap")
        h.signature_rows={
            "live":{"signature":"live","blockTime":200,"slot":200,"err":None},
        }
        rpc=R()
        h._bootstrap_decision_window(rpc,200,30)
        self.assertFalse(h.decision_bootstrap_complete)
        self.assertFalse(h.decision_bootstrap_capacity_loss)
        self.assertEqual(h.decision_bootstrap_before,"p1b")
        h._bootstrap_decision_window(rpc,200,30)
        self.assertFalse(h.decision_bootstrap_complete)
        self.assertFalse(h.decision_bootstrap_capacity_loss)
        self.assertEqual(h.decision_bootstrap_before,"p2b")
        h._bootstrap_decision_window(rpc,200,30)
        self.assertTrue(h.decision_bootstrap_complete)
        self.assertFalse(h.decision_bootstrap_capacity_loss)
        self.assertEqual(rpc.befores,["live","p1b","p2b"])

    def test_decision_bootstrap_capacity_loss_only_after_final_continuation(self):
        class B:
            def signature_rows(self,*_args,**_kwargs): return []
            def remember_signatures(self,*_args,**_kwargs): return None
            def stream_status(self,*_args,**_kwargs): return {"covered":False}
        class R:
            def __init__(self): self.n=0;self.befores=[]
            def call(self,method,params,priority=False):
                self.befores.append(params[1].get("before"))
                self.n+=1
                newest=200-self.n*2
                return [
                    {"signature":f"a{self.n}","blockTime":newest,
                     "slot":newest,"err":None},
                    {"signature":f"b{self.n}","blockTime":newest-1,
                     "slot":newest-1,"err":None},
                ]
        h=IncrementalPumpSwapHistory(
            "pool",100,page_limit=2,max_backfill_pages=0,
            broker=B(),stream_key="pool:bounded")
        h.signature_rows={
            "live":{"signature":"live","blockTime":200,"slot":200,"err":None},
        }
        rpc=R()
        h._bootstrap_decision_window(rpc,200,30)
        self.assertFalse(h.decision_bootstrap_capacity_loss)
        h._bootstrap_decision_window(rpc,200,30)
        self.assertFalse(h.decision_bootstrap_capacity_loss)
        h._bootstrap_decision_window(rpc,200,30)
        self.assertTrue(h.decision_bootstrap_capacity_loss)
        self.assertEqual(rpc.befores[0],"live")
        self.assertEqual(len(set(rpc.befores)),3)

    def test_restart_restores_signature_ledger_and_reuses_cached_bodies(self):
        with tempfile.TemporaryDirectory() as td:
            broker=EvidenceBroker(os.path.join(td,"broker.sqlite3"))
            self.addCleanup(broker.close)
            first_rpc=FakeRPC()
            first=IncrementalPumpSwapHistory(
                "pool",100,page_limit=2,max_backfill_pages=2,
                max_new_pages=2,broker=broker,stream_key="pool:restart")
            first.refresh(first_rpc,103,research=True)
            self.assertGreater(len(first_rpc.tx_calls),0)
            persisted=broker.signature_rows("pumpswap_history","pool")
            self.assertTrue(persisted)

            second_rpc=FakeRPC()
            second=IncrementalPumpSwapHistory(
                "pool",100,page_limit=2,max_backfill_pages=2,
                max_new_pages=2,broker=broker,stream_key="pool:restart")
            self.assertGreater(second.restored_signature_rows,0)
            before=len(second_rpc.tx_calls)
            second.refresh(second_rpc,103,research=True)
            self.assertEqual(len(second_rpc.tx_calls),before)

    def test_recent_decision_window_is_decoded_before_older_backlog(self):
        class R:
            def __init__(self): self.calls=[]
            def call_many(self,method,params_list,priority=False,batch_size=8):
                self.calls.extend(x[0] for x in params_list)
                return [
                    {"slot":1,"meta":{"err":None,"logMessages":[]}}
                    for _ in params_list
                ]
        h=IncrementalPumpSwapHistory("pool",100,max_tx_per_refresh=2)
        h.signature_rows={
            "old":{"signature":"old","blockTime":110,"slot":1,"err":None},
            "new1":{"signature":"new1","blockTime":195,"slot":2,"err":None},
            "new2":{"signature":"new2","blockTime":199,"slot":3,"err":None},
        }
        rpc=R();h._decode_pending(rpc,200)
        self.assertEqual(set(rpc.calls),{"new1","new2"})
        self.assertNotIn("old",h.processed)

    def test_warm_live_stream_ignores_old_unknown_research_timestamp(self):
        class B:
            def signature_rows(self,*_args,**_kwargs): return []
            def remember_signatures(self,*_args,**_kwargs): return None
            def stream_status(self,*_args,**_kwargs):
                return {"covered":True}
        h=IncrementalPumpSwapHistory(
            "pool",100,broker=B(),stream_key="pool:live")
        h.signature_rows={
            "old-unknown":{
                "signature":"old-unknown","blockTime":None,
                "slot":1,"err":None,
            }
        }
        h.unknown_block_times=1
        h.stream_pending_transactions=0
        status=h.decision_window_status(200,30)
        self.assertTrue(status["complete"])
        self.assertTrue(status["stream_complete"])
        self.assertEqual(status["ignored_historical_unknown_block_times"],1)

    def test_decision_window_can_be_complete_while_second_leg_backlog_remains(self):
        h=IncrementalPumpSwapHistory("pool",100)
        h.signature_rows={
            "old":{"signature":"old","blockTime":110,"slot":1,"err":None},
            "boundary":{"signature":"boundary","blockTime":169,"slot":2,"err":None},
            "new":{"signature":"new","blockTime":195,"slot":3,"err":None},
        }
        h.processed={"boundary","new"}
        status=h.decision_window_status(200,30)
        self.assertTrue(status["complete"])
        self.assertFalse(h.complete(200))

if __name__=="__main__":
    unittest.main()

class RefreshBudgetRegressionTests(unittest.TestCase):
    def test_decision_decoder_uses_one_budget_across_chunks(self):
        clock=[1000.0]
        class B:
            def signature_rows(self,*_a,**_kw):return []
            def hydrate_transactions(self,rpc,sigs,**kw):
                rpc.append((list(sigs),kw['deadline']));clock[0]+=6.1
                return {s:None for s in sigs},dict(pending=len(sigs))
        history=IncrementalPumpSwapHistory('pool',900,broker=B())
        history.signature_rows={str(i):dict(signature=str(i),slot=i,blockTime=999,err=None) for i in range(48)}
        calls=[]
        with patch('meme_machine.pump_acceleration_history.time.time',side_effect=lambda:clock[0]):
            history._decode_pending(calls,1000,kind='pump_window')
        self.assertEqual(len(calls),1)
        self.assertEqual(history.tx_failures,16)

    def test_incomplete_current_window_does_not_start_second_leg_history_reads(self):
        class B:
            def signature_rows(self,*_a,**_kw):return []
            def stream_status(self,*_a,**_kw):return dict(covered=False)
        history=IncrementalPumpSwapHistory('pool',900,broker=B())
        with patch.object(history,'_ingest_stream_window'),patch.object(history,'_bootstrap_decision_window'),\
             patch.object(history,'_decode_pending'),patch.object(history,'_new_head') as head,\
             patch.object(history,'_backfill') as backfill:
            history.refresh(object(),1000,research=True)
        head.assert_not_called();backfill.assert_not_called()

    def test_bootstrap_hydration_clears_initial_stream_miss_without_another_rpc(self):
        class B(EvidenceBroker):
            first=True
            def hydrate_transactions(self,rpc,signatures,**kwargs):
                if self.first:
                    self.first=False
                    return {s:None for s in signatures},dict(pending=len(signatures),hydrated=0)
                return super().hydrate_transactions(rpc,signatures,**kwargs)
        class R(FakeRPC):
            def call_many(self,*args,**kwargs):
                result=super().call_many(*args,**kwargs)
                return [dict(tx,blockTime=100+tx['slot']) for tx in result]
        broker=B(':memory:',clock=lambda:103,sleeper=lambda _:None);self.addCleanup(broker.close)
        broker.stream_begin('pool:one',70)
        broker.record_event('pool:one',signature='s3',slot=3,observed_at=103)
        history=IncrementalPumpSwapHistory('pool',100,broker=broker,stream_key='pool:one')
        rpc=R();history.refresh(rpc,103)
        self.assertEqual(history.stream_pending_transactions,0)
        self.assertTrue(history.decision_window_status(103)['complete'])
        self.assertEqual(rpc.tx_calls.count('s3'),1)
