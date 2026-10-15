"""Adversarial exact-money authority, replay, and source-to-screen proofs."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from decimal import Decimal, getcontext, localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from dashboard.model import Reader, decimal as reader_money
from meme_machine.exact_money import INTEGER_DIGITS, FRACTIONAL_PLACES, arithmetic, money, amount, proportional_basis_release
from meme_machine.portfolio_accounting import PortfolioAccounting, canonical, digest, _encode_checkpoint
from meme_machine.portfolio_lane_integration import _money as lane_money
from meme_machine.portfolio_snapshot_transport import build_snapshot, validate_snapshot, apply_snapshot, current_paths, SnapshotTransportError
from meme_machine.runtime.usd_valuation import NativeValueReader, USDValue, sol_usd
from tests import test_portfolio_accounting as accounting_fixture
from tests import test_portfolio_lane_integration as lane_fixture
from tests.test_robinhood_usd_valuation import ReadRPC, NOW


class ExactMoneyContract(unittest.TestCase):
    def test_checkpoint_checks_money_even_inside_historical_collections(self):
        from meme_machine.portfolio_accounting import _decode_checkpoint
        valid = {"history": [{"value": {"decimal": "0." + "0" * 28 + "1"}}]}
        self.assertEqual(_encode_checkpoint(_decode_checkpoint(valid)), valid)
        for collection in ("history", "delivery_receipts"):
            for value in ("0." + "0" * 29 + "1", "1" + "0" * 40):
                with self.subTest(collection=collection, value=value), self.assertRaises(ValueError):
                    _decode_checkpoint({collection: [{"value": {"decimal": value}}]})

    def test_mutation_validation_work_does_not_rescan_retained_history(self):
        import meme_machine.exact_money as contract
        t = accounting_fixture.SharedPortfolioAccountingTests(); t.setUp()
        try:
            t.activate()
            state = t.account.snapshot()
            state["history"] = [{"at": "historical", "value": "0", "labels": ["immutable"] * 32}
                                for _ in range(2000)]
            state["delivery_receipts"] = {str(i): {"body": {"data": ["validated"] * 32}}
                                          for i in range(512)}
            original = contract.validate_decimals
            visits = 0
            def bounded(value):
                nonlocal visits
                visits += 1
                if visits > 256:
                    raise AssertionError("mutation rescanned immutable history/receipts")
                return original(value)
            with patch.object(contract, "validate_decimals", bounded):
                self.assertTrue(all(t.account._reconcile(state)["checks"].values()))
            for key in ("available", "shared_costs"):
                invalid = deepcopy(state); invalid[key] = Decimal("1e40")
                with self.subTest(key=key), self.assertRaises(ValueError):
                    t.account._reconcile(invalid)
        finally:
            t.tearDown()

    def test_boundary_envelope_is_shared_without_rounding(self):
        maximum='9'*INTEGER_DIGITS+'.'+'9'*FRACTIONAL_PLACES
        inside=('0.'+'0'*(FRACTIONAL_PLACES-1)+'1',maximum,'-'+maximum,
                '123456789012345678901234567890.123456789012345678901234')
        with localcontext() as context:
            context.prec=3
            for value in inside:
                self.assertEqual(amount(money(value)),value)
                self.assertEqual(lane_money(value),value)
                self.assertEqual(reader_money(value),Decimal(value))
            for value in ('1'+'0'*INTEGER_DIGITS, '0.'+'0'*FRACTIONAL_PLACES+'1',
                          1.0, True, 'NaN', 'Infinity', '1e-29'):
                for parser in (money,lane_money,reader_money):
                    with self.subTest(value=value,parser=parser),self.assertRaises(ValueError):parser(value)
            with self.assertRaises(ValueError):money(Decimal('1e-30'))
            with self.assertRaises(ValueError):money(Decimal('1e40'))

    def test_local_arithmetic_does_not_leak_and_aggregate_overflow_fails(self):
        value=Decimal('9'*INTEGER_DIGITS+'.'+'9'*FRACTIONAL_PLACES)
        def work(precision):
            with localcontext() as caller:
                caller.prec=precision
                with arithmetic():
                    result=value+Decimal('0.'+'0'*(FRACTIONAL_PLACES-1)+'1')
                    self.assertEqual(result,Decimal('1'+'0'*INTEGER_DIGITS))
                    with self.assertRaises(ValueError):money(result)
                self.assertEqual(getcontext().prec,precision)
        original=getcontext().copy()
        with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(work,(2,7,28)))
        self.assertEqual(getcontext().prec,original.prec)
        self.assertEqual(getcontext().traps,original.traps)

    def test_actual_authenticated_pons_path_has_29_exact_places(self):
        rpc=ReadRPC();rpc.route_output=2500001
        with localcontext() as caller,patch('meme_machine.runtime.usd_valuation.time.time',return_value=NOW):
            caller.prec=3
            value=NativeValueReader('pons',rpc=rpc)(NOW).amount(1234567890123456789,NOW)
            self.assertEqual(amount(value),'3086.85185510674045860270552731229')
            self.assertEqual(lane_money(value),amount(value))
            self.assertEqual(reader_money(amount(value)),value)
            self.assertEqual(getcontext().prec,3)

    def test_sol_and_usdg_amounts_are_exact_under_hostile_context(self):
        with localcontext() as context:
            context.prec=3
            sol=USDValue('SOL',9,Decimal('123.456789'),100,200,'s','a'*64)
            usdg=USDValue('USDG',6,Decimal('1.00013961'),100,200,'u','a'*64)
            self.assertEqual(amount(sol.amount(123456789,100)),'15.241578750190521')
            self.assertEqual(amount(usdg.amount(1234567,100)),'1.23473935789887')
            with self.assertRaises(ValueError):sol.amount(10**100,100)

    def test_native_recurring_basis_fraction_is_conservative_and_exactly_representable(self):
        from fractions import Fraction
        with localcontext() as context:
            context.prec=2
            value=proportional_basis_release(Decimal('1'),1,3)
            self.assertEqual(amount(value),'0.33333333333333333333333333334')
            self.assertGreaterEqual(Fraction(value),Fraction(1,3))
            self.assertLess(Fraction(value)-Fraction(1,3),Fraction(1,10**29))
            self.assertEqual(proportional_basis_release(Decimal('1'),1,4),Decimal('0.25'))
            self.assertEqual(proportional_basis_release(Decimal('1'),3,3),Decimal('1'))
            with self.assertRaisesRegex(ValueError,'below_money_resolution'):
                proportional_basis_release(Decimal('1e-29'),1,2)


class CanonicalLifecycleMoney(unittest.TestCase):
    def setUp(self):
        self.t=accounting_fixture.SharedPortfolioAccountingTests();self.t.setUp();self.t.activate()
        self.addCleanup(self.t.tearDown)

    def mutate(self,life,kind,lane='pump',*,released='10',added='0',proceeds='12',fee='0'):
        t=self.t
        if kind in ('partial','harvest'):
            at=t.at()
            t.account.realize(epoch_id=t.EPOCH,event_id='realize-'+str(t.counter),lifecycle_id=life,
                basis_released=released,gross_proceeds=proceeds,fee=fee,at=at,
                provenance=t.provenance(lane,t.counter,valued=True,as_of=at),harvest=kind=='harvest')
        else:
            at=t.at();reservation='rebalance-r'+str(t.counter)
            with arithmetic():reserved=max(Decimal('0.01'),Decimal(added)+Decimal(fee))
            t.account.reserve(epoch_id=t.EPOCH,event_id='reserve-r'+str(t.counter),reservation_id=reservation,
                lifecycle_id=life,lane=lane,amount=reserved,at=at,provenance=t.provenance(lane,t.counter))
            at=t.at()
            t.account.rebalance(epoch_id=t.EPOCH,event_id='rebalance-'+str(t.counter),lifecycle_id=life,
                reservation_id=reservation,basis_released=released,basis_added=added,gross_proceeds=proceeds,
                fee=fee,at=at,provenance=t.provenance(lane,t.counter,valued=True,as_of=at))

    def restart(self):
        t=self.t;before=t.account.snapshot();t.account.close()
        t.account=PortfolioAccounting(t.database,receipt_path=t.receipt_path,export_path=t.export_path)
        self.assertEqual(_encode_checkpoint(t.account.snapshot()),_encode_checkpoint(before))

    def screen(self,export):
        t=self.t
        snapshot=build_snapshot(json.loads(t.receipt_path.read_text()),export)
        self.assertEqual(validate_snapshot(snapshot),snapshot)
        replica=t.root/'replica';bundle=t.root/'bundle.json'
        bundle.write_text(json.dumps(snapshot));apply_snapshot(bundle,replica)
        paths=current_paths(replica)
        view=Reader(paths['inception_path'],paths['accounting_path'],mode='canonical',clock=lambda:__import__('datetime').datetime.fromisoformat(export['as_of']).timestamp()).view()
        self.assertNotEqual(view['state'],'FAIL_CLOSED')
        self.assertEqual(view['portfolio']['metrics']['realized_pnl']['value'],export['balances']['realized_pnl'])
        return view

    def test_mark_invalidation_and_fresh_restoration_for_all_mutations(self):
        for label,lane,kind,released,added in (
            ('partial','pump','partial','10','0'),('harvest','pons','harvest','10','0'),
            ('release','meteora','rebalance','10','0'),('add','pump','rebalance','0','10'),
            ('mixed','ramses','rebalance','10','10')):
            with self.subTest(label=label):
                t=self.t;life=t.reserve_enter(lane,basis='40',fee='0')
                t.current_mark(lane,life,'50')
                self.mutate(life,kind,lane,released=released,added=added)
                self.assertEqual(t.account.snapshot()['positions'][life]['mark'],{'state':'UNAVAILABLE'})
                export=t.publish();view=self.screen(export)
                self.assertIsNone(export['balances']['unrealized_pnl']);self.assertIsNone(export['balances']['equity'])
                self.assertIsNone(view['portfolio']['metrics']['equity']['value'])
                self.assertIsNone(view['portfolio']['metrics']['unrealized_pnl']['value'])
                self.assertEqual(view['portfolio']['metrics']['realized_pnl']['state'],'CURRENT')
                self.restart()
                t.current_mark(lane,life,'45')
                self.assertEqual(t.account.snapshot()['positions'][life]['mark']['state'],'CURRENT')
                export=t.publish();view=self.screen(export)
                self.assertEqual(view['portfolio']['metrics']['equity']['value'],export['balances']['equity'])
                t.settle(lane,life,'45',fee='0');self.assertIsNone(t.account.snapshot()['positions'][life]['mark'])

    def test_exact_large_money_partial_fee_shared_cost_compaction_replay_and_screen(self):
        t=self.t;life=t.reserve_enter(basis='100',fee='0')
        gross='123456789012345678901234567890.12345678901234567890123456789'
        tiny='0.'+'0'*28+'1'
        with localcontext() as hostile:
            hostile.prec=3
            self.mutate(life,'partial',released='10',proceeds=gross,fee=tiny)
            at=t.at();t.account.charge_shared_cost(epoch_id=t.EPOCH,event_id='shared-long',amount=tiny,at=at,
                provenance=t.provenance(None,t.counter,valued=True,as_of=at))
            t.current_mark('pump',life,'90')
            export=t.publish();self.screen(export)
            with arithmetic():
                self.assertEqual(Decimal(export['balances']['realized_pnl']),Decimal(gross)-10-Decimal(tiny)*2)
                self.assertEqual(Decimal(export['balances']['equity']),500+Decimal(export['balances']['realized_pnl']))
            self.restart()
            before=_encode_checkpoint(t.account.snapshot())
            t.account.compact()
            after_checkpoint=_encode_checkpoint(t.account.snapshot())
            # Compaction adds delivery receipts; all canonical state and money
            # otherwise remain exactly the same, including decimal scale.
            before.pop('delivery_receipts',None);after_checkpoint.pop('delivery_receipts',None)
            self.assertEqual(canonical(after_checkpoint),canonical(before))
            after=t.publish();self.screen(after);self.restart()
            self.assertEqual(after['balances'],export['balances'])
            self.assertEqual(t.account.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_many_partial_realizations_and_staged_adds_are_exact(self):
        t=self.t;life=t.reserve_enter(basis='100',fee='0')
        tiny='0.'+'0'*28+'1';proceeds='0.01000000000000000000000000001'
        with localcontext() as hostile:
            hostile.prec=3
            for i in range(24):
                self.mutate(life,'partial',released='0.01',proceeds=proceeds,fee=tiny)
                self.mutate(life,'rebalance',released='0.01',added='0.01',proceeds=proceeds,fee=tiny)
            row=t.account.snapshot()['positions'][life]
            self.assertEqual(row['remaining_basis'],Decimal('99.76'))
            self.assertEqual(row['realized_pnl'],0)
            with arithmetic():self.assertEqual(row['fees'],Decimal(tiny)*48)
            self.assertEqual(row['gross_result'],row['fees'])
            self.restart();t.account.compact();self.restart()
            self.assertEqual(t.account.snapshot()['positions'][life]['remaining_basis'],Decimal('99.76'))

    def test_maximum_integer_precision_mutation_replay_and_explicit_overflow_rollback(self):
        t=self.t;life=t.reserve_enter(basis='100',fee='0')
        value='1'+'0'*39+'.'+'12345678901234567890123456789'
        with localcontext() as hostile:
            hostile.prec=2
            self.mutate(life,'partial',released='1',proceeds=value)
            self.assertEqual(t.account.snapshot()['positions'][life]['gross_proceeds'],Decimal(value))
            self.restart();t.current_mark('pump',life,'99');self.screen(t.publish())
            before=_encode_checkpoint(t.account.snapshot())
            # Every input fits, but the resulting available-cash magnitude
            # would exceed 40 digits. Reject the entire mutation explicitly.
            with self.assertRaisesRegex(ValueError,'invalid_decimal'):
                self.mutate(life,'partial',released='1',proceeds='9'*40)
            self.assertEqual(_encode_checkpoint(t.account.snapshot()),before)
            self.restart()

    def test_retired_lifecycle_accumulations_keep_exact_results(self):
        t=self.t;tiny='0.'+'0'*28+'1'
        with localcontext() as hostile:
            hostile.prec=3
            for i in range(20):
                life=t.reserve_enter(basis='1',fee='0')
                t.settle('pump',life,'1.00000000000000000000000000001',fee='0')
            before=t.publish();t.account.compact(keep_closed=0);self.restart()
            after=t.publish();self.screen(after)
            self.assertEqual(after['balances'],before['balances'])
            with arithmetic():self.assertEqual(Decimal(after['balances']['realized_pnl']),Decimal(tiny)*20)
            self.assertEqual(after['retired_lane_totals']['pump']['count'],20)

    def test_old_checkpoint_invalid_mark_is_derived_from_order_without_rewriting_journal(self):
        t=self.t;life=t.reserve_enter(fee='0');t.current_mark('pump',life,'120')
        old_mark=deepcopy(t.account.snapshot()['positions'][life]['mark'])
        self.mutate(life,'partial');t.account.compact()
        # Emulate an authentic pre-repair checkpoint with the defect: same
        # journal identity and economics, CURRENT value preceding mutation.
        state=t.account.snapshot();state['positions'][life]['mark']=old_mark
        encoded=_encode_checkpoint(state)
        t.account.db.execute('UPDATE portfolio_checkpoint SET body=?,hash=? WHERE id=1',(canonical(encoded),digest(encoded)))
        journal=t.account.db.execute('SELECT * FROM portfolio_events').fetchall()
        before=state['journal_hash'];t.account.close()
        t.account=PortfolioAccounting(t.database)
        row=t.account.snapshot()['positions'][life]
        self.assertEqual(row['mark'],{'state':'UNAVAILABLE'})
        self.assertEqual(t.account.snapshot()['journal_hash'],before)
        self.assertEqual(t.account.db.execute('SELECT * FROM portfolio_events').fetchall(),journal)
        self.assertEqual(row['realized_pnl'],2)

    def test_fresh_post_mutation_checkpoint_mark_survives_replay(self):
        t=self.t;life=t.reserve_enter(fee='0');self.mutate(life,'partial')
        t.current_mark('pump',life,'115');t.account.compact();self.restart()
        self.assertEqual(t.account.snapshot()['positions'][life]['mark']['state'],'CURRENT')

    def test_snapshot_and_reader_reject_outside_envelope(self):
        export=self.t.publish();receipt=json.loads(self.t.receipt_path.read_text())
        for bad in ('1'+'0'*40,'0.'+'0'*29+'1'):
            changed=deepcopy(export);changed['balances']['equity']=bad
            with self.assertRaisesRegex(SnapshotTransportError,'snapshot_decimal_contract'):build_snapshot(receipt,changed)
            self.t.export_path.write_text(json.dumps(changed))
            self.assertEqual(self.t.reader_view()['state'],'FAIL_CLOSED')


class IdempotentMarkMutation(unittest.TestCase):
    def test_long_pons_conversion_through_lane_journal_restart_and_reader(self):
        t=lane_fixture.PortfolioLaneIntegrationTests();t.setUp();self.addCleanup(t.tearDown)
        rpc=ReadRPC();rpc.route_output=2500001
        with patch('meme_machine.runtime.usd_valuation.time.time',return_value=NOW):
            basis=NativeValueReader('pons',rpc=rpc)(NOW).amount(123456789012345679,NOW)
        with localcontext() as context:
            context.prec=3
            lane=t.reserve_enter('pons','long-pons',reserved=amount(basis),basis=amount(basis),fee='0')
            export=t.account.publish(epoch_id=t.EPOCH,event_id='long-pons-publish',as_of=t.next_at(),valid_until=t.at(t.clock+100))
            validate_snapshot(build_snapshot(json.loads(t.receipt_path.read_text()),export))
            view=Reader(t.receipt_path,t.export_path,mode='canonical',clock=lambda:__import__('datetime').datetime.fromisoformat(export['as_of']).timestamp()).view()
            self.assertEqual(view['positions'][0]['remaining_basis'],amount(basis))
            self.assertNotEqual(view['state'],'FAIL_CLOSED')
            state=_encode_checkpoint(t.account.snapshot());t.account.close();t.account=PortfolioAccounting(t.database)
            self.assertEqual(_encode_checkpoint(t.account.snapshot()),state)

    def test_duplicate_native_mutation_does_not_reapply_after_restart(self):
        t=lane_fixture.PortfolioLaneIntegrationTests();t.setUp();self.addCleanup(t.tearDown)
        lane=t.reserve_enter('pons','life',fee='0',basis='50')
        args=t.event_args('pons','life','mark')
        lane.mark(state='CURRENT',net_liquidation_value='60',value_evidence=t.evidence('pons','mark',args['at']),**args)
        args=t.event_args('pons','life','harvest')
        kwargs=dict(basis_released='10',gross_proceeds='12',fee='0',value_evidence=t.evidence('pons','harvest',args['at']),**args)
        lane.partial_exit(**kwargs)
        before=_encode_checkpoint(t.account.snapshot());lane.partial_exit(**kwargs)
        self.assertEqual(_encode_checkpoint(t.account.snapshot()),before)
        t.account.close();t.account=PortfolioAccounting(t.database)
        from meme_machine.portfolio_lane_integration import PortfolioLaneProducer
        producer=PortfolioLaneProducer(t.account,epoch_id=t.EPOCH,inception_sha256=t.receipt_hash)
        producer.lane('pons').partial_exit(**kwargs)
        self.assertEqual(_encode_checkpoint(t.account.snapshot()),before)
        self.assertEqual(next(iter(t.account.snapshot()['positions'].values()))['mark'],{'state':'UNAVAILABLE'})
