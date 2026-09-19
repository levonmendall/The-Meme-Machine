import unittest

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
