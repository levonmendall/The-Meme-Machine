"""Crash cuts in the actual current-Pons production lifecycle, with virtual evidence."""
import json,tempfile,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock,patch
from meme_machine.lanes.pons import BoundaryError, pons_selective_paper as runtime
from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,JOURNAL_CATEGORY
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH,EXIT_POLICY
from meme_machine.lanes.pons.evidence import Store
from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
from tests.lanes.pons import test_pons_partial_accounting as accounting_fixture
from tests.lanes.pons import test_pons_position_provider_recovery as recovery_fixture
from meme_machine.runtime.execution_capacity import resize

class ProcessCut(BaseException):pass

class CurrentRecoveryTests(unittest.TestCase):
    def case(self,folder,cut,*,cohort=False,workflow=None,bounded=False,asynchronous=False):
        import time
        real_sleep=time.sleep
        clock=[100];fixture=accounting_fixture.PartialAccountingTests()
        state=MagicMock();state.buy_with_snipe.return_value=dict(refund=0,ready_to_graduate=False,tokens_out=1000)
        evaluation=dict(vector=dict(current_threshold_pass=True,policy_hash=POLICY_HASH,
         proposed_size={'amount_quote':100},evidence_available_at=100,
         trajectory={'graduation_eta_seconds':100},demand={'largest_buyer_flow_bps':100}),
         candidate=dict(receipt={'gasUsed':hex(21000)},curve='m',state=state,report={},token='token',record={},auth={}),
         token='token',curve='m',source_transaction='source',market_events=[])
        rpc=MagicMock();rpc.used=0;rpc.telemetry.return_value={}
        def sleep(n):
            clock[0]+=max(0,n)
            if clock[0]>170:clock[0]=max(clock[0],100+EXIT_POLICY['max_total_hold_seconds']+10)
            if workflow is not None:real_sleep(.001)
        def quote(_rpc,_candidate,side,amount,*a,**kw):
         return fixture.quote(int(clock[0]),side,amount,1000 if side=='buy' else amount*148//1000),dict(block=int(clock[0]),block_hash='h'+str(int(clock[0])),event_at=int(clock[0]))
        def wait_quote(*a,**kw):q,m=quote(*a,**kw);return q,m,None
        patches={'paper_rpc':lambda *a:rpc,'_gas_quote':lambda *a:(2,1),
         '_entry_capacity':lambda meta,amount,gas:resize(amount,1,lambda n:100,ordinary_limit=600),
         '_wait_curve_quote':wait_quote,'_curve_quote':quote,
         '_refresh_entry_persistence_signal':recovery_fixture.PositionRecoveryTests.persistent_entry_signal,
         '_refresh_curve_signal':recovery_fixture.PositionRecoveryTests.persistent_entry_signal,
         '_validate_final_entry':lambda *a:None,'_confirm_entry_delta':lambda *a:(a[5],[],{}),
         '_fresh_fill_full_exit_check':lambda *a:dict(executable=True),
         '_latest_header':lambda *a:dict(number=hex(int(clock[0]))),
         '_graduation_transition':lambda *a:None,'time.time':lambda:clock[0],'time.sleep':sleep}
        if cut in ('transition','postgrad_mark','runner_mark','v4_pending_timeout'):
            from dataclasses import replace
            from meme_machine.lanes.pons.protocols import PoolKey
            key=PoolKey('0x'+'1'*40,'0x'+'2'*40,3000,60,'0x'+'3'*40)
            transition=dict(previous_market='m',market=key.pool_id(),proof_hash='fixture-graduation')
            def graduated(*args):
                return ((transition,key,dict(number=hex(134),timestamp=hex(134)),{})
                    if clock[0]>=134 else None)
            def v4_quote(_rpc,_key,market,amount,*args,**kwargs):
                q,m=quote(_rpc,{},'sell',amount)
                return replace(q,market=market),m,None
            if cut=='v4_pending_timeout':
                original_quote=quote
                def quote(*args,**kwargs):
                    q,m=original_quote(*args,**kwargs)
                    if args[2]=='sell' and clock[0]<134:q=replace(q,amount_out=args[3]*108//1000)
                    return q,m
                def growing_signal(*args):
                    trajectory,demand,sessions=recovery_fixture.PositionRecoveryTests.persistent_entry_signal()
                    trajectory['recent_progress_bps']=600
                    return trajectory,demand,sessions
                patches['_refresh_curve_signal']=growing_signal
                patches['_curve_quote']=quote
            patches.update(_graduation_transition=graduated,_v4_quote=v4_quote,
                evidence_rpc=lambda *a:rpc,_header_search=lambda *a:dict(number=hex(int(clock[0])-10)),
                collect_v4_activity=lambda *a,**kw:dict(provider_sessions=[],new_independent_buyers=4,
                    buy_quote=3000,sell_quote=1000,net_quote=2000,preholder_sell_quote=200,
                    largest_buyer_flow_bps=80,buyer_groups=['a','b','c','d']))
        db=Path(folder)/'trial-000.sqlite';capital=Path(folder)/'pons-selective-cohort-capital.sqlite'
        original=SelectivePaper.advance
        def advance(paper,*args,**kwargs):
            action=kwargs['action']
            if cut=='before_entry' and action=='entry':raise ProcessCut()
            p=original(paper,*args,**kwargs)
            if (cut==action or (cut=='partial' and action=='exit' and p['status']=='open')
                    or (cut=='final' and action=='exit' and p['status']=='settled')
                    or (cut=='v4_pending_timeout' and action=='exit_intent' and p['controller_state']['v4_key'])
                    or (cut=='postgrad_mark' and action=='mark' and p['controller_state']['post_grad_checked'])
                    or (cut=='runner_mark' and action=='mark' and p['controller_state']['post_grad_checked']
                        and p['version']>=9)):
                raise ProcessCut()
            return p
        with ExitStack() as stack:
            from meme_machine.lanes.pons.pons_current_workers import LifecyclePool
            stack.enter_context(patch('meme_machine.lanes.pons.pons_current_workers.LifecyclePool',
                side_effect=lambda **kw:LifecyclePool(**kw,clock=lambda:clock[0],wait_for_due=sleep)))
            if cut=='before_reserve':stack.enter_context(patch.object(SelectivePaper,'reserve',side_effect=ProcessCut()))
            for name,value in patches.items():stack.enter_context(patch('meme_machine.lanes.pons.pons_selective_paper.'+name,side_effect=value))
            with patch.object(SelectivePaper,'advance',advance):
                with self.assertRaises(ProcessCut):runtime.run_lifecycle('unused',evaluation,db_path=db,capital_path=capital)
            if cut=='before_reserve':
                stack.pop_all().close()
                from meme_machine.runtime.directional_sleeve import open_sleeve
                with patch.object(runtime,'paper_rpc',side_effect=AssertionError('unfilled recovery needs no provider')):
                    result=runtime.resume_lifecycle('unused',db_path=db,capital_path=capital)
                    again=runtime.resume_lifecycle('unused',db_path=db,capital_path=capital)
                self.assertEqual(result['status'],again['status'])
                self.assertEqual(result['status'],'entry_failed')
                self.assertEqual(result['final_position']['entry_tokens'],0)
                rec=CohortCapital(capital,runtime.STRATEGY_CAPITAL_QUOTE).reconcile()
                self.assertEqual((rec['unsettled'],rec['reserved'],rec['realized']),(0,0,0))
                self.assertTrue(rec['cash_basis_conservation'])
                with StoreForTest(db) as store:
                    events=[json.loads(r[0]) for r in store.db.execute('SELECT body FROM records WHERE category=?',(JOURNAL_CATEGORY,))]
                self.assertEqual([e['action'] for e in events],['reserve','cancel'])
                sleeve=open_sleeve('pons',runtime.STRATEGY_CAPITAL_QUOTE)
                if sleeve:
                    try:self.assertEqual(sleeve.reconcile()['reserved'],0)
                    finally:sleeve.close()
                return result,events
            with StoreForTest(db) as store:
                before=json.loads(store.db.execute('SELECT body FROM pons_selective_paper').fetchone()[0])
            if cut!='before_entry':
                self.assertEqual(before['controller_state']['opened_at'],102)
                self.assertEqual(before['controller_state']['policy_hash'],POLICY_HASH)
            if cut=='partial':
                import hashlib
                from meme_machine.runtime.terminal_reconciliation import pons_current_handoff
                before_bytes=hashlib.sha256(db.read_bytes()).hexdigest()
                handoff=pons_current_handoff(folder,capital)
                self.assertEqual(handoff['positions'][0]['id'],before['id'])
                self.assertFalse(handoff['entry_authority'])
                self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(),before_bytes)
                self.assertEqual(before['tokens'],750)
                self.assertTrue(before['controller_state']['partial_taken'])
                self.assertGreater(before['controller_state']['high_water'],1800)
                self.assertIsNone(before['controller_state']['pending_action'])
            if cut=='mark':self.assertEqual(before['controller_state']['pending_action']['exit_tokens'],250)
            if cut=='exit_intent':self.assertEqual(before['pending_exit_tokens'],250)
            if cut=='entry':clock[0]+=5
            if cut=='v4_pending_timeout':clock[0]=100+EXIT_POLICY['max_total_hold_seconds']+10
            if cut in ('transition','postgrad_mark','runner_mark'):
                self.assertEqual(before['controller_state']['graduation_at'],134)
                self.assertTrue(before['controller_state']['partial_taken'])
                self.assertEqual(before['market'],key.pool_id())
                if cut!='transition':
                    self.assertTrue(before['controller_state']['post_grad_checked'])
                    self.assertEqual(before['controller_state']['seen_v4_buyers']['count'],4)
            # Resume without advancing past the partial: duplicate harvesting would
            # show up as an extra exit. The native policy eventually reaches max hold.
            if bounded:
                with patch.object(runtime.time,'monotonic',side_effect=lambda:clock[0]):
                    sliced=runtime.resume_lifecycle('unused',db_path=db,capital_path=capital,slice_seconds=1)
                self.assertEqual(sliced['status'],'handoff_required')
                self.assertEqual(sliced['final_position']['tokens'],750)
                self.assertEqual(sliced['final_position']['controller_state']['opened_at'],102)
                self.assertTrue(sliced['final_position']['controller_state']['partial_taken'])
                self.assertEqual(sliced['cohort_reconciliation']['unsettled'],1)
            if cohort:
                from meme_machine.lanes.pons.pons_selective_recovery import recover_existing_lifecycles
                qualifier=dict(index=0,token='token',curve='m',source_transaction='source',vector=evaluation['vector'])
                receipts=[]
                prior=dict(index=0,lifecycle_id=before['id'],curve='m',status='boundary')
                if asynchronous:
                    import threading
                    from concurrent.futures import ThreadPoolExecutor
                    from meme_machine.lanes.pons import pons_selective_recovery as recovery
                    entered=threading.Event();release=threading.Event()
                    original=recovery.resume_lifecycle
                    def resume(*args,**kwargs):
                        entered.set()
                        assert release.wait(5), 'cohort discovery caller blocked during startup'
                        return original(*args,**kwargs)
                    with ThreadPoolExecutor(max_workers=8) as pool,patch.object(recovery,'resume_lifecycle',side_effect=resume):
                        pending=recovery.submit_existing_lifecycles('unused',folder,[qualifier],[prior],pool=pool)
                        self.assertTrue(entered.wait(5));self.assertEqual(len(pending),1)
                        self.assertEqual(pending[0][:2],(0,'m'))
                        self.assertFalse(pending[0][2].done())
                        self.assertEqual(CohortCapital(capital,runtime.STRATEGY_CAPITAL_QUOTE).reconcile()['unsettled'],1)
                        # The same bounded pool still accepts other independent work.
                        self.assertEqual(pool.submit(lambda:'discovery_progress').result(timeout=2),'discovery_progress')
                        release.set();rows=[pending[0][2].result(timeout=10)];receipts.extend(rows)
                else:
                    rows=recover_existing_lifecycles('unused',folder,[qualifier],[prior],on_recovered=receipts.append)
                self.assertEqual(len(rows),1);self.assertEqual(len(receipts),1)
                result=rows[0]
                with patch.object(runtime,'paper_rpc',side_effect=AssertionError('completed recovery must be idempotent')):
                    self.assertEqual(recover_existing_lifecycles('unused',folder,[qualifier],rows,
                        on_recovered=receipts.append),rows)
                self.assertEqual(len(receipts),1)
            else:result=runtime.resume_lifecycle('unused',db_path=db,capital_path=capital)
            self.assertEqual(result['status'],'entry_failed' if cut=='before_entry' else 'settled',result)
            self.assertEqual(result['final_position']['status'],'settled',result.get('status'))
            with StoreForTest(db) as store:
                events=[json.loads(r[0]) for r in store.db.execute('SELECT body FROM records WHERE category=?',(JOURNAL_CATEGORY,))]
                count=len(events)
                self.assertEqual(store.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            # A repeated recovery after final exit/settlement cannot realize again.
            with patch.object(runtime,'paper_rpc',side_effect=AssertionError('settled recovery needs no provider')):
                again=runtime.resume_lifecycle('unused',db_path=db,capital_path=capital)
            self.assertEqual(again['status'],result['status'],again.get('boundary'))
            with StoreForTest(db) as store:
                self.assertEqual(store.db.execute('SELECT count(*) FROM records WHERE category=?',(JOURNAL_CATEGORY,)).fetchone()[0],count)
            self.assertEqual(sum(e['action']=='entry' for e in events),0 if cut=='before_entry' else 1)
            self.assertEqual(sum(e['action']=='exit' for e in events),0 if cut=='before_entry' else 2)
            self.assertEqual(sum(e['action']=='exit_intent' for e in events),0 if cut=='before_entry' else 2)
            book=CohortCapital(capital,runtime.STRATEGY_CAPITAL_QUOTE).reconcile()
            self.assertEqual(book['unsettled'],0);self.assertEqual(book['reserved'],0)
            self.assertTrue(book['cash_basis_conservation'])
            if cut!='before_entry':
                self.assertEqual(result['final_position']['tokens'],0)
                self.assertEqual(result['final_position']['controller_state']['opened_at'],102)
            return before,events

    def test_crash_after_cohort_before_native_reserve_releases_exact_intent(self):
        import os
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,dict(
                MM_DIRECTIONAL_COMPOSITE_REQUIRED='1',MM_DIRECTIONAL_COHORT_ID='offline-recovery',
                MM_DIRECTIONAL_SLEEVE_DB=str(Path(td)/'sleeve.sqlite'))):
            self.case(td,'before_reserve')

    def test_crash_matrix_no_duplicate_entry_partial_exit_or_settlement(self):
        for cut in ('before_entry','entry','mark','exit_intent','partial','final','transition','postgrad_mark','runner_mark'):
            with self.subTest(cut=cut),tempfile.TemporaryDirectory() as td:self.case(td,cut)

    def test_v4_pending_partial_at_max_hold_does_not_claim_full_settlement(self):
        with tempfile.TemporaryDirectory() as td:self.case(td,'v4_pending_timeout')

    def test_bounded_position_slice_preserves_runner_for_next_window(self):
        with tempfile.TemporaryDirectory() as td:self.case(td,'partial',bounded=True)

    def test_cohort_startup_recovers_actual_native_partial_without_new_entry(self):
        with tempfile.TemporaryDirectory() as td:self.case(td,'partial',cohort=True)

    def test_recovered_native_partial_uses_existing_pool_without_blocking_discovery(self):
        with tempfile.TemporaryDirectory() as td:self.case(td,'partial',cohort=True,asynchronous=True)

    def test_recovery_receipts_reject_identity_changes_and_duplicate_counting(self):
        from meme_machine.runtime.robinhood.pons import coalesce_lifecycle_rows
        prior=dict(index=0,curve='m',lifecycle_id='x',status='boundary')
        final=dict(index=0,curve='m',lifecycle_id='x',status='settled',recovery_replaces_index=0,
            entry_authority=False,final_position=dict(id='x',status='settled',tokens=0))
        self.assertEqual(coalesce_lifecycle_rows([prior,final,final]),[final])
        for change in (dict(curve='other'),dict(lifecycle_id='other'),dict(entry_authority=True),
                       dict(recovery_replaces_index=1)):
            with self.assertRaisesRegex(BoundaryError,'recovery_lifecycle_identity'):
                coalesce_lifecycle_rows([prior,dict(final,**change)])

    def test_concurrent_controller_cannot_enter_or_resume(self):
        from meme_machine.lanes.pons.pons_selective_recovery import exclusive_lifecycle
        @exclusive_lifecycle
        def owner(*,db_path):
            with self.assertRaisesRegex(BoundaryError,'controller_already_running'):
                runtime.resume_lifecycle('unused',db_path=db_path)
            with self.assertRaisesRegex(BoundaryError,'controller_already_running'):
                runtime.run_lifecycle('unused',{},db_path=db_path)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'trial-000.sqlite'
            owner(db_path=path)
            owner(db_path=path)  # ownership releases after the earlier call

    def test_normalized_group_corruption_fails_before_provider_access(self):
        from meme_machine.lanes.pons.pons_selective_recovery import GROUPS
        with tempfile.TemporaryDirectory() as td:
            self.case(td,'partial')
            with StoreForTest(Path(td)/'trial-000.sqlite') as store:
                identity=json.loads(store.db.execute('SELECT body FROM pons_selective_paper').fetchone()[0])['id']
                store.db.execute(f'INSERT INTO {GROUPS} VALUES(?,?,?)',(identity,'seen_v4_buyers','forged'))
            with patch.object(runtime,'paper_rpc',side_effect=AssertionError('provider must not be called')):
                with self.assertRaisesRegex(BoundaryError,'controller_group_replay'):
                    runtime.resume_lifecycle('unused',db_path=Path(td)/'trial-000.sqlite')

    def test_controller_groups_and_native_journal_rollback_together(self):
        import sqlite3
        from meme_machine.lanes.pons.pons_selective_recovery import LifecycleState,GROUPS
        f=accounting_fixture.PartialAccountingTests()
        with tempfile.TemporaryDirectory() as td,StoreForTest(Path(td)/'trial-000.sqlite') as store:
            paper=SelectivePaper(store,runtime.STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=POLICY_HASH)
            paper.reserve('x',market='m',amount=100,gas_budget=20,now=10,features=f.features(10))
            evaluation=dict(token='token',curve='m',source_transaction='source',
                candidate=dict(curve='m'),market_events=[dict(group='prior')],
                vector=dict(current_threshold_pass=True,policy_hash=POLICY_HASH,
                    trajectory=dict(graduation_eta_seconds=100),demand=dict(largest_buyer_flow_bps=100)))
            state=LifecycleState.create(store,'x',evaluation,1000,21000,opened_at=11,last_block=11)
            paper.controller_context=state.checkpoint
            before=paper.advance('x',now=11,action='entry',quote=f.quote(11,'buy',100,1000))
            state.seen_v4_buyers.add('new');state.high_water=2000
            store.db.execute(f"""CREATE TRIGGER interrupt_checkpoint BEFORE INSERT ON records
                WHEN NEW.category='{JOURNAL_CATEGORY}'
                BEGIN SELECT RAISE(ABORT,'checkpoint_cut'); END""")
            with self.assertRaisesRegex(sqlite3.IntegrityError,'checkpoint_cut'):
                paper.advance('x',now=12,action='mark',quote=f.quote(12,'sell',1000,125))
            self.assertEqual(paper._get('x'),before)
            restored=LifecycleState.restore(paper,'x')
            self.assertEqual(restored.seen_v4_buyers,set())
            self.assertEqual(restored.preholders,{'prior'})
            self.assertEqual(restored.high_water,-10**9)
            store.db.execute('DROP TRIGGER interrupt_checkpoint')
            paper.advance('x',now=12,action='mark',quote=f.quote(12,'sell',1000,125))
            restored=LifecycleState.restore(paper,'x')
            self.assertEqual(restored.seen_v4_buyers,{'new'})
            self.assertEqual(restored.high_water,2000)

    def test_unexecuted_quote_cannot_be_reported_as_a_completed_exit(self):
        from dataclasses import replace
        f=accounting_fixture.PartialAccountingTests()
        for venue in ('curve','v4'):
            with self.subTest(venue=venue),StoreForTest(':memory:') as store:
                paper=SelectivePaper(store,runtime.STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=POLICY_HASH)
                paper.reserve('x',market='m',amount=100,gas_budget=20,now=10,features=f.features(10))
                paper.advance('x',now=11,action='entry',quote=f.quote(11,'buy',100,1000))
                paper.advance('x',now=12,action='exit_intent',exit_tokens=1000)
                bad=replace(f.quote(14,'sell',1000,110),market='wrong-market')
                with patch.object(runtime,'_wait_curve_quote',return_value=(bad,{},None)),\
                     patch.object(runtime,'_v4_quote',return_value=(bad,{},None)),\
                     patch.object(runtime.time,'time',return_value=14),patch.object(runtime.time,'sleep'):
                    with self.assertRaisesRegex(BoundaryError,'quote_identity_mismatch'):
                        if venue=='curve':
                            runtime._delayed_exit('unused',paper=paper,identity='x',rpc=None,candidate={},
                                gas_units=1,store=store,transition=None,v4_key=None,label='test',exit_tokens=1000)
                        else:runtime._complete_pending_v4_exit(paper=paper,identity='x',rpc=None,
                            v4_key=None,gas_units=1,store=store,label='test')
                position=paper._get('x')
                self.assertEqual(position['status'],'exit_pending')
                self.assertEqual(position['tokens'],1000)
                self.assertEqual(position['realized_proceeds'],0)

class StoreForTest(Store):
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
