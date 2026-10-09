"""Existing SQLite evidence, native V4 consumers, deterministic eviction/restart."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import sqlite3
import time
import unittest
from unittest.mock import patch

from meme_machine.runtime.robinhood.plane import Plane,canonical,digest
from meme_machine.runtime.robinhood.pons import durable_cache,shared_evidence_domain
from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
from meme_machine.lanes.pons import pons_selective_v4 as v4
from tests.test_pons_dense_v4_receipts import fixture,ENDPOINT


class DurableReceiptTests(unittest.TestCase):
    def test_source_generation_rebinds_long_lived_native_context_and_missing_artifact_refuses(self):
        from meme_machine.lanes.pons import pons
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
        with tempfile.TemporaryDirectory() as td:
            template=Path(td)/'template.json';template.write_bytes(pons.TEMPLATE.read_bytes())
            plane=Plane(Path(td)/'plane.sqlite')
            runtime=Runtime.__new__(Runtime);runtime.plane=plane;runtime.endpoint=ENDPOINT
            try:
                with patch.object(pons,'TEMPLATE',template):
                    first=runtime._position_context()
                    first.cache.remember_receipt('tx','bh',dict(transactionHash='tx',blockHash='bh',logs=[]))
                    self.assertIs(runtime._position_context(),first)
                    template.write_text(template.read_text()+' ')
                    second=runtime._position_context()
                    self.assertIsNot(first,second)
                    self.assertNotEqual(first.cache.domain,second.cache.domain)
                    self.assertIsNone(second.cache.receipt('tx','bh'))
                    template.unlink()
                    with self.assertRaises((OSError,ValueError)):runtime._position_context()
            finally:plane.close()

    def test_optional_retention_does_not_wait_on_a_busy_writer_or_change_native_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite');other=sqlite3.connect(plane.path,isolation_level=None)
            cache=durable_cache(plane,shared_evidence_domain(ENDPOINT))
            try:
                before=plane.db.execute('PRAGMA busy_timeout').fetchone()[0]
                other.execute('BEGIN IMMEDIATE');started=time.monotonic()
                cache.begin_receipts('current','pool',digest('cursor'))
                receipt=dict(transactionHash='tx',blockHash='bh',logs=[])
                cache.remember_receipt('tx','bh',receipt)
                self.assertLess(time.monotonic()-started,.1)
                self.assertEqual(cache.receipt('tx','bh'),receipt)
                self.assertEqual(plane.db.execute('PRAGMA busy_timeout').fetchone()[0],before)
                self.assertGreater(cache.counts['durable_busy_fallback'],0)
                other.execute('ROLLBACK')
                cache.remember_receipt('tx','bh',receipt);cache.acknowledge_receipts()
            finally:other.close();plane.close()

    def replay(self,plane,domain):
        tape,ctx,options=fixture(dense=False)
        ctx.cache=durable_cache(plane,domain)
        options['evidence_context']=ctx
        with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=tape),patch('time.monotonic',return_value=100):
            result=v4.collect_v4_activity(ENDPOINT,**options)
        return {k:v for k,v in result.items() if k!='provider_sessions'},tape,ctx

    def fill(self,plane,domain,count):
        # Batched fixture injection is not a provider request or production path.
        with plane.transaction():
            plane.db.executemany('INSERT INTO evidence VALUES(?,?,?,?,?)',
                [(domain+':receipt',canonical(['unused-'+str(i),'other']),canonical(dict(fixture=i)),canonical({}),1000+i)
                 for i in range(count)])

    def test_eviction_and_restart_reuse_native_receipts_while_each_consumer_owes_ack(self):
        with tempfile.TemporaryDirectory() as td:
            old=Plane(Path(td)/'old.sqlite',clock=lambda:100);new=Plane(Path(td)/'new.sqlite',clock=lambda:100)
            domain=shared_evidence_domain(ENDPOINT);generation=digest('native-frontier')
            try:
                baseline,old_tape,_=self.replay(old,'legacy')
                tape,ctx,options=fixture(dense=False);ctx.cache=durable_cache(new,domain)
                ctx.cache.begin_receipts('current','pool',generation)
                with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=tape),patch('time.monotonic',return_value=100):
                    first=v4.collect_v4_activity(ENDPOINT,**options)
                second=durable_cache(new,domain);second.begin_receipts('survivor','token',generation)
                for tx,bh in list(ctx.cache.receipts):self.assertIsNotNone(second.receipt(tx,bh))
                self.fill(old,'legacy',8192);old.maintain()
                self.fill(new,domain,8092)
                for i in range(200):
                    self.assertTrue(new.put_receipt(domain+':receipt',canonical(['later-'+str(i),'other']),dict(fixture=i),{}))
                self.assertEqual(new.db.execute('SELECT COUNT(*) FROM evidence WHERE namespace=?',(domain+':receipt',)).fetchone()[0],8192)
                ctx.cache.acknowledge_receipts()
                self.assertEqual(new.db.execute('SELECT COUNT(*) FROM receipt_obligations').fetchone()[0],100)
                old.close();new.close();old=Plane(Path(td)/'old.sqlite',clock=lambda:100);new=Plane(Path(td)/'new.sqlite',clock=lambda:100)
                a,original,_=self.replay(old,'legacy');b,optimized,_=self.replay(new,domain)
                self.assertEqual(a,baseline);self.assertEqual(a,b)
                self.assertEqual(original.methods['eth_getTransactionReceipt'],100)
                self.assertEqual(optimized.methods.get('eth_getTransactionReceipt',0),0)
                self.assertEqual(original.batches-optimized.batches,2)
                new.receipt_scope(domain+':receipt','survivor','token',generation,acknowledge=True)
                self.assertEqual(new.db.execute('SELECT COUNT(*) FROM receipt_obligations').fetchone()[0],0)
            finally:old.close();new.close()

    def test_generation_recovery_and_reorganization_clear_obligations_not_native_state(self):
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite');domain=shared_evidence_domain(ENDPOINT)
            try:
                cache=durable_cache(plane,domain);cache.begin_receipts('current','pool',digest(1))
                receipt=dict(transactionHash='tx',blockHash='old',logs=[])
                cache.remember_receipt('tx','old',receipt)
                self.assertEqual(plane.db.execute('SELECT COUNT(*) FROM receipt_obligations').fetchone()[0],1)
                cache.begin_receipts('current','pool',digest(2))
                self.assertEqual(plane.db.execute('SELECT COUNT(*) FROM receipt_obligations').fetchone()[0],0)
                self.assertIsNone(cache.receipt('tx','new'))
                cache.remember_receipt('tx','old',receipt);cache.invalidate_canonical_aliases()
                self.assertEqual(plane.db.execute('SELECT COUNT(*) FROM receipt_obligations').fetchone()[0],0)
                self.assertEqual(cache.receipt('tx','old'),receipt)
                self.assertNotEqual(shared_evidence_domain(ENDPOINT),shared_evidence_domain(ENDPOINT+'other'))
            finally:plane.close()

    def test_byte_and_record_admission_never_discards_pending_facts_or_provider_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite');ns=shared_evidence_domain(ENDPOINT)+':receipt'
            try:
                generation=digest('cursor');plane.receipt_scope(ns,'current','pool',generation)
                with plane.transaction():
                    plane.db.executemany('INSERT INTO evidence VALUES(?,?,?,?,?)',
                        [(ns,str(i),'{}','{}',i) for i in range(8192)])
                    plane.db.executemany('INSERT INTO receipt_obligations VALUES(?,?,?,?,?)',
                        [(ns,str(i),'current','pool',generation) for i in range(8192)])
                self.assertFalse(plane.put_receipt(ns,'new',dict(acquired=True),{},('survivor','token',generation)))
                self.assertEqual(plane.db.execute('SELECT COUNT(*) FROM receipt_obligations').fetchone()[0],8192)
                # Resource proof is accounting-only fixture pressure, no large allocation.
                with plane.transaction():plane.db.execute('UPDATE receipt_cache_usage SET bytes=?',(64*1024*1024,))
                self.assertFalse(plane.put_receipt(ns,'extra',dict(acquired=True),{}))
                self.assertEqual(plane.evidence(ns,'0')[0],{})
            finally:plane.close()

    def test_conflicting_receipt_and_independent_ack_never_grant_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite');domain=shared_evidence_domain(ENDPOINT)
            try:
                a=durable_cache(plane,domain);b=durable_cache(plane,domain)
                generation=digest('cursor');a.begin_receipts('current','pool',generation);b.begin_receipts('survivor','token',generation)
                r=dict(transactionHash='tx',blockHash='bh',logs=[])
                a.remember_receipt('tx','bh',r);self.assertEqual(b.receipt('tx','bh'),r)
                with self.assertRaisesRegex(Exception,'conflict'):b.remember_receipt('tx','bh',dict(r,logs=['changed']))
                a.acknowledge_receipts();self.assertEqual(plane.db.execute('SELECT consumer FROM receipt_obligations').fetchone()[0],'survivor')
            finally:plane.close()
