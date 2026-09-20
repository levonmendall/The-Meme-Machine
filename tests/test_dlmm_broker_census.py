import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from meme_machine.solana_evidence_broker import EvidenceBroker
from tests import solana_dlmm_independent_v1 as strategy


def row(signature,slot):
    return dict(signature=signature,slot=slot,transactionIndex=0,confirmationStatus='finalized',err=None)


class BrokerCensusTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.broker=EvidenceBroker(Path(self.tmp.name)/'broker.sqlite');self.addCleanup(self.broker.close)

    def test_cold_census_stops_at_first_authenticated_boundary(self):
        rpc=MagicMock();rpc.call.return_value=[row('new',101)]+[row(str(i),100-i) for i in range(63)]
        selected,meta=strategy._complete_signature_census(rpc,'pool',100,102,self.broker)
        self.assertEqual([x['signature'] for x in selected],['new','0'])
        self.assertEqual(meta['pages'],1)
        self.assertEqual(rpc.call.call_count,1)

    def test_incomplete_warm_bridge_does_not_advance_or_poison_cached_head(self):
        self.broker.remember_signatures('dlmm_interval','pool',[row('head',100),row('bound',99)],covered_through_slot=100)
        before=self.broker.signature_coverage('dlmm_interval','pool')
        rpc=MagicMock();rpc.call.return_value=[row('future-'+str(i),300-i) for i in range(64)]
        with patch.object(strategy,'MAX_SIGNATURE_CENSUS_PAGES',1):
            with self.assertRaisesRegex(Exception,'census_head_incomplete'):
                strategy._complete_signature_census(rpc,'pool',100,102,self.broker)
        self.assertEqual(self.broker.signature_coverage('dlmm_interval','pool'),before)
        self.assertEqual(len(self.broker.signature_rows('dlmm_interval','pool')),2)
        rpc.call.return_value=[row('next',101)]
        selected,meta=strategy._complete_signature_census(rpc,'pool',100,102,self.broker)
        self.assertEqual([x['signature'] for x in selected],['next','head'])
        self.assertEqual(rpc.call.call_args.args[1][1]['until'],'head')

    def test_pressure_and_missing_boundary_remain_fail_closed_before_publication(self):
        for page,reason in [([row(str(i),118-i) for i in range(17)]+[row('b',100)],'transaction_pressure_overflow'),
                            ([row('a',101)],'missing_start_boundary')]:
            rpc=MagicMock();rpc.call.return_value=page
            with self.assertRaisesRegex(Exception,reason):
                strategy._complete_signature_census(rpc,'pool',100,118,self.broker)
            self.assertEqual(self.broker.signature_coverage('dlmm_interval','pool')['covered_through_slot'],0)

if __name__=='__main__':unittest.main()
