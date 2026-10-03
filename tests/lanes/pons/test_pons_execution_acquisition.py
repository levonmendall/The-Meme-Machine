from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.abi import calldata
from meme_machine.lanes.pons.evidence import Store
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
from meme_machine.lanes.pons.pons_selective_paper import _curve_quote,run_lifecycle,STRATEGY_CAPITAL_QUOTE
from meme_machine.lanes.pons.pons_natural_paper import _curve_quote as serial_quote,RESEARCH_RECIPIENT
from tests.lanes.pons.test_pons_selective_continuation import state
from certification.execution_capacity import resize

CURVE='0x'+'11'*20

def word(n):return hex(n)[2:].zfill(64)

class FakeRPC:
    def __init__(self,changed=False):
        self.transports=0;self.logical=0;self.changed=changed
        self.header=dict(number='0xc',hash='0xabc',parentHash='0xparent',timestamp='0x64')
        self.values={calldata('getReserves()'):'0x'+word(2*10**18)+word(800*10**24),
            calldata('realQuoteReserve()'):'0x'+word(8*10**17),
            calldata('reservedTokens()'):'0x'+word(100*10**24),
            calldata('graduated()'):'0x'+word(0),
            calldata('currentSnipeTaxBps(address)',RESEARCH_RECIPIENT):'0x'+word(0)}
    def value(self,m,p):
        self.logical+=1
        if m=='eth_getBlockByNumber':
            return dict(self.header,hash='0xchanged') if self.changed and p[0]!='latest' else self.header.copy()
        if m=='eth_gasPrice':return '0x1'
        self.assert_pinned(p);return self.values[p[0]['data']]
    def assert_pinned(self,p):
        assert p[0]['to']==CURVE and p[1]=='0xc'
    def call(self,m,p,*,scope):self.transports+=1;return self.value(m,p)
    def batch(self,calls,*,scope):self.transports+=1;return [self.value(m,p) for m,p in calls]

def candidate():return dict(curve=CURVE,auth={'immutables':{'feeBps':100,'creatorTaxBps':50}},report={'reads':[]})

