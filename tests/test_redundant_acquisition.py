"""Same-evidence historical reuse and inactive getter parity; no market I/O."""
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from types import ModuleType,SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons import pons_selective_v4 as v4
from meme_machine.runtime.robinhood.plane import Plane
from meme_machine.runtime.robinhood.pons import durable_cache,shared_evidence_domain
from tests.test_pons_dense_v4_receipts import fixture,ENDPOINT
from tests import test_pons_protective_capacity as capacity
from engineering.redundant_acquisition.quoter import candidate_batch,manager_proof

BASE='030705397cf75766b5bffbea41abb8bf8db12104'


def original_v4():
    path='meme_machine/lanes/pons/pons_selective_v4.py'
    module=ModuleType('pr129_v4');module.__package__='meme_machine.lanes.pons'
    source=subprocess.check_output(['git','show',BASE+':'+path],text=True)
    exec(compile(source,path,'exec'),module.__dict__)
    return module


def history_replay(plane,*,module=v4,count=1,fork=False,sender=False,seed=0):
    rpc,ctx,options=fixture(relevant=count,total=count,dense=False,
        receipt_sender=sender,fork=fork,seed=seed)
    ctx.cache=durable_cache(plane,shared_evidence_domain(ENDPOINT))
    with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=rpc),\
            patch('time.monotonic',return_value=100):
        result=module.collect_v4_activity(ENDPOINT,**options)
    return {k:v for k,v in result.items() if k!='provider_sessions'},rpc,ctx


