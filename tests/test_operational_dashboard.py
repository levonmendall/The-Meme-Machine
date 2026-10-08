from contextlib import closing
from decimal import Decimal
import json,tempfile,time,unittest
from pathlib import Path

from dashboard.model import Reader
from meme_machine.operational.supervisor import Supervisor
from meme_machine.portfolio_snapshot_transport import load_snapshot,apply_snapshot
from meme_machine.runtime.portfolio import NativePortfolio
from meme_machine.portfolio_lane_integration import usd_evidence
from meme_machine.runtime.usd_valuation import utc


class OperationalDashboard(unittest.TestCase):
    def test_bounded_feed_replica_and_retired_totals_preserve_exact_portfolio(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);service=Supervisor(root/'fixtures',offline=True);service.initialize()
            try:
                client=NativePortfolio(service.root/'portfolio.sqlite','pump');at=utc(time.time())
                value=usd_evidence('fixture','a'*64,at,utc(time.time()+120))
                for kind,data in [('reserve',{'amount':'6.25'}),('enter',{'asset':'fixture','basis':'6.25','fee':'0','strategy_id':'pump'}),('settle',{'gross_proceeds':'7.25','fee':'0','exit_reason':'fixture'})]:
                    client.deliver('closed',event_key=kind,journal_hash='e'*64,kind=kind,at=at,data=data,value_evidence=value if kind!='reserve' else None)
                service.publish()
                reader=Reader(service.root/'inception.json',service.root/'portfolio.json',service.root/'health.json')
                before=reader.view()
                self.assertEqual(Decimal(before['portfolio']['metrics']['realized_pnl']['value']),Decimal('1'))
                with service.account() as account:account.compact(keep_closed=0)
                service.publish();view=reader.view()
                self.assertEqual(view['portfolio']['reconciliation']['state'],'CURRENT')
                self.assertEqual(Decimal(view['lanes']['pump']['metrics']['realized_pnl']['value']),Decimal('1'))
                self.assertEqual(Decimal(view['portfolio']['metrics']['equity']['value']),Decimal('501'))
                self.assertEqual(view['lanes']['pump']['metrics']['completed_trades']['value'],1)
                self.assertEqual(view['lanes']['pump']['metrics']['win_rate']['state'],'UNAVAILABLE')
                bundle=load_snapshot(service.root/'dashboard-snapshot.json')
                result=apply_snapshot(service.root/'dashboard-snapshot.json',root/'replica',retain=2)
                self.assertTrue(result['applied'])
                self.assertEqual(bundle['epoch_id'],service.epoch)
                self.assertLess((service.root/'dashboard-snapshot.json').stat().st_size,4*1024*1024)
            finally:service.lock.close()
