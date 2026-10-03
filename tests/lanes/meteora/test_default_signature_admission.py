"""Default SDK signatures remain failed evidence, without physical hydration."""
import json
import os
import sqlite3
import tempfile
import unittest
import zlib
from unittest.mock import patch

from meme_machine.lanes.meteora.provider import Unavailable
from meme_machine.lanes.meteora.solana_evidence_broker import EvidenceBroker
from meme_machine.lanes.meteora.solana_evidence_consumers import StreamEvidenceService
from meme_machine.lanes.meteora.solana_read_rpc import ReadOnlyFailoverRPC
from meme_machine.lanes.meteora.solana_signature_identity import DEFAULT_SIGNATURE as ZERO


class Clock:
    def __init__(self):self.now=1000.
    def __call__(self):return self.now
    def sleep(self,n):self.now+=n


class Rpc:
    def __init__(self, result=True):self.requests=[];self.result=result
    def call_many(self,method,params,*args,**kwargs):
        self.requests.append((method,params))
        return [{'slot':1,'blockTime':1} if self.result else None for _ in params]


class DefaultSignatureTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        self.b=EvidenceBroker(':memory:',clock=self.clock,sleeper=self.clock.sleep)
        self.addCleanup(self.b.close)

    def test_repeated_prefetch_is_terminal_without_constructing_rpc(self):
        for i in range(30):
            self.b.consumers.register('pool',[ZERO],'stream_prefetch',1001+i)
        service=StreamEvidenceService(self.b,lambda:self.fail('invalid identity reached provider'))
        with patch.dict(os.environ,{'MM_CERT_GOVERNOR_DB':''}):
            for _ in range(3):self.assertFalse(service.step())
        self.assertEqual(self.b.db.execute('SELECT deadline,state,first_transport_at FROM evidence_consumers').fetchone(),
            (1001.,'invalid_default_transaction_signature',None))
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM evidence_terminals').fetchone()[0],1)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM acquisition_phases').fetchone()[0],1)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
        self.assertEqual(self.b.consumers.telemetry()['acquisition_failures'],{})
        with self.assertRaises(sqlite3.IntegrityError):
            with self.b.db:self.b.db.execute('DELETE FROM evidence_terminals')

    def test_mixed_batch_acquires_real_identity_once_and_never_qualifies_default(self):
        rpc=Rpc()
        for owner in ('pump','meteora'):
            result,meta=self.b.hydrate_transactions(rpc,[ZERO,'real',ZERO],kind='pump_window',
                deadline=self.clock()+4,owner=owner)
            self.assertIsNone(result[ZERO]);self.assertEqual(result['real']['slot'],1)
            self.assertEqual((meta['hydrated'],meta['pending']),(1,1))
        self.assertEqual([[p[0] for p in params] for _,params in rpc.requests],[['real']])
        self.assertEqual(self.b.db.execute("SELECT count(*) FROM evidence_terminals WHERE signature=? AND reason='invalid_default_transaction_signature'",(ZERO,)).fetchone()[0],2)
        self.assertEqual(self.b.db.execute("SELECT count(*) FROM jobs WHERE job_key=?",('tx:'+ZERO,)).fetchone()[0],0)

    def test_foreground_default_preserves_original_deadline_and_no_provider_failure(self):
        rpc=Rpc()
        result,meta=self.b.hydrate_transactions(rpc,[ZERO],kind='pump_window',deadline=1004,owner='window')
        self.assertEqual(result,{ZERO:None});self.assertEqual(meta['acquisition_batches'],0)
        self.assertEqual(rpc.requests,[])
        self.assertEqual(self.b.db.execute('SELECT deadline,reason FROM evidence_terminals').fetchone(),
            (1004.,'invalid_default_transaction_signature'))
        stats=self.b.consumers.telemetry()
        self.assertEqual(stats['acquisition_phase_attempts'],{'invalid_default_transaction_signature':1})
        self.assertEqual(stats['acquisition_failures'],{})

    def test_valid_null_can_recover_without_reviving_expired_consumer(self):
        rpc=Rpc(False)
        self.b.hydrate_transactions(rpc,['real'],kind='pump_window',deadline=1001,owner='old')
        self.clock.now=1002;rpc.result=True
        result,meta=self.b.hydrate_transactions(rpc,['real'],kind='pump_window',deadline=1004,owner='new')
        self.assertEqual(meta['pending'],0);self.assertEqual(len(rpc.requests),2)
        self.assertEqual(dict(self.b.db.execute('SELECT owner,state FROM evidence_consumers')),
            {'old':'consumer_deadline_expired','new':'evidence_complete'})

    def test_distinct_default_observations_preserve_raw_payload_and_valid_reentry(self):
        for slot,logs in ((1,['a']),(1,['b']),(2,['b'])):
            self.b.record_event('stream',signature=ZERO,address='pool',slot=slot,
                payload={'signature':ZERO,'logs':logs})
        self.b.record_event('stream',signature='real',address='pool',slot=3)
        rows=self.b.db.execute('SELECT signature,payload FROM stream_signature_archive').fetchall()
        self.assertEqual(len(rows),4)
        self.assertEqual(sum(json.loads(zlib.decompress(p))['signature']==ZERO for s,p in rows if s==ZERO),3)
        self.assertIsNone(self.b.get_transaction(ZERO))
        result,meta=self.b.hydrate_transactions(Rpc(),['real'],kind='pump_window',deadline=1004)
        self.assertEqual(meta['pending'],0)

    def test_direct_queue_and_cache_cannot_create_default_job_or_success(self):
        self.assertFalse(self.b.queue_transaction(ZERO,kind='pump_window',deadline=1004))
        with self.assertRaisesRegex(ValueError,'invalid_default_transaction_signature'):
            self.b.put_transaction(ZERO,{'slot':1})
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM immutable_transactions').fetchone()[0],0)

    def test_shared_rpc_routes_invalid_identity_to_terminal_without_transport(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,
            MM_SOLANA_EVIDENCE_BROKER_DB=td+'/broker.db',MM_CERT_GOVERNOR_DB=''):
            wire=[]
            def transport(q):
                wire.append(q);self.fail('default signature reached transport')
            rpc=ReadOnlyFailoverRPC('https://solana-mainnet.g.alchemy.com/v2/test',
                transport=transport,sleeper=lambda n:None)
            try:
                with self.assertRaisesRegex(Unavailable,'transaction_evidence_incomplete'):
                    rpc.call('getTransaction',[ZERO,dict(commitment='finalized',encoding='json',
                        maxSupportedTransactionVersion=1)],True)
                self.assertEqual(wire,[])
                with sqlite3.connect(td+'/broker.db') as db:
                    self.assertEqual(db.execute('SELECT reason FROM evidence_terminals').fetchone()[0],
                        'invalid_default_transaction_signature')
            finally:
                if hasattr(rpc,'_immutable_broker'):rpc._immutable_broker.close()

    def test_legacy_waiting_default_is_terminal_before_background_selection(self):
        with self.b.db:
            self.b.db.execute('INSERT INTO evidence_consumers(owner,signature,kind,deadline,created_at) VALUES(?,?,?,?,?)',
                ('legacy',ZERO,'stream_prefetch',1004,1000))
        self.assertEqual(self.b.consumers.batch(),[])
        self.assertEqual(self.b.db.execute('SELECT reason FROM evidence_terminals').fetchone()[0],
            'invalid_default_transaction_signature')
