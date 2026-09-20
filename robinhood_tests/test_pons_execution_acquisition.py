from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from robinhood_research import BoundaryError
from robinhood_research.abi import calldata
from robinhood_research.evidence import Store
from robinhood_research.pons_selective_continuation import POLICY_HASH
from robinhood_research.pons_selective_capital import CohortCapital
from robinhood_research.pons_selective_paper import _curve_quote,run_lifecycle,STRATEGY_CAPITAL_QUOTE
from robinhood_research.pons_natural_paper import _curve_quote as serial_quote,RESEARCH_RECIPIENT
from robinhood_tests.test_pons_selective_continuation import state

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
    def test_identical_native_buy_and_sell_quotes_use_two_transports(self):
        for side,amount in [('buy',10**15),('sell',10**20)]:
            outputs=[];counts=[]
            for function in (serial_quote,_curve_quote):
                rpc=FakeRPC();store=Store(':memory:')
                with patch('robinhood_research.pons_natural_paper.time.time',return_value=320),patch('robinhood_research.pons_natural_paper.time.monotonic',side_effect=[10,13]):
                    quote,meta=function(rpc,candidate(),side,amount,21000,store,'test',local_freshness=True)
                outputs.append((asdict(quote),meta));counts.append((rpc.transports,rpc.logical));store.close()
            self.assertEqual(outputs[0],outputs[1]);self.assertEqual(counts[1][0],2)
            self.assertEqual(counts[0][1],counts[1][1]);self.assertGreater(counts[0][0],counts[1][0])

    def test_batch_time_remains_inside_five_second_gate_and_header_change_fails(self):
        for latency,changed,error in [(6,False,'stale_state'),(2,True,'header_changed')]:
            store=Store(':memory:')
            with patch('robinhood_research.pons_natural_paper.time.time',return_value=320),patch('robinhood_research.pons_natural_paper.time.monotonic',side_effect=[10,10+latency]):
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
            with patch('robinhood_research.pons_selective_paper.paper_rpc',return_value=rpc),patch('robinhood_research.pons_selective_paper._gas_quote',return_value=(21000,1)),patch('robinhood_research.pons_selective_paper._wait_curve_quote',side_effect=BoundaryError('stale_state')),patch('robinhood_research.pons_selective_paper.time.sleep'),patch('robinhood_research.pons_selective_paper.time.time',return_value=100):
                result=run_lifecycle('unused',evaluation,db_path=db,capital_path=capital)
            self.assertEqual(result['status'],'entry_failed');self.assertEqual(result['boundary'],'stale_state')
            position=result['final_position'];self.assertEqual(position['status'],'settled')
            self.assertEqual(position['entry_tokens'],0);self.assertEqual(position['cost'],0)
            pool=CohortCapital(capital,STRATEGY_CAPITAL_QUOTE);book=pool.reconcile()
            self.assertEqual(book['reserved'],0);self.assertEqual(book['unsettled'],0)
            self.assertEqual(book['cash'],STRATEGY_CAPITAL_QUOTE);self.assertTrue(book['capital_integral_complete'])
            with self.assertRaisesRegex(BoundaryError,'duplicate_settlement'):pool.settle(position['id'],position,at=101)

    def test_filled_position_cannot_be_released_as_an_unfilled_cancellation(self):
        from robinhood_tests.test_pons_partial_accounting import PartialAccountingTests
        from robinhood_research.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from robinhood_research.pons_selective_paper import _cancel_proven_unfilled
        from robinhood_research.evidence import digest
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
