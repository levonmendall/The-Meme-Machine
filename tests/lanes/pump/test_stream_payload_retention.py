"""Exercise actual finalized log ingress, including durable raw hint retention."""
import json
import threading
import unittest
import zlib
from unittest.mock import patch
from meme_machine.lanes.pump import solana_evidence_broker as module


def ingest(broker, values, *, stream_name='pumpswap_pool', address='pool'):
    stop=threading.Event()
    stream=module.DynamicAddressLogStream('wss://test.invalid',broker,stream_name,clock=lambda:1000)
    key=stream.add_address(address)
    queue=[];incoming=iter(values)
    class Socket:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def send(self,raw):
            request=json.loads(raw)
            assert request['params'][1]['commitment']=='finalized'
            queue.append(dict(id=request['id'],result=7))
        def recv(self,**kwargs):
            if queue:return json.dumps(queue.pop(0))
            try:value=next(incoming)
            except StopIteration:
                stop.set();raise TimeoutError()
            return json.dumps(dict(method='logsNotification',params=dict(subscription=7,
                result=dict(context=dict(slot=100),value=value))))
    with patch.object(module,'connect',return_value=Socket()):stream.run(stop)
    return key,stream


class StreamPayloadTests(unittest.TestCase):
    def test_real_ingress_retains_all_finalized_log_payloads_without_body_authority(self):
        b=module.EvidenceBroker(':memory:',clock=lambda:1000);self.addCleanup(b.close)
        values=[dict(signature='noise',err=None,logs=['Program Other111 invoke [1]','Program Other111 success']),
                dict(signature='ambiguous',err=None,logs=['Log truncated']),
                dict(signature='missing',err=None)]
        key,stream=ingest(b,values)
        self.assertEqual(stream.last_error_kind,None)
        self.assertEqual({r['signature']:r['payload'] for r in b.recent_events(key)},
                         {v['signature']:v for v in values})
        archived={s:json.loads(zlib.decompress(p)) for s,p in b.db.execute('SELECT signature,payload FROM stream_signature_archive')}
        self.assertEqual(archived,{v['signature']:v for v in values})
        self.assertEqual(b.db.execute('SELECT count(*) FROM immutable_transactions').fetchone()[0],0)
        self.assertEqual(b.db.execute('SELECT count(*) FROM evidence_consumers').fetchone()[0],0)
