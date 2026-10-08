"""Shared offline source transport; importable without another test module."""
import asyncio
import json
import time
from meme_machine.lanes.pump.postgrad import PUMPSWAP_PROGRAM

class FakeSocket:
    def __init__(self):self.queue=asyncio.Queue();self.subs={};self.recv_count=0
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def send(self,raw):
        req=json.loads(raw);self.subs[req['id']]=req
        await self.queue.put(json.dumps(dict(id=req['id'],result=req['id'])))
    async def recv(self,decode=None):
        self.recv_count+=1
        raw=await self.queue.get()
        return raw.encode() if decode is False and isinstance(raw,str) else raw
    async def inject(self,slot,logs):
        for identity,req in self.subs.items():
            if req['method']!='blockSubscribe':continue
            tx=dict(transaction=dict(signatures=['synthetic'+str(slot)],message=dict(accountKeys=[PUMPSWAP_PROGRAM])),meta=dict(err=None,logMessages=logs))
            msg=dict(method='blockNotification',params=dict(subscription=identity,result=dict(value=dict(slot=slot,err=None,block=dict(parentSlot=slot-1,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),blockTime=int(time.time())-1,transactions=[tx])))))
            await self.queue.put(json.dumps(msg))
