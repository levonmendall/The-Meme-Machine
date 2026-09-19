import unittest

from meme_machine.provider import RPC


class PartialBatchRetryTests(unittest.TestCase):
    def test_only_failed_batch_members_are_retried(self):
        class PartialRPC(RPC):
            def __init__(self):
                self.batch_requests=[]
                self.single_params=[]
                super().__init__(
                    "https://example.invalid",limit=40,
                    clock=lambda:100.0,sleeper=lambda _seconds:None)
            def _http(self,request):
                if isinstance(request,list):
                    self.batch_requests.append([x["params"] for x in request])
                    out=[]
                    for item in request:
                        if item["params"]==[2]:
                            out.append({"jsonrpc":"2.0","id":item["id"],
                                        "error":{"code":-32000}})
                        else:
                            out.append({"jsonrpc":"2.0","id":item["id"],
                                        "result":item["params"][0]*10})
                    return out
                self.single_params.append(request["params"])
                return {"jsonrpc":"2.0","id":request["id"],
                        "result":request["params"][0]*10}

        rpc=PartialRPC()
        result=rpc.call_many("getBlockTime",[[1],[2],[3]],True,batch_size=8)
        self.assertEqual(result,[10,20,30])
        self.assertEqual(rpc.batch_requests,[[[1],[2],[3]]])
        self.assertEqual(rpc.single_params,[[2]])
        self.assertEqual(rpc.retries,1)
        self.assertEqual(rpc.failures,1)
        self.assertEqual(rpc.calls,4)
        self.assertEqual(rpc.http_requests,2)

    def test_sixteen_member_batch_is_supported(self):
        class BatchRPC(RPC):
            def __init__(self):
                self.batch_sizes=[]
                super().__init__(
                    "https://example.invalid",limit=40,
                    clock=lambda:100.0,sleeper=lambda _seconds:None)
            def _http(self,request):
                if not isinstance(request,list):
                    raise AssertionError("expected batch")
                self.batch_sizes.append(len(request))
                return [
                    {"jsonrpc":"2.0","id":item["id"],"result":item["params"][0]}
                    for item in request
                ]
        rpc=BatchRPC()
        values=rpc.call_many(
            "getBlockTime",[[i] for i in range(16)],True,batch_size=16)
        self.assertEqual(values,list(range(16)))
        self.assertEqual(rpc.batch_sizes,[16])


if __name__=="__main__":
    unittest.main()
