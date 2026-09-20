import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from robinhood_research import BoundaryError
from robinhood_research import ramses_extended_test as extended
from robinhood_research.ramses_campaign import CampaignBooks
from robinhood_research.ramses_strategy import POLICY_HASH,STRATEGY_DOMAIN
from robinhood_tests.test_ramses_capital_replay import decision

ASSET='0x'+'11'*20
OTHER='0x'+'22'*20

def screen(rows):
    return dict(policy_hash=POLICY_HASH,strategy_domain=STRATEGY_DOMAIN,rows=rows,
        finalized_block=100,finalized_hash='0x'+'11'*32,finalized_timestamp=1000,
        finalized_frontier_source='pinned_external_finalized_header')


class RamsesCampaignTests(unittest.TestCase):
    def test_assets_are_separate_genesis_is_frozen_and_losses_are_not_replenished(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'campaign'
            books=CampaignBooks(root,screen([dict(token_y=ASSET,paper_capital_quote_raw=1000),
                dict(token_y=OTHER,paper_capital_quote_raw=2)]))
            try:
                book=books.ledger(ASSET)
                book.reserve('one',pool='pool',decision=decision(1000),at=1);book.open('one',at=2)
                with self.assertRaisesRegex(BoundaryError,'unresolved'):books.ledger(OTHER)
                book.settle('one',pnl=dict(strategy_domain=STRATEGY_DOMAIN,net_result_quote=-100,unresolved_inventory=None),at=3)
                with self.assertRaisesRegex(BoundaryError,'capital_exhausted'):
                    books.ledger(ASSET).reserve('two',pool='pool',decision=decision(1000),at=4)
                with self.assertRaisesRegex(BoundaryError,'unfunded'):books.ledger('0x'+'33'*20)
                result=books.reconcile()
                self.assertEqual(result['by_quote_asset'][ASSET]['available'],900)
                self.assertEqual(result['by_quote_asset'][OTHER]['available'],2)
                self.assertFalse(result['unlike_quote_units_summed'])
                with self.assertRaisesRegex(BoundaryError,'existing_capital'):CampaignBooks(root,screen([]))
            finally:books.close()

    def test_campaign_keeps_one_process_budget_after_multiple_settlements(self):
        clock=[0];calls=[];ledger_ids=[]
        class Rpc:
            def verify_chain(self):return 4663
            def telemetry(self):return {}
            def call(self,*args,**kwargs):
                n=100+int(clock[0]//60)
                return dict(number=hex(n),hash='0x'+format(n,'064x'),parentHash='0x'+format(n-1,'064x'),timestamp=hex(1000+n))
        def scan(endpoint,**kwargs):
            header=kwargs['finalized_frontier'];value=screen([dict(pool='pool',token_y=ASSET,paper_capital_quote_raw=1000)])
            value.update(finalized_block=int(header['number'],16),finalized_hash=header['hash'],finalized_timestamp=int(header['timestamp'],16))
            return value
        def connected(endpoint,**kwargs):
            book=kwargs['campaign_ledger'];ledger_ids.append(id(book))
            identity=kwargs['lifecycle_prefix']+':'+str(len(calls));calls.append(identity)
            book.reserve(identity,pool='pool',decision=decision(500),at=len(calls)*3)
            book.open(identity,at=len(calls)*3+1)
            final=book.settle(identity,pnl=dict(strategy_domain=STRATEGY_DOMAIN,net_result_quote=10,unresolved_inventory=None),at=len(calls)*3+2)
            return dict(status='settled',lifecycle_id=identity,ledger_final=final,
                ledger_reconciliation=book.reconcile(),segments=[dict(terminal_equality=True)])
        with tempfile.TemporaryDirectory() as td,patch.object(extended,'REPORT',Path(td)/'report.json'), \
            patch.object(extended,'BoundedMultiRpc',return_value=Rpc()),patch.object(extended,'scan',side_effect=scan), \
            patch.object(extended,'_screen_summary',side_effect=lambda row:row),patch.object(extended,'select_qualifier',side_effect=lambda row:row['rows'][0]), \
            patch.object(extended,'run_connected',side_effect=connected),patch.object(extended.time,'monotonic',side_effect=lambda:clock[0]), \
            patch.object(extended.time,'time',side_effect=lambda:10000+clock[0]),patch.object(extended.time,'sleep',side_effect=lambda n:clock.__setitem__(0,clock[0]+n)):
            result=extended.run('unused',campaign=True,discovery_seconds=125,db_path=Path(td)/'paper.sqlite')
            self.assertEqual(len(result['natural_lifecycles']),3)
            self.assertEqual(len(set(calls)),3);self.assertEqual(len(set(ledger_ids)),1)
            self.assertEqual(result['campaign_accounting']['by_quote_asset'][ASSET]['paper_capital'],1000)
            self.assertEqual(result['campaign_accounting']['by_quote_asset'][ASSET]['available'],1030)
            self.assertEqual(clock[0],125)
            self.assertNotIn('forced_machinery',result)
            records=(Path(td)/'paper.sqlite.campaign/lifecycles.jsonl').read_text().splitlines()
            self.assertEqual(len(records),3)

    def test_four_hours_is_explicit_and_session_budget_matches_time_not_rate(self):
        with self.assertRaisesRegex(BoundaryError,'discovery_seconds'):extended.run('unused',discovery_seconds=14400)
        with patch.object(extended,'BoundedMultiRpc',side_effect=RuntimeError('offline-boundary')) as rpc:
            with self.assertRaisesRegex(RuntimeError,'offline-boundary'):extended.run('unused',campaign=True,discovery_seconds=14400)
            self.assertEqual(rpc.call_args.kwargs['max_sessions'],7)
            self.assertEqual(rpc.call_args.kwargs['batch_size'],1)
        self.assertEqual(extended.POLICY_HASH,POLICY_HASH)
