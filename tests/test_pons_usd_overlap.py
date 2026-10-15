"""Existing native USD acquisition overlaps due Pons work; no market I/O."""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch,MagicMock

from meme_machine.runtime import usd_valuation as usd
from tests.test_robinhood_usd_valuation import ReadRPC,NOW


class PonsUSDOverlapTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,MM_PONS_USD_ACQUISITION_OVERLAP='1');self.env.start()
        self.addCleanup(self.env.stop)
        self.clock=patch.object(usd.time,'time',return_value=NOW);self.clock.start();self.addCleanup(self.clock.stop)
        self.saved=(usd._pons_prefetch_pool,usd._pons_prefetch_pending)
        usd._pons_prefetch_pool=usd._pons_prefetch_pending=None
        def restore():
            if usd._pons_prefetch_pool is not None:usd._pons_prefetch_pool.shutdown(wait=True)
            usd._pons_prefetch_pool,usd._pons_prefetch_pending=self.saved
        self.addCleanup(restore)

    def test_one_pending_original_reader_serves_concurrent_current_and_survivor(self):
        from meme_machine.runtime.provider_purchases import work_label
        from meme_machine.lanes.pons.provider_admission import priority
        reader=usd.NativeValueReader('pons',rpc=ReadRPC());start=threading.Event();release=threading.Event()
        original=reader._read;labels=[]
        def delayed(*args):
            labels.append((work_label(),priority('pons')));start.set()
            self.assertTrue(release.wait(3));return original(*args)
        with patch.object(usd,'native_reader',return_value=reader),patch.object(reader,'_read',side_effect=delayed):
            a=usd.prefetch_pons_usd(3,consumer='current');self.assertTrue(start.wait(2))
            try:
                self.assertIs(usd.prefetch_pons_usd(3,consumer='survivor'),a)
                self.assertFalse(a.done())
            finally:release.set()
            value=a.result(timeout=3);before=len(reader.rpc.calls)
            self.assertEqual(len(labels),1)
            self.assertIs(reader(NOW+2),value)
            self.assertEqual(len(reader.rpc.calls),before)
            self.assertEqual(value.valid_until,NOW+5)
        self.assertEqual(labels[0][0]['operation'],'pons_held_protection')
        self.assertEqual(labels[0][1],0)

    def test_compatible_cache_needs_no_thread_or_provider_and_retains_original_expiry(self):
        reader=usd.NativeValueReader('pons',rpc=ReadRPC());value=reader(NOW);before=len(reader.rpc.calls)
        with patch.object(usd,'native_reader',return_value=reader):
            self.assertIsNone(usd.prefetch_pons_usd(3,consumer='survivor'))
        self.assertIsNone(usd._pons_prefetch_pool);self.assertEqual(len(reader.rpc.calls),before)
        with self.assertRaises(usd.ValuationUnavailable):value.amount(0,NOW+6)

    def test_required_usd_rpcs_receive_consumption_deadline_and_restore_outer_context(self):
        from meme_machine.lanes.pons.provider_admission import priority
        rpc=ReadRPC();reader=usd.NativeValueReader('pons',rpc=rpc)
        original=rpc.call;seen=[]
        def checked(*args,**kwargs):
            seen.append((priority(kwargs.get('scope','connectivity')),rpc.evidence_deadline))
            return original(*args,**kwargs)
        with patch.object(usd,'native_reader',return_value=reader),patch.object(rpc,'call',side_effect=checked),\
             patch.object(usd.time,'monotonic',return_value=100):
            value=usd.prefetch_pons_usd(3,consumer='survivor').result(timeout=3)
        self.assertTrue(seen)
        self.assertTrue(all(row==(0,103) for row in seen),seen)
        self.assertIsNone(rpc.evidence_deadline)
        self.assertEqual(value.valid_until,NOW+5)
        # A supplied earlier controller deadline remains authoritative.
        rpc.evidence_deadline=101;reader.cached=None;seen.clear()
        with patch.object(rpc,'call',side_effect=checked),patch.object(usd.time,'monotonic',return_value=100):
            reader(NOW,valid_through=NOW+3)
        self.assertTrue(all(row[1]==101 for row in seen),seen)
        self.assertEqual(rpc.evidence_deadline,101)

    def test_usd_failure_restores_deadline_without_publishing_financial_evidence(self):
        rpc=ReadRPC();rpc.evidence_deadline=101;rpc.failed=True
        reader=usd.NativeValueReader('pons',rpc=rpc)
        with patch.object(usd.time,'monotonic',return_value=100):
            with self.assertRaises(usd.ValuationUnavailable):reader(NOW,valid_through=NOW+3)
        self.assertIsNone(reader.cached);self.assertEqual(rpc.evidence_deadline,101)

    def test_failure_has_fixed_diagnostic_and_cannot_create_valid_USD(self):
        reader=usd.NativeValueReader('pons',rpc=ReadRPC());reader.rpc.failed=True
        with patch.object(usd,'native_reader',return_value=reader),self.assertLogs(usd.__name__,level='WARNING') as logs:
            future=usd.prefetch_pons_usd(3,consumer='survivor')
            with self.assertRaises(usd.ValuationUnavailable):future.result(timeout=3)
            usd._pons_prefetch_pool.shutdown(wait=True)
        self.assertIsNone(reader.cached)
        self.assertIn('pons_USD_prefetch_unavailable',' '.join(logs.output))
        self.assertNotIn('private-provider-secret',' '.join(logs.output))

    def test_busy_foreground_reader_does_not_block_or_queue_optional_prefetch(self):
        reader=usd.NativeValueReader('pons',rpc=ReadRPC());started=threading.Event();release=threading.Event()
        def busy():
            with reader._lock:started.set();release.wait(3)
        thread=threading.Thread(target=busy);thread.start();self.assertTrue(started.wait(2))
        try:
            with patch.object(usd,'native_reader',return_value=reader):
                self.assertIsNone(usd.prefetch_pons_usd(3,consumer='survivor'))
            self.assertIsNone(usd._pons_prefetch_pool);self.assertFalse(reader.rpc.calls)
        finally:release.set();thread.join(3)

    def test_disabled_overlap_and_invalid_horizon_cannot_start_provider_work(self):
        with patch.object(usd,'native_reader',side_effect=AssertionError('provider path forbidden')):
            for n in (0,6,3.0,True):
                with self.assertRaises(usd.ValuationUnavailable):usd.prefetch_pons_usd(n,consumer='current')
            with patch.dict(os.environ,MM_PONS_USD_ACQUISITION_OVERLAP='0'):
                self.assertIsNone(usd.prefetch_pons_usd(3,consumer='survivor'))

    def test_accounting_boundary_reuses_same_reader_only_for_enabled_Pons(self):
        from meme_machine.runtime import native_boundary
        reader=object()
        with patch.dict(os.environ,MM_PORTFOLIO_ACCOUNTING_DB='offline-only'),\
             patch.object(usd,'native_reader',return_value=reader),\
             patch.object(native_boundary,'NativeBoundary',return_value=MagicMock()) as boundary:
            native_boundary.attach(object(),'pons')
            self.assertIs(boundary.call_args.kwargs['value_reader'],reader)
            native_boundary.attach(object(),'pump')
            self.assertIsInstance(boundary.call_args.kwargs['value_reader'],usd.NativeValueReader)

    def test_supervisor_installs_overlap_only_in_Pons_worker(self):
        from meme_machine.operational.supervisor import Supervisor
        with tempfile.TemporaryDirectory() as td:
            supervisor=Supervisor.__new__(Supervisor)
            supervisor.root=Path(td);supervisor.epoch='isolated-test-epoch';supervisor.offline=True
            with patch('meme_machine.operational.supervisor.require_active'):
                self.assertEqual(supervisor.environment('pons')['MM_PONS_USD_ACQUISITION_OVERLAP'],'1')
                self.assertEqual(supervisor.environment('pump')['MM_PONS_USD_ACQUISITION_OVERLAP'],'0')
                for lane in ('meteora','ramses','solana'):
                    self.assertNotIn('MM_PONS_USD_ACQUISITION_OVERLAP',supervisor.environment(lane))
