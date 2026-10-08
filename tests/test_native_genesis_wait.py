from contextlib import closing
import os
import sqlite3
import threading
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.operational.lane import (empty_native_reconciliation,unfunded_ramses_reconciliation,
    NativeReconciliationUnavailable,native_reconciliation,run_native)
from meme_machine.portfolio_accounting import PortfolioAccounting,LANES,inception_receipt


class NativeGenesisWait(unittest.TestCase):
    def test_native_read_budget_and_transient_failure_never_mask_integrity_or_unknown_interrupt(self):
        from meme_machine.operational import observation
        for proof in [dict(state='UNAVAILABLE',sqlite_code=sqlite3.SQLITE_BUSY),
                dict(state='UNAVAILABLE',sqlite_code=sqlite3.SQLITE_CANTOPEN),
                dict(state='UNAVAILABLE',sqlite_code=sqlite3.SQLITE_INTERRUPT,observation_deadline_exhausted=True)]:
            with patch.object(observation,'database',return_value=proof) as read:
                with self.assertRaises(NativeReconciliationUnavailable):native_reconciliation('/absent',None,'unavailable')
                self.assertEqual(read.call_args.kwargs['seconds'],5)
        for proof in [dict(state='FAIL_CLOSED',sqlite_code=sqlite3.SQLITE_CORRUPT),
                dict(state='UNAVAILABLE',sqlite_code=sqlite3.SQLITE_INTERRUPT),dict(state='UNAVAILABLE')]:
            with patch.object(observation,'database',return_value=proof):
                with self.assertRaises(RuntimeError) as failure:native_reconciliation('/absent',None,'unavailable')
                self.assertNotIsInstance(failure.exception,NativeReconciliationUnavailable)

    def test_transient_read_waits_in_same_pons_process_without_genesis_or_discovery(self):
        from meme_machine.operational import lane
        from meme_machine.runtime import stop,status,usd_valuation
        class Stop:
            waits=[]
            def wait(self,seconds):
                if threading.current_thread().name=='health':return True
                self.waits.append(seconds);return len(self.waits)==2
        requested=Stop()
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'MM_PAPER_EPOCH':'paper-fixture'}):
            root=Path(td);(root/'pons').mkdir();ids=dict(source_sha='a'*40,policy_hash='b'*64,config_hash='c'*64)
            with closing(PortfolioAccounting(root/'portfolio.sqlite')) as account:
                account.establish_inception(inception_receipt('paper-fixture','2026-10-05T00:00:00Z','fixture'),portfolio_identities=ids,lane_identities={name:ids for name in LANES})
                account.configure_family_sleeves()
            before=(root/'portfolio.sqlite').read_bytes();native_check=lane.empty_native_reconciliation;attempts=[]
            def check(*args):
                attempts.append(1)
                if len(attempts)==1:raise NativeReconciliationUnavailable('read_deadline')
                return native_check(*args)
            with patch.object(stop,'requested',requested),patch.object(status,'update') as update,\
                    patch.object(lane,'empty_native_reconciliation',side_effect=check),\
                    patch.object(usd_valuation,'native_reader') as reader:
                reader.return_value.side_effect=usd_valuation.ValuationUnavailable('no_executable_route')
                run_native(root,'pons')
            self.assertEqual(requested.waits,[15,15])
            self.assertEqual([call.kwargs['reconciled'] for call in update.call_args_list],[False,True])
            self.assertTrue(all(call.args==('FAIL_CLOSED',) and call.kwargs['discovery_enabled'] is False for call in update.call_args_list))
            self.assertEqual((root/'portfolio.sqlite').read_bytes(),before)
            self.assertFalse((root/'pons/native-genesis.json').exists())

    def test_no_ramses_qualifier_is_reconciled_without_funding_or_replacing_native_state(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'MM_PAPER_EPOCH':'paper-fixture'}):
            root=Path(td);folder=root/'ramses';folder.mkdir()
            ids=dict(source_sha='a'*40,policy_hash='b'*64,config_hash='c'*64)
            with closing(PortfolioAccounting(root/'portfolio.sqlite')) as account:
                account.establish_inception(inception_receipt('paper-fixture','2026-10-05T00:00:00Z','fixture'),portfolio_identities=ids,lane_identities={lane:ids for lane in LANES})
                account.configure_family_sleeves();before=account.snapshot()
            cache=folder/'robinhood-ramses-extended-market.sqlite.pipeline.sqlite'
            with sqlite3.connect(cache) as db:db.execute('CREATE TABLE observation(value)')
            original=cache.read_bytes()
            self.assertTrue(unfunded_ramses_reconciliation(root))
            self.assertEqual(cache.read_bytes(),original)
            with closing(PortfolioAccounting(root/'portfolio.sqlite')) as account:self.assertEqual(account.snapshot(),before)
            self.assertFalse((folder/'native-genesis.json').exists())
            manifest=folder/'robinhood-ramses-extended-market.sqlite.campaign';manifest.mkdir()
            self.assertFalse(unfunded_ramses_reconciliation(root))
            manifest.rmdir()
            (folder/'robinhood-ramses-continuation.json').write_text('{"active":true}')
            with self.assertRaisesRegex(RuntimeError,'native_continuation_present'):unfunded_ramses_reconciliation(root)

    def test_empty_lane_proof_readonly_and_existing_state_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'MM_PAPER_EPOCH':'paper-fixture'}):
            root=Path(td);(root/'pons').mkdir();ids=dict(source_sha='a'*40,policy_hash='b'*64,config_hash='c'*64)
            with closing(PortfolioAccounting(root/'portfolio.sqlite')) as account:
                account.establish_inception(inception_receipt('paper-fixture','2026-10-05T00:00:00Z','fixture'),portfolio_identities=ids,lane_identities={lane:ids for lane in LANES})
                account.configure_family_sleeves();before=account.snapshot()
            self.assertTrue(empty_native_reconciliation(root,'pons')['reconciled'])
            with closing(PortfolioAccounting(root/'portfolio.sqlite')) as account:self.assertEqual(before,account.snapshot())
            (root/'pons'/'native.sqlite').write_bytes(b'existing native state')
            with self.assertRaisesRegex(RuntimeError,'existing_native_store'):empty_native_reconciliation(root,'pons')
            self.assertEqual((root/'pons'/'native.sqlite').read_bytes(),b'existing native state')

    def test_epoch_mismatch_cannot_be_reported_reconciled(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'MM_PAPER_EPOCH':'wrong'}):
            root=Path(td);(root/'pons').mkdir();ids=dict(source_sha='a'*40,policy_hash='b'*64,config_hash='c'*64)
            with closing(PortfolioAccounting(root/'portfolio.sqlite')) as account:
                account.establish_inception(inception_receipt('paper-original','2026-10-05T00:00:00Z','fixture'),portfolio_identities=ids,lane_identities={lane:ids for lane in LANES})
            with self.assertRaisesRegex(RuntimeError,'not_reconciled'):empty_native_reconciliation(root,'pons')
