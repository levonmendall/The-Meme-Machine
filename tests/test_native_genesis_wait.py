from contextlib import closing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.operational.lane import empty_native_reconciliation
from meme_machine.portfolio_accounting import PortfolioAccounting,LANES,inception_receipt


class NativeGenesisWait(unittest.TestCase):
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