class HistoricalTransactionReuseTests(unittest.TestCase):
    def test_restart_and_independent_consumer_avoid_only_already_authenticated_sender_purchase(self):
        for count in (1,100):
            with self.subTest(transactions=count),tempfile.TemporaryDirectory() as td:
                old=Plane(Path(td)/'old.sqlite');new=Plane(Path(td)/'new.sqlite')
                try:
                    a,_,_=history_replay(old,module=original_v4(),count=count)
                    b,_,_=history_replay(new,count=count)
                    self.assertEqual(a,b)
                    old.close();new.close()
                    old=Plane(Path(td)/'old.sqlite');new=Plane(Path(td)/'new.sqlite')
                    a,baseline,_=history_replay(old,module=original_v4(),count=count)
                    b,optimized,_=history_replay(new,count=count)
                    self.assertEqual(a,b)
                    self.assertEqual(baseline.methods['eth_getTransactionReceipt'],0)
                    self.assertEqual(optimized.methods['eth_getTransactionReceipt'],0)
                    self.assertEqual(baseline.methods['eth_getTransactionByHash'],count)
                    self.assertEqual(optimized.methods['eth_getTransactionByHash'],0)
                    self.assertEqual(baseline.methods['eth_getBlockByNumber'],optimized.methods['eth_getBlockByNumber'])
                    self.assertEqual(baseline.batches-optimized.batches,(count+49)//50)
                finally:old.close();new.close()

    def test_new_transactions_and_changed_block_hash_still_require_original_facts(self):
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite')
            try:
                history_replay(plane)
                _,rpc,ctx=history_replay(plane,seed=1)
                self.assertEqual(rpc.methods['eth_getTransactionByHash'],1)
                self.assertEqual(rpc.methods['eth_getTransactionReceipt'],1)
                transaction=next(iter(ctx.cache.receipts.values()))
                if transaction.get('transactionHash'):
                    self.assertIsNone(ctx.cache.transaction(transaction['transactionHash'],'other-fork'))
            finally:plane.close()

    def test_canonical_reorganization_refuses_cached_receipt_and_sender(self):
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite')
            try:
                history_replay(plane)
                with self.assertRaisesRegex(BoundaryError,'canonical_header_membership'):
                    history_replay(plane,fork=True)
            finally:plane.close()

    def test_busy_durable_store_falls_back_without_wait_and_memory_stays_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite');other=sqlite3.connect(plane.path,isolation_level=None)
            try:
                history_replay(plane)
                other.execute('BEGIN IMMEDIATE')
                _,rpc,ctx=history_replay(plane)
                # SQLite WAL readers may still reuse an existing body while
                # optional writes refuse immediately. A new event still pays
                # for its sender and cannot wait for cache retention.
                self.assertEqual(rpc.methods['eth_getTransactionByHash'],0)
                _,missing,ctx=history_replay(plane,seed=1)
                self.assertEqual(missing.methods['eth_getTransactionByHash'],1)
                self.assertGreater(ctx.cache.counts['durable_busy_fallback'],0)
                self.assertEqual(plane.db.execute('PRAGMA busy_timeout').fetchone()[0],10000)
                other.execute('ROLLBACK')
                from meme_machine.lanes.pons.pons_selective_acquisition import ImmutableEvidenceCache
                cache=ImmutableEvidenceCache()
                for n in range(8200):
                    cache.remember_transaction(str(n),'bh',dict(hash=str(n),blockHash='bh',**{'from':'0x'+'12'*20}))
                self.assertEqual(len(cache.receipts),8192)
                self.assertLess(cache.telemetry()['accounted_cache_bytes'],16*1024*1024)
            finally:other.close();plane.close()

    def test_invalid_conflicting_or_other_provider_sender_never_suppresses_authentication(self):
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite')
            try:
                cache=durable_cache(plane,shared_evidence_domain(ENDPOINT))
                value=dict(hash='tx',blockHash='bh',**{'from':'0x'+'12'*20})
                cache.remember_transaction('tx','bh',value)
                namespaces=[r[0] for r in plane.db.execute('SELECT DISTINCT namespace FROM evidence')]
                self.assertEqual(namespaces,[cache.domain+':receipt'])
                self.assertEqual(plane.db.execute('SELECT records FROM receipt_cache_usage').fetchone()[0],1)
                for bad in (dict(value,hash='other'),dict(value,blockHash='fork'),dict(value,**{'from':'missing'})):
                    with self.assertRaisesRegex(BoundaryError,'transaction_identity'):
                        cache.remember_transaction('tx','bh',bad)
                with self.assertRaisesRegex(BoundaryError,'transaction_conflict'):
                    cache.remember_transaction('tx','bh',dict(value,**{'from':'0x'+'34'*20}))
                other=durable_cache(plane,shared_evidence_domain(ENDPOINT+'other'))
                self.assertIsNone(other.transaction('tx','bh'))
            finally:plane.close()

    def test_optional_senders_never_displace_receipts_at_shared_capacity(self):
        from meme_machine.lanes.pons.pons_selective_acquisition import ImmutableEvidenceCache
        from meme_machine.runtime.robinhood.plane import canonical
        with patch('meme_machine.lanes.pons.pons_selective_acquisition.CACHE_RECEIPTS',2):
            cache=ImmutableEvidenceCache()
            receipt=lambda tx:dict(transactionHash=tx,blockHash='bh')
            sender=lambda tx:dict(hash=tx,blockHash='bh',**{'from':'0x'+'12'*20})
            cache.remember_receipt('a','bh',receipt('a'))
            cache.remember_transaction('a','bh',sender('a'))
            cache.remember_receipt('b','bh',receipt('b'))
            self.assertEqual(cache.receipt('a','bh'),receipt('a'))
            self.assertEqual(cache.receipt('b','bh'),receipt('b'))
            cache.remember_transaction('b','bh',sender('b'))
            self.assertIsNone(cache.transaction('b','bh'))
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite')
            try:
                cache=durable_cache(plane,shared_evidence_domain(ENDPOINT));ns=cache.domain+':receipt'
                cache.remember_receipt('a','bh',receipt('a'))
                # Emulate other consumers occupying the original record ceiling.
                plane.db.execute('UPDATE receipt_cache_usage SET records=8192 WHERE namespace=?',(ns,))
                cache.remember_transaction('a','bh',sender('a'))
                self.assertIsNotNone(plane.evidence(ns,canonical(['a','bh'])))
                self.assertIsNone(plane.evidence(ns,canonical(['transaction','a','bh'])))
                # At full capacity ordinary receipt admission evicts optional
                # metadata first, preserving the oldest reusable receipt.
                plane.db.execute('UPDATE receipt_cache_usage SET records=1 WHERE namespace=?',(ns,))
                cache.remember_transaction('a','bh',sender('a'))
                plane.db.execute('UPDATE receipt_cache_usage SET records=8192 WHERE namespace=?',(ns,))
                cache.remember_receipt('b','bh',receipt('b'))
                self.assertIsNotNone(plane.evidence(ns,canonical(['a','bh'])))
                self.assertIsNone(plane.evidence(ns,canonical(['transaction','a','bh'])))
            finally:plane.close()


class InactiveImmutableGetterTests(unittest.TestCase):
    def replay(self,*,optimized,factor=1.,count=1,gas=1,unknown=False):
        test=capacity.ProtectiveCapacityTests();self.addCleanup(test.doCleanups)
        def prepare(runtime,rpc):
            rpc.gas=gas;value=rpc.value
            code=manager_proof()[0]
            def read(method,params):
                if method=='eth_getCode' and params[0].lower()==v4_quoter().lower():
                    return '0x6000' if unknown else code
                return value(method,params)
            rpc.value=read
            if optimized:
                original=rpc.batch
                rpc.batch=lambda calls,**kwargs:candidate_batch(SimpleNamespace(batch=original),calls,**kwargs)
        return capacity.replay(test,count,price_factor=factor,paced=False,latency=0,before_step=prepare)

    def test_native_economic_risk_and_execution_equivalence_at_all_winner_multiples_and_stop(self):
        for factor in (.6,1.,2.,5.,10.,25.,50.,100.,1000.):
            for count in (1,4):
                with self.subTest(multiple=factor,owners=count):
                    a,ra,old,_=self.replay(optimized=False,factor=factor,count=count)
                    b,rb,new,_=self.replay(optimized=True,factor=factor,count=count)
                    self.assertEqual(a,b);self.assertEqual(ra,rb)
                    self.assertEqual(old.methods['eth_call']-new.methods['eth_call'],1)
                    self.assertEqual(old.methods['eth_getCode'],new.methods['eth_getCode'])
                    self.assertEqual(old.methods['eth_gasPrice'],new.methods['eth_gasPrice'])
                    self.assertEqual(len(old.transports),len(new.transports))

    def test_gas_changed_without_swap_change_keeps_native_stop_and_fresh_gas(self):
        a,ra,old,_=self.replay(optimized=False,gas=10**10)
        b,rb,new,_=self.replay(optimized=True,gas=10**10)
        self.assertEqual(a,b);self.assertEqual(ra,rb)
        self.assertEqual(old.methods['eth_gasPrice'],new.methods['eth_gasPrice'])

    def test_unknown_or_changed_code_preserves_original_getter_with_explicit_fallback_cost(self):
        a,ra,old,_=self.replay(optimized=False,unknown=True)
        b,rb,new,_=self.replay(optimized=True,unknown=True)
        self.assertEqual(a,b);self.assertEqual(ra,rb)
        self.assertEqual(old.methods,new.methods)
        self.assertEqual(len(new.transports),len(old.transports)+1)

    def test_no_trading_controller_imports_inactive_candidate(self):
        root=Path(__file__).resolve().parents[1]/'meme_machine'
        self.assertFalse(any('redundant_acquisition' in p.read_text() for p in root.rglob('*.py')))


def v4_quoter():
    from meme_machine.lanes.pons.pons_natural_paper import V4_QUOTER
    return V4_QUOTER


class PumpScoutSliceTests(unittest.TestCase):
    def test_operational_slice_retains_every_consumed_field_and_filter(self):
        from meme_machine import solana_selective_source as source
        with patch.dict(os.environ,{'MM_OPERATIONAL_PHASE':'continuous'},clear=True):
            request=source.scout_request()
        self.assertEqual(set(request.accounts),{'p'})
        self.assertEqual(request.accounts_data_slice[0].offset,0)
        self.assertEqual(request.accounts_data_slice[0].length,49)
        # The exact producer filter still nominates every Pump curve.
        self.assertEqual(list(request.accounts['p'].owner),[source.PROGRAMS['pump']])
        self.assertEqual(request.accounts['p'].filters[0].memcmp.offset,0)
        self.assertEqual(len(request.accounts['p'].filters[0].memcmp.bytes),8)

    def test_native_scout_observations_identical_for_all_reserve_and_activity_cases(self):
        from meme_machine import solana_selective_source as source
        from meme_machine.yellowstone import geyser_pb2 as pb
        from meme_machine.lanes.pump import pump
        for reserve,supply in ((0,0),(0,100),(1,100),(100,100),(101,100)):
            for complete in (0,1):
                for startup in (False,True):
                    update=pb.SubscribeUpdate(filters=['p'])
                    item=update.account;item.slot=100;item.is_startup=startup
                    account=item.account;account.pubkey=bytes([12])*32
                    account.owner=pump.un58(source.PROGRAMS['pump'])
                    account.txn_signature=bytes([13])*64
                    raw=bytearray(56);raw[24:32]=reserve.to_bytes(8,'little')
                    raw[40:48]=supply.to_bytes(8,'little');raw[48]=complete
                    raw[49:]=b'UNUSED!'
                    observed=[]
                    history=SimpleNamespace(observe=lambda *a,**kw:observed.append((a,kw)))
                    with patch.object(source,'install',return_value=history):
                        for width in (56,49):
                            account.data=bytes(raw[:width])
                            source.commit_scout(object(),update,101)
                    self.assertEqual(observed[0],observed[1])
                    self.assertEqual(len(observed),2)
                    before=pb.SubscribeUpdate();before.CopyFrom(update)
                    before.account.account.data=bytes(raw)
                    self.assertEqual(before.ByteSize()-update.ByteSize(),7)

    def test_legacy_meteora_slice_and_incomplete_pump_frame_fallback_remain(self):
        from meme_machine import solana_selective_source as source
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        from meme_machine.yellowstone import geyser_pb2 as pb
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(source.scout_request().accounts_data_slice[0].length,56)
        update=pb.SubscribeUpdate(filters=['p']);update.account.account.data=bytes(48)
        update.account.account.pubkey=bytes([12])*32
        with patch.object(source,'install',return_value=SimpleNamespace()):
            with self.assertRaisesRegex(EvidenceUnavailable,'candidate_scout_fields_missing'):
                source.commit_scout(object(),update,101)
