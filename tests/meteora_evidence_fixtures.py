"""Native Meteora evidence fixtures; no external provider or other lane imports."""
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