class ExecutionAcquisitionTests(unittest.TestCase):
    def test_fill_signal_decay_releases_both_books_without_a_trade(self):
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        from meme_machine.lanes.pons.pons_selective_ledger import JOURNAL_CATEGORY
        import json
        fixture=PartialAccountingTests()
        for persistent,age,expected in ((False,0,'entry_signal_decay'),(True,20,'entry_quote_stale_after_confirmation')):
            with self.subTest(expected=expected),tempfile.TemporaryDirectory() as tmp:
                db=Path(tmp)/'paper.sqlite';capital=Path(tmp)/'capital.sqlite'
                curve=MagicMock();curve.buy_with_snipe.return_value=dict(refund=0,ready_to_graduate=False,tokens_out=1000)
                evaluation=dict(vector=dict(current_threshold_pass=True,policy_hash=POLICY_HASH,
                    proposed_size={'amount_quote':100},evidence_available_at=100),
                    candidate=dict(receipt={'gasUsed':hex(21000)},curve='m',state=curve),
                    token='token',curve='m',source_transaction='source')
                rpc=MagicMock();rpc.telemetry.return_value={}
                prefix='meme_machine.lanes.pons.pons_selective_paper.'
                with patch(prefix+'_validate_final_entry'),patch(prefix+'_confirm_entry_delta',return_value=({},[],{})),\
                     patch(prefix+'_entry_capacity',side_effect=lambda meta,amount,gas:resize(amount,1,lambda n:100,ordinary_limit=600)),\
                     patch(prefix+'paper_rpc',return_value=rpc),patch(prefix+'_gas_quote',return_value=(2,1)),\
                     patch(prefix+'_wait_curve_quote',return_value=(fixture.quote(102,'buy',100,1000),{},None)),\
                     patch(prefix+'_refresh_entry_persistence_signal',return_value=({}, {}, [])),\
                     patch(prefix+'entry_signal_persistence',return_value={'persistent':persistent,'reasons':[]}),\
                     patch(prefix+'time.sleep'),patch(prefix+'time.time',return_value=102+age):
                    result=run_lifecycle('unused',evaluation,db_path=db,capital_path=capital)
                self.assertEqual(result['entry_failure'],expected)
                rec=CohortCapital(capital,STRATEGY_CAPITAL_QUOTE).reconcile()
                self.assertEqual((rec['reserved'],rec['unsettled'],rec['realized']),(0,0,0))
                store=Store(db)
                events=[json.loads(x[0]) for x in store.db.execute('SELECT body FROM records WHERE category=?',(JOURNAL_CATEGORY,))]
                self.assertEqual([e['action'] for e in sorted(events,key=lambda e:e['position']['version'])],['reserve','cancel'])
                store.close()

    def test_identical_native_buy_and_sell_quotes_use_two_transports(self):
        for side,amount in [('buy',10**15),('sell',10**20)]:
            outputs=[];counts=[]
            for function in (serial_quote,_curve_quote):
                rpc=FakeRPC();store=Store(':memory:')
                with patch('meme_machine.lanes.pons.pons_natural_paper.time.time',return_value=320),patch('meme_machine.lanes.pons.pons_natural_paper.time.monotonic',side_effect=[10,13]):
                    quote,meta=function(rpc,candidate(),side,amount,21000,store,'test',local_freshness=True)
                outputs.append((asdict(quote),meta));counts.append((rpc.transports,rpc.logical));store.close()
            self.assertEqual(outputs[0],outputs[1]);self.assertEqual(counts[1][0],2)
            self.assertEqual(counts[0][1],counts[1][1]);self.assertGreater(counts[0][0],counts[1][0])

    def test_batch_time_remains_inside_five_second_gate_and_header_change_fails(self):
        for latency,changed,error in [(6,False,'stale_state'),(2,True,'header_changed')]:
            store=Store(':memory:')
            with patch('meme_machine.lanes.pons.pons_natural_paper.time.time',return_value=320),patch('meme_machine.lanes.pons.pons_natural_paper.time.monotonic',side_effect=[10,10+latency]):
                with self.assertRaisesRegex(BoundaryError,error):
                    _curve_quote(FakeRPC(changed),candidate(),'buy',10**15,21000,store,'test',local_freshness=True)
            store.close()

    def test_stale_entry_cancels_native_reservation_and_releases_cohort_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'paper.sqlite';capital=Path(tmp)/'capital.sqlite'
            evaluation=dict(vector=dict(current_threshold_pass=True,policy_hash=POLICY_HASH,
                proposed_size={'amount_quote':2500000000000000},evidence_available_at=100),
                candidate=dict(receipt={'gasUsed':hex(21000)},curve=CURVE,state=state()),
                token='token',curve=CURVE,source_transaction='source')
            rpc=MagicMock();rpc.telemetry.return_value={}
            with patch('meme_machine.lanes.pons.pons_selective_paper.paper_rpc',return_value=rpc),patch('meme_machine.lanes.pons.pons_selective_paper._gas_quote',return_value=(21000,1)),patch('meme_machine.lanes.pons.pons_selective_paper._wait_curve_quote',side_effect=BoundaryError('stale_state')),patch('meme_machine.lanes.pons.pons_selective_paper.time.sleep'),patch('meme_machine.lanes.pons.pons_selective_paper.time.time',return_value=100):
                result=run_lifecycle('unused',evaluation,db_path=db,capital_path=capital)
            self.assertEqual(result['status'],'entry_failed');self.assertEqual(result['boundary'],'stale_state')
            position=result['final_position'];self.assertEqual(position['status'],'settled')
            self.assertEqual(position['entry_tokens'],0);self.assertEqual(position['cost'],0)
            pool=CohortCapital(capital,STRATEGY_CAPITAL_QUOTE);book=pool.reconcile()
            self.assertEqual(book['reserved'],0);self.assertEqual(book['unsettled'],0)
            self.assertEqual(book['cash'],STRATEGY_CAPITAL_QUOTE);self.assertTrue(book['capital_integral_complete'])
            with self.assertRaisesRegex(BoundaryError,'duplicate_settlement'):pool.settle(position['id'],position,at=101)

    def test_filled_position_cannot_be_released_as_an_unfilled_cancellation(self):
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_paper import _cancel_proven_unfilled
        from meme_machine.lanes.pons.evidence import digest
        fixture=PartialAccountingTests()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trial.sqlite';store=Store(path)
            guard=CohortCapital(Path(tmp)/'capital.sqlite',1000)
            paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=POLICY_HASH,on_commit=guard.observe)
            decision=fixture.features(10)
            guard.reserve('x',120,at=10,decision_hash=digest(decision),trial_path=path)
            paper.reserve('x',market='m',amount=100,gas_budget=20,now=10,features=decision)
            paper.advance('x',now=11,action='entry',quote=fixture.quote(11,'buy',100,1000))
            before=guard.reconcile()
            self.assertIsNone(_cancel_proven_unfilled(paper,'x',guard,'stale_state'))
            self.assertEqual(guard.reconcile(),before);self.assertEqual(before['reserved'],120)
            self.assertEqual(paper._get('x')['status'],'open');store.close()

