"""Delayed evidence is valued at acquisition without extending its expiry."""
from contextlib import closing
from decimal import Decimal, localcontext
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.portfolio_accounting import PortfolioAccounting,inception_receipt,LANES
from meme_machine.runtime.native_boundary import NativeBoundary
from meme_machine.runtime.usd_valuation import USDValue,ValuationUnavailable,utc

NOW=1791130000
IDS=dict(source_sha='a'*40,policy_hash='b'*64,config_hash='c'*64)

class NativeValuationCompletionTests(unittest.TestCase):
    def initialize(self,path):
        with closing(PortfolioAccounting(path)) as account:
            account.establish_inception(inception_receipt('offline-clock',utc(NOW),'inception'),
                portfolio_identities=IDS,lane_identities={lane:IDS for lane in LANES})
            account.configure_family_sleeves()

    def test_delayed_assets_through_boundary_and_same_epoch_pending_recovery(self):
        for lane,asset,decimals in [('pump','SOL',9),('pons','ETH',18),('ramses','USDG',6)]:
            with self.subTest(asset=asset),tempfile.TemporaryDirectory() as td:
                path=Path(td)/'portfolio.sqlite';self.initialize(path)
                calls=[]
                def reader(native_at):
                    calls.append(native_at)
                    return USDValue(asset,decimals,Decimal('1'),NOW+2,NOW+5,'delayed','e'*64)
                boundary=NativeBoundary(path,lane,SimpleNamespace(),value_reader=reader)
                with patch('meme_machine.runtime.native_boundary.time.time',return_value=NOW+3):
                    boundary.record('native','reserved',{'reserved':10**decimals},None,at=NOW,checksum='b'*64)
                self.assertEqual(calls,[NOW])
                event=boundary.prepared[0][1]
                self.assertEqual(event.at,utc(NOW+3));self.assertEqual(event.data['amount'],'1')
                self.assertEqual(event.native_journal_hash,'b'*64)
                restart=NativeBoundary(path,lane,SimpleNamespace(),value_reader=reader)
                with patch.object(restart,'journal_hashes',return_value={'b'*64}):restart.recover()
                self.assertFalse(restart.client.pending())
                with closing(PortfolioAccounting(path)) as account:
                    self.assertEqual(account.binding()['receipt']['epoch_id'],'offline-clock')
                    before=account.snapshot()
                with patch('meme_machine.runtime.native_boundary.time.time',return_value=NOW+6):
                    with self.assertRaises(ValuationUnavailable):
                        restart.record('stale','reserved',{'reserved':10**decimals},None,at=NOW,checksum='c'*64)
                with closing(PortfolioAccounting(path)) as account:self.assertEqual(account.snapshot(),before)
                self.assertFalse(restart.client.pending())

    def test_expiry_crossed_during_preparation_rejects_before_pending_write(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'portfolio.sqlite';self.initialize(path)
            value=USDValue('USDG',6,Decimal('1'),NOW+2,NOW+5,'delayed','e'*64)
            boundary=NativeBoundary(path,'ramses',SimpleNamespace(),value_reader=lambda at:value)
            with patch('meme_machine.runtime.native_boundary.time.time',side_effect=[NOW+3,NOW+3,NOW+6]):
                with self.assertRaises(ValuationUnavailable):
                    boundary.record('expired','reserved',{'reserved':1000000},None,at=NOW,checksum='b'*64)
            self.assertFalse(boundary.client.pending());self.assertFalse(boundary.prepared)

    def test_recurring_basis_release_is_persisted_once_and_pending_replay_is_exact(self):
        from fractions import Fraction
        from meme_machine.runtime.portfolio import NativePortfolio
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'portfolio.sqlite';self.initialize(path)
            client=NativePortfolio(path,'pons')
            evidence=USDValue('ETH',18,Decimal('1e18'),NOW,NOW+120,'offline','e'*64).evidence(NOW)
            for kind,data in [('reserve',{'amount':'1'}),('enter',{'asset':'ETH','basis':'1','fee':'0','strategy_id':'pons'}),
                              ('mark',{'state':'CURRENT','net_liquidation_value':'1.1'})]:
                client.deliver('native',event_key=kind,journal_hash='b'*64,kind=kind,at=utc(NOW),
                    data=data,value_evidence=evidence if kind!='reserve' else None)
            value=USDValue('ETH',18,Decimal('1e18'),NOW,NOW+120,'offline','e'*64)
            boundary=NativeBoundary(path,'pons',SimpleNamespace(),value_reader=lambda at:value)
            with localcontext() as context,patch('meme_machine.runtime.native_boundary.time.time',return_value=NOW+1):
                context.prec=3
                boundary.record('native','partial_harvest',dict(basis=2,realized=0),dict(basis=3,realized=0),
                    at=NOW+1,checksum='c'*64)
            fact=boundary.prepared[0][1]
            self.assertEqual(fact.data['basis_released'],'0.33333333333333333333333333334')
            restarted=NativeBoundary(path,'pons',SimpleNamespace(),value_reader=lambda at: (_ for _ in ()).throw(AssertionError('no revaluation on replay')))
            with patch.object(restarted,'journal_hashes',return_value={'c'*64}):restarted.recover();restarted.recover()
            self.assertFalse(restarted.client.pending())
            with closing(PortfolioAccounting(path)) as account:
                state=account.snapshot();row=next(iter(state['positions'].values()))
                self.assertEqual(row['mark'],{'state':'UNAVAILABLE'})
                self.assertEqual(state['available'],Decimal('500'))
                self.assertLessEqual(Fraction(row['realized_pnl']),Fraction(2,3))
                self.assertEqual(row['fees'],0)
                self.assertTrue(all(account._reconcile(state)['checks'].values()))
