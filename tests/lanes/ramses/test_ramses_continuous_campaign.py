import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.lanes.ramses import BoundaryError
from meme_machine.lanes.ramses import ramses_extended_test as extended
_campaign_candidate_boundary=extended._campaign_candidate_boundary
from meme_machine.lanes.ramses.ramses_campaign import CampaignBooks
from meme_machine.lanes.ramses.ramses_strategy import POLICY_HASH,STRATEGY_DOMAIN
from tests.lanes.ramses.test_ramses_capital_replay import decision

ASSET='0x'+'11'*20
OTHER='0x'+'22'*20

def screen(rows):
    return dict(policy_hash=POLICY_HASH,strategy_domain=STRATEGY_DOMAIN,rows=rows,
        finalized_block=100,finalized_hash='0x'+'11'*32,finalized_timestamp=1000,
        finalized_frontier_source='pinned_external_finalized_header')


class RamsesCampaignTests(unittest.TestCase):
    def test_funding_crashes_publish_once_with_original_budget_and_no_exposure(self):
        from meme_machine.lanes.ramses import ramses_campaign as native
        class Crash(BaseException):pass
        real_book=native.RamsesStrategyLedger;real_rename=native.os.rename
        for cut in ('before_genesis','after_genesis','before_publish','after_publish'):
            with self.subTest(cut=cut),tempfile.TemporaryDirectory() as td:
                root=Path(td)/'campaign';seen=[]
                initial=screen([dict(token_y=ASSET,paper_capital_quote_raw=1000),
                                dict(token_y=OTHER,paper_capital_quote_raw=2)])
                def book(*args,**kwargs):
                    if not seen and cut=='before_genesis':raise Crash()
                    value=real_book(*args,**kwargs);seen.append(args[0])
                    if len(seen)==1 and cut=='after_genesis':value.close();raise Crash()
                    return value
                def rename(*args):
                    if cut=='before_publish':raise Crash()
                    real_rename(*args)
                    if cut=='after_publish':raise Crash()
                with patch.object(native,'RamsesStrategyLedger',side_effect=book),patch.object(native.os,'rename',side_effect=rename):
                    with self.assertRaises(Crash):CampaignBooks(root,initial)
                location=root if root.exists() else CampaignBooks.pending_path(root)
                original=json.loads((location/'funding-intent.json').read_text())['manifest']
                if root.exists():books=CampaignBooks.recover(root)
                else:
                    # A later screen cannot replace the durable original budgets.
                    books=CampaignBooks(root,screen([dict(token_y=ASSET,paper_capital_quote_raw=9999)]))
                rec=books.reconcile();books.close()
                self.assertEqual(rec['manifest'],original)
                self.assertEqual(rec['position_count'],0)
                self.assertEqual(rec['by_quote_asset'][ASSET]['available'],1000)
                self.assertEqual(rec['by_quote_asset'][OTHER]['available'],2)
                self.assertFalse(CampaignBooks.pending_path(root).exists())
                again=CampaignBooks.recover(root)
                self.assertEqual(again.reconcile(),rec);again.close()

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

    def test_recovery_preserves_existing_open_position_and_loss_without_refunding(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'campaign'
            books=CampaignBooks(root,screen([dict(token_y=ASSET,paper_capital_quote_raw=1000)]))
            book=books.ledger(ASSET)
            book.reserve('original',pool='pool',decision=decision(500),at=1);book.open('original',at=2)
            before=books.reconcile();books.close()
            books=CampaignBooks.recover(root)
            self.assertEqual(books.reconcile(),before)
            with self.assertRaisesRegex(BoundaryError,'unresolved'):books.ledger(ASSET)
            books.books[ASSET].settle('original',pnl=dict(strategy_domain=STRATEGY_DOMAIN,
                net_result_quote=-100,unresolved_inventory=None),at=3)
            final=books.reconcile();books.close()
            for _ in range(2):
                books=CampaignBooks.recover(root)
                self.assertEqual(books.reconcile(),final)
                self.assertEqual(books.ledger(ASSET).reconcile()['available'],900)
                self.assertEqual(books.run_id,before['manifest']['run_id'])
                books.close()

    def test_missing_book_or_modified_pinned_screen_cannot_refund_capital(self):
        import gzip
        for fault in ('missing','screen','policy'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as td:
                root=Path(td)/'campaign'
                books=CampaignBooks(root,screen([dict(token_y=ASSET,paper_capital_quote_raw=1000)]));books.close()
                if fault=='missing':(root/(ASSET+'.sqlite')).unlink()
                elif fault=='screen':
                    with gzip.open(root/'initial-screen.json.gz','wt') as stream:
                        json.dump(screen([dict(token_y=ASSET,paper_capital_quote_raw=2000)]),stream)
                else:
                    path=root/'capital-manifest.json';body=json.loads(path.read_text());body['policy_hash']='wrong';path.write_text(json.dumps(body))
                before={p.name:p.read_bytes() for p in root.iterdir()}
                with self.assertRaisesRegex(BoundaryError,'recovery'):CampaignBooks.recover(root)
                self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})

    def test_campaign_keeps_one_process_budget_after_multiple_settlements(self):
        clock=[0];calls=[];ledger_ids=[];prefixes=[]
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
            book=kwargs['campaign_ledger'];ledger_ids.append(id(book));prefixes.append(kwargs['lifecycle_prefix'])
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
            self.assertEqual(len(set(prefixes)),3)
            self.assertEqual(result['campaign_accounting']['by_quote_asset'][ASSET]['paper_capital'],1000)
            self.assertEqual(result['campaign_accounting']['by_quote_asset'][ASSET]['available'],1030)
            self.assertEqual(clock[0],125)
            self.assertNotIn('forced_machinery',result)
            records=(Path(td)/'paper.sqlite.campaign/lifecycles.jsonl').read_text().splitlines()
            self.assertEqual(len(records),3)
            prior_id=result['campaign_accounting']['manifest']['run_id']
            resumed=extended.run('unused',campaign=True,discovery_seconds=60,db_path=Path(td)/'paper.sqlite')
            account=resumed['campaign_accounting']
            self.assertEqual(account['manifest']['run_id'],prior_id)
            self.assertEqual(account['by_quote_asset'][ASSET]['paper_capital'],1000)
            self.assertEqual(account['by_quote_asset'][ASSET]['available'],1040)
            self.assertEqual(account['position_count'],4)
            self.assertEqual(len(set(calls)),4)

    def test_repeat_entry_capacity_and_provider_boundaries_are_candidate_local(self):
        self.assertEqual(_campaign_candidate_boundary('ramses_strategy_capital_exhausted'),'capacity_censored')
        self.assertEqual(_campaign_candidate_boundary('connected_campaign_cost_envelope_unfunded'),'capacity_censored')
        self.assertEqual(_campaign_candidate_boundary('provider_http_429'),'provider_failed')
        self.assertEqual(_campaign_candidate_boundary('provider_shared_admission_deadline'),'provider_failed')
        self.assertIsNone(_campaign_candidate_boundary('connected_lifecycle_terminal_equality'))

    def test_four_hours_is_explicit_and_session_budget_matches_time_not_rate(self):
        with self.assertRaisesRegex(BoundaryError,'discovery_seconds'):extended.run('unused',discovery_seconds=14400)
        with patch.object(extended,'BoundedMultiRpc',side_effect=RuntimeError('offline-boundary')) as rpc:
            with self.assertRaisesRegex(RuntimeError,'offline-boundary'):extended.run('unused',campaign=True,discovery_seconds=14400)
            self.assertEqual(rpc.call_args.kwargs['max_sessions'],7)
            self.assertEqual(rpc.call_args.kwargs['batch_size'],1)
        self.assertEqual(extended.POLICY_HASH,POLICY_HASH)

    def test_unqualified_first_asset_does_not_freeze_later_qualified_asset_out(self):
        clock=[0];calls=[];ledger_ids=[]
        class Rpc:
            def verify_chain(self):return 4663
            def telemetry(self):return {}
            def call(self,*args,**kwargs):
                n=100+int(clock[0]//60)
                return dict(number=hex(n),hash='0x'+format(n,'064x'),parentHash='0x'+format(n-1,'064x'),timestamp=hex(1000+n))
        def scan(endpoint,**kwargs):
            header=kwargs['finalized_frontier']
            rows=[dict(pool='other',token_y=OTHER,paper_capital_quote_raw=2)] if clock[0]<60 else [dict(pool='pool',token_y=ASSET,paper_capital_quote_raw=1000)]
            value=screen(rows);value.update(finalized_block=int(header['number'],16),finalized_hash=header['hash'])
            return value
        def connected(endpoint,**kwargs):
            book=kwargs['campaign_ledger'];ledger_ids.append(id(book));identity=kwargs['lifecycle_prefix']+':'+str(len(calls));calls.append(identity)
            book.reserve(identity,pool='pool',decision=decision(500),at=len(calls)*3);book.open(identity,at=len(calls)*3+1)
            final=book.settle(identity,pnl=dict(strategy_domain=STRATEGY_DOMAIN,net_result_quote=10,unresolved_inventory=None),at=len(calls)*3+2)
            return dict(status='settled',lifecycle_id=identity,ledger_final=final,ledger_reconciliation=book.reconcile(),segments=[dict(terminal_equality=True)])
        with tempfile.TemporaryDirectory() as td,patch.object(extended,'REPORT',Path(td)/'report.json'), \
            patch.object(extended,'BoundedMultiRpc',return_value=Rpc()),patch.object(extended,'scan',side_effect=scan), \
            patch.object(extended,'_screen_summary',side_effect=lambda row:row),patch.object(extended,'select_qualifier',side_effect=lambda row:next((x for x in row['rows'] if x.get('token_y')==ASSET),None)), \
            patch.object(extended,'run_connected',side_effect=connected),patch.object(extended.time,'monotonic',side_effect=lambda:clock[0]), \
            patch.object(extended.time,'time',side_effect=lambda:10000+clock[0]),patch.object(extended.time,'sleep',side_effect=lambda n:clock.__setitem__(0,clock[0]+n)):
            result=extended.run('unused',campaign=True,discovery_seconds=125,db_path=Path(td)/'paper.sqlite')
            self.assertEqual(len(result['natural_lifecycles']),2)
            self.assertEqual(len(set(ledger_ids)),1)
            final=result['campaign_accounting']
            self.assertEqual(final['manifest']['source_finalized_block'],101)
            self.assertEqual(final['by_quote_asset'][ASSET]['paper_capital'],1000);self.assertNotIn(OTHER,final['by_quote_asset'])
            self.assertEqual(final['by_quote_asset'][ASSET]['available'],1020)
            self.assertEqual(clock[0],125)

    def test_unfundable_screen_cannot_create_an_empty_permanent_genesis(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'campaign'
            with self.assertRaisesRegex(BoundaryError,'funding_unavailable'):CampaignBooks(root,screen([]))
            self.assertFalse(root.exists())
            self.assertEqual(CampaignBooks.budgets_from_screen(screen([])),{})
            wrong=screen([]);wrong['policy_hash']='foreign'
            with self.assertRaisesRegex(BoundaryError,'foreign_screen'):CampaignBooks.budgets_from_screen(wrong)