class MonitorReceiptReuseRegression(unittest.TestCase):
    def test_overlapping_monitor_windows_share_only_hash_bound_receipts(self):
        from meme_machine.lanes.pons import pons_selective_paper as paper
        from meme_machine.lanes.pons import pons_selective_acquisition as acquisition
        from meme_machine.lanes.pons.immutable_rpc import EvidenceStore,Reuse
        from meme_machine.lanes.pons.provider_topology import PacedRpc
        store=EvidenceStore();self.addCleanup(store.db.close)
        seen=[];header=dict(number='0x1',hash='block',timestamp='0x64')
        event=dict(transactionHash='tx',blockHash='block')
        def transport(method,params):
            seen.append((method,params))
            return dict(transactionHash='tx',blockHash='block')
        rpc=PacedRpc('https://robinhood-mainnet.g.alchemy.com/v2/offline',role='test',requests_per_second=2,transport=transport)
        rpc.evidence_reuse=Reuse('https://robinhood-mainnet.g.alchemy.com/v2/offline',store,'pons')
        def context(endpoint):
            ctx=acquisition.SelectiveEvidenceContext(endpoint)
            ctx.acquire=lambda *a,**k:rpc
            return ctx
        def batched(endpoint,calls,scope,**kwargs):
            if calls[0][0]=='eth_getLogs':return [[event]],[]
            if calls[0][0]=='eth_getBlockByHash':return [header],[]
            ctx=kwargs['evidence_context']
            self.assertEqual(ctx.receipt_pins,{'tx':'block'})
            return ctx.batch(calls,scope),[]
        with patch.object(paper,'evidence_rpc') as locator, \
                patch.object(paper,'_header_search',return_value=header), \
                patch.object(paper,'_batched',side_effect=batched), \
                patch.object(paper,'SelectiveEvidenceContext',side_effect=context), \
                patch.object(paper,'raw_event',return_value=dict(event_at=100,decoded={},block=1,transaction_hash='tx',log_index=0)), \
                patch.object(paper,'normalized_trade',return_value={'trade':'authenticated'}):
            first=paper._curve_logs('https://robinhood-mainnet.g.alchemy.com/v2/offline','curve',header)
            second=paper._curve_logs('https://robinhood-mainnet.g.alchemy.com/v2/offline','curve',header)
        self.assertEqual(first,second)
        self.assertEqual(seen,[('eth_getTransactionReceipt',['tx'])])
