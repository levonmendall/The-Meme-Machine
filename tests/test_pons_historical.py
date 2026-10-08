"""Complete-input equivalence and failures; no actual seven-day seed claim."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engineering.pons_history.fixtures import Tape, encoded_event, checksum
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.pons_historical import Preparation, PLAN, GRADUATION, LAUNCH, FACTORY, event_id
from meme_machine.lanes.pons.pons_history import PonsHistory
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH, evaluate_entry
from meme_machine.lanes.pons.pons_selective_v4 import collect_v4_activity
from meme_machine.runtime.journal import digest


class HistoricalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, dict(MM_DIRECTIONAL_SLEEVE_DB=self.temp.name+'/sleeve.sqlite',
            MM_DIRECTIONAL_COHORT_ID='historical-offline'), clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tape = Tape()
        provider=patch('meme_machine.lanes.pons.pons_survivor_runtime.configured_rpc',
                       side_effect=lambda *a,**kw:self.tape.provider())
        provider.start();self.addCleanup(provider.stop)
        self.runtime = Runtime(Path(self.temp.name)/'new', 10**18, 'offline', 'https://offline.invalid')
        self.addCleanup(self.runtime.close)
        self.runtime.rpc = self.tape
        self.history = self.runtime.history
        self.prep = self.make()

    def make(self, *, range_blocks=10, support=None, log_limit=1024):
        return Preparation(self.history, self.tape.provider, range_blocks=range_blocks,
            support=support, response_log_limit=log_limit,
            clock=lambda:int(self.tape.header(self.tape.top)['timestamp'],16)+1)

    def boundary(self, prospective=False):
        self.prep.begin(prospective=prospective)
        for _ in range(40):
            if 'first' in self.history.get_meta(PLAN):
                break
            self.prep.boundary_step()
        self.assertIn('first', self.history.get_meta(PLAN))

    def census(self):
        for _ in range(200):
            p = self.history.get_meta(PLAN)
            if self.prep._frontier('population', p['first'], p['anchor'])['block'] == self.tape.top:
                return
            self.prep.discover_step()
        self.fail('census did not converge')

    def authenticate(self):
        for _ in range(100):
            if not self.history.pending_graduations():
                return
            self.prep.authenticate_step()
        self.fail('authentication did not converge')

    def hydration(self):
        for token in self.tape.tokens:
            while self.history.get(token)['block'] < self.tape.top:
                self.prep.history_step(self.runtime, token)

    def complete(self):
        self.boundary()
        self.census()
        self.authenticate()
        self.hydration()
        self.assertTrue(self.prep.readiness()['ready'], self.prep.readiness())

    def support(self, blocks=40):
        return dict(schema='pons-log-range-comparison-v1', chain_id=4663,
            provider_fingerprint=self.tape.provider_fingerprint, equal=True, range_blocks=blocks,
            filter=Preparation.population_filter(), canonical_end_hash=self.tape.header(self.tape.top)['hash'],
            baseline_digest='offline-equal-input-receipt')

    def activity(self, endpoint, **kw):
        return collect_v4_activity(None, **kw, _shared=self.tape.shared_activity(
            kw['start_block'],kw['end_block'],[kw['pool_id']]))

    def vector(self, runtime, token):
        runtime.current = runtime.history.get(token)
        class Quotes:
            def loss(self, n):return 100
        state = dict(block=self.tape.top, block_hash=self.tape.header(self.tape.top)['hash'],
                     at=int(self.tape.header(self.tape.top)['timestamp'],16), acquired=1, price_index=10**18)
        with patch('meme_machine.lanes.pons.pons_survivor_runtime.collect_v4_activity', side_effect=self.activity):
            facts = runtime.reconstruct(state, Quotes())
        facts.pop('evidence_acquired_monotonic')
        return facts

    def test_exact_boundary_census_and_all_candidate_histories(self):
        self.complete()
        self.assertEqual(self.history.get_meta(PLAN)['first'],self.tape.first)
        expected = [e for e in self.tape.logs if e['address'].lower()==FACTORY
                    and e['topics'][0] in (LAUNCH,GRADUATION)]
        self.assertEqual(sorted(event_id(e) for e in expected),sorted(event_id(e) for e in self.prep.population()))
        self.assertEqual(len(self.history.rows()),2)
        self.assertEqual(self.runtime.book.reconcile()['open_positions'],0)
        self.assertTrue(self.prep.resume()['ready'])

    def test_old_and_new_exact_complete_vectors_and_rejections(self):
        self.complete()
        old = Runtime(Path(self.temp.name)/'old',10**18,'offline','https://offline.invalid')
        self.addCleanup(old.close)
        old.rpc = self.tape
        old.now = lambda:int(self.tape.header(self.tape.top)['timestamp'],16)
        target=self.tape.top
        self.tape.top=self.tape.first
        old.discover()
        self.tape.top=target
        for _ in range(20):
            old.discover()
            if old.history.get_meta('discovery_block') == self.tape.top and not old.history.pending_graduations():break
        self.assertEqual([r['id'] for r in old.history.rows()],[r['id'] for r in self.history.rows()])
        for token in self.tape.tokens:
            while old.history.get(token)['block'] < self.tape.top:
                row = old.history.get(token)
                with patch('meme_machine.lanes.pons.pons_survivor_runtime.collect_v4_activity',side_effect=self.activity):
                    old._increment(row,min(self.tape.top,row['block']+40))
            self.assertEqual(old.history.get(token)['graduation'], self.history.get(token)['graduation'])
            a,b = self.vector(old,token),self.vector(self.runtime,token)
            self.assertEqual(a,b)
            self.assertEqual(evaluate_entry(a),evaluate_entry(b))
        self.assertEqual(old.book.reconcile(),self.runtime.book.reconcile())

    def test_wider_bounded_ranges_preserve_native_output(self):
        self.prep = self.make(range_blocks=40,support=self.support())
        self.test_old_and_new_exact_complete_vectors_and_rejections()

    def test_shared_group_reconstruction_and_restart(self):
        self.boundary();self.census();self.authenticate()
        while any(r['block']<self.tape.top for r in self.history.rows()):
            self.prep.history_group_step(self.runtime,self.history.rows())
        self.assertTrue(self.prep.readiness()['ready'],self.prep.readiness())
        self.assertTrue(self.prep.resume()['ready'])
        groups=[r[0] for r in self.history.db.execute("SELECT DISTINCT kind FROM pons_historical_ranges WHERE kind LIKE 'candidates:%'")]
        self.assertEqual(len(groups),1)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM pons_historical_members').fetchone()[0],2)

    def test_older_launch_search_reuses_authenticated_lineage(self):
        token=self.tape.tokens[0]
        b=self.tape.first-35
        self.tape.launch_blocks[token]=b
        launch=next(e for e in self.tape.logs if e['topics'][0]==LAUNCH
                    and e['topics'][1][-40:]==token[2:])
        launch.update(blockNumber=hex(b),blockHash=self.tape.header(b)['hash'])
        self.boundary();self.census();self.tape.request_log=[];self.authenticate()
        self.assertEqual(self.history.get_meta('pons_historical_identity:'+token)['launch'],launch)
        calls=[p for m,p in self.tape.request_log if m=='eth_getCode' and p[0]==self.tape.records[token]['curve']]
        self.assertEqual(len(calls),1)
        self.assertGreater(len([m for m,p in self.tape.request_log if m=='eth_getBlockByNumber']),15)

    def test_runtime_warm_discovery_and_position_precedence(self):
        self.complete()
        self.runtime.now=lambda:int(self.tape.header(self.tape.top)['timestamp'],16)
        row=self.history.get(self.tape.tokens[0]);row.update(position='native-position',state='filled')
        self.history.save(row)
        actions=[]
        self.runtime.historical_preparation=self.make()
        self.tape.request_log=[]
        with patch('meme_machine.runtime.storage.compact_survivor'), \
                patch.object(self.runtime,'_position',side_effect=lambda r,**k:actions.append('position')), \
                patch.object(self.history,'qualification_turn',side_effect=AssertionError('unrestored qualification')):
            status=self.runtime.step(admit=False)
        self.assertEqual(actions,['position'])
        self.assertFalse(self.runtime.historical_preparation.restored)
        self.runtime.discover()
        self.runtime.forward_preparation=None
        self.tape.request_log=[]
        self.runtime.discover()
        self.assertTrue(self.runtime.historical_readiness['ready'])
        self.assertFalse(any(m=='eth_getLogs' for m,p in self.tape.request_log))
        self.tape.top+=1
        for _ in range(5):
            self.runtime.discover()
            if self.runtime.historical_readiness['ready']:break
        self.assertTrue(self.runtime.historical_readiness['ready'])
        logs=[p[0] for m,p in self.tape.request_log if m=='eth_getLogs']
        self.assertTrue(logs)
        self.assertTrue(all(int(q['fromBlock'],16)>=self.tape.top for q in logs))

    def test_existing_worker_driver_finishes_and_restores(self):
        for _ in range(100):
            if self.prep.step(self.runtime)['ready']:break
        else:self.fail('bounded worker did not finish')
        self.prep=self.make()
        self.assertTrue(self.prep.step(self.runtime)['ready'])

    def test_deleted_prefix_range_is_not_accepted_as_complete(self):
        self.complete()
        self.history.db.execute("DELETE FROM pons_historical_ranges WHERE id=(SELECT id FROM pons_historical_ranges WHERE kind='population' ORDER BY first LIMIT 1)")
        self.prep=self.make()
        with self.assertRaisesRegex(BoundaryError,'replay_gap'):self.prep.resume()

    def test_candidate_complete_flag_cannot_replace_missing_coverage(self):
        self.boundary();self.census();self.authenticate()
        for row in self.history.rows():
            row.update(block=self.tape.top,block_hash=self.tape.header(self.tape.top)['hash'],complete=True)
            self.history.save(row)
        self.assertFalse(self.prep.readiness()['ready'])

    def test_expiration_requires_strategy_and_recovery_boundaries(self):
        self.complete()
        self.tape.top+=160
        self.prep.extend(self.tape.header(self.tape.top));self.census()
        for _ in range(10):
            if self.prep.step(self.runtime)['ready']:break
        self.assertTrue(self.prep.readiness()['ready'],self.prep.readiness())
        protected=self.tape.start_at-1
        before=self.history.db.execute('SELECT COUNT(*) FROM pons_historical_ranges').fetchone()[0]
        self.assertEqual(self.prep.maintain(recovery_before=protected)['retired_ranges'],0)
        self.assertEqual(before,self.history.db.execute('SELECT COUNT(*) FROM pons_historical_ranges').fetchone()[0])
        result=self.prep.maintain(recovery_before=int(self.tape.header(self.tape.top)['timestamp'],16))
        self.assertGreater(result['retired_ranges'],0)
        self.assertTrue(self.prep.resume()['ready'])

    def test_unverified_widening_makes_zero_provider_requests(self):
        p = self.make(range_blocks=40)
        before = self.tape.physical
        with self.assertRaisesRegex(BoundaryError,'capability_unverified'):p.begin()
        self.assertEqual(before,self.tape.physical)

    def test_wrong_provider_capability_makes_zero_requests(self):
        support = self.support();support['provider_fingerprint']='different'
        p=self.make(range_blocks=40,support=support)
        with self.assertRaisesRegex(BoundaryError,'capability_unverified'):p.begin()
        self.assertEqual(self.tape.physical,0)

    def test_bounded_capability_comparison(self):
        from engineering.pons_history.capability import compare
        from meme_machine.lanes.pons.pons_historical import order
        self.tape.logs.sort(key=order)
        receipt=compare(self.history,self.tape.provider,self.tape.first)
        self.assertTrue(receipt['equal']);self.assertGreater(receipt['event_count'],0)
        self.assertLessEqual(receipt['logical_rpc_elements'],64)
        self.assertFalse(receipt['provider_certified'])
        self.prep=self.make(range_blocks=40,support=receipt)
        self.complete()

    def test_capability_detects_silent_large_range_truncation(self):
        from engineering.pons_history.capability import compare
        from meme_machine.lanes.pons.pons_historical import order
        self.tape.logs.sort(key=order)
        self.tape.silent_truncation=True
        with self.assertRaisesRegex(BoundaryError,'population_disagreement'):
            compare(self.history,self.tape.provider,self.tape.first)

    def test_capability_empty_range_is_insufficient(self):
        from engineering.pons_history.capability import compare
        self.tape.logs=[]
        with self.assertRaisesRegex(BoundaryError,'nonempty_sample_required'):
            compare(self.history,self.tape.provider,self.tape.first)

    def test_capability_budget_stops_before_dispatch(self):
        from engineering.pons_history.capability import compare
        tick=[0]
        def clock():tick[0]+=50;return tick[0]
        with self.assertRaisesRegex(BoundaryError,'budget_exhausted'):
            compare(self.history,self.tape.provider,self.tape.first,clock=clock)
        self.assertEqual(self.tape.physical,0)

    def test_empty_ranges_require_canonical_boundaries(self):
        self.tape.logs=[]
        self.boundary();self.census()
        self.assertTrue(self.prep.readiness()['ready'])
        for body,hash_ in self.history.db.execute('SELECT body,hash FROM pons_historical_ranges'):
            r=self.history._verified((body,hash_))
            self.assertTrue(r['previous']['hash']);self.assertTrue(r['end']['hash'])

    def test_empty_response_missing_boundary_is_incomplete(self):
        self.tape.logs=[];self.boundary()
        self.tape.missing_block=self.tape.first+39
        with self.assertRaisesRegex(BoundaryError,'header_identity'):self.prep.discover_step()
        self.assertFalse(self.prep.readiness()['ready'])
        self.assertIsNone(self.history.get_meta('pons_historical_frontier:population'))

    def test_range_rejection_subdivides_without_losing_census(self):
        self.prep=self.make(range_blocks=40,support=self.support())
        self.tape.max_range=10
        self.boundary();self.census();self.authenticate();self.hydration()
        self.assertTrue(self.prep.readiness()['ready'],self.prep.readiness())
        self.assertGreater(self.tape.failures['provider_log_block_range_limit'],0)

    def test_provider_page_and_pagination_failure_do_not_advance(self):
        self.boundary();self.tape.paginated=True
        with self.assertRaisesRegex(BoundaryError,'pagination'):self.prep.discover_step()
        self.assertEqual(self.history.pending_graduations(),0)
        self.assertFalse(self.prep.readiness()['ready'])

    def test_single_block_saturation_is_incomplete_not_rejection(self):
        self.boundary();self.tape.saturated=True
        for _ in range(20):
            try:self.prep.discover_step()
            except BoundaryError as exc:
                self.assertEqual(str(exc),'historical_response_saturation');break
        else:self.fail('saturated block must stop')
        self.assertFalse(self.prep.readiness()['ready'])
        self.assertEqual(self.history.rows(),[])

    def test_duplicate_events_and_repeated_turn_insert_once(self):
        self.tape.duplicates=True
        self.boundary();self.census()
        before=self.history.db.execute('SELECT COUNT(*) FROM pons_historical_events').fetchone()[0]
        calls=self.tape.physical
        self.assertFalse(self.prep.discover_step())
        self.assertEqual(calls,self.tape.physical)
        self.assertEqual(before,self.history.db.execute('SELECT COUNT(*) FROM pons_historical_events').fetchone()[0])
        self.assertEqual(self.history.pending_graduations(),2)

    def test_duplicate_identity_conflict_fails_closed(self):
        self.boundary()
        e=deepcopy(next(e for e in self.tape.logs if e['topics'][0]==GRADUATION));e['data']='0x'+'0'*192
        self.tape.logs.append(e)
        with self.assertRaisesRegex(BoundaryError,'duplicate_event_conflict'):self.prep.discover_step()
        self.assertIsNone(self.history.get_meta('pons_historical_frontier:population'))

    def test_interrupted_atomic_write_restart_keeps_original_checkpoint(self):
        self.boundary()
        original=self.prep._put_events
        def interrupt(*args):
            original(*args);raise KeyboardInterrupt()
        with patch.object(self.prep,'_put_events',side_effect=interrupt),self.assertRaises(KeyboardInterrupt):
            self.prep.discover_step()
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM pons_historical_events').fetchone()[0],0)
        self.assertIsNone(self.history.get_meta('discovery_block'))
        self.prep=self.make();self.prep.resume();self.census()
        self.assertEqual(self.history.pending_graduations(),2)

    def test_restart_during_catchup_does_not_refetch_proven_ranges(self):
        self.boundary();self.prep.discover_step()
        through=self.history.get_meta('discovery_block')
        self.prep=self.make()
        with self.assertRaisesRegex(BoundaryError,'restore_verification_required'):self.prep.discover_step()
        self.prep.resume();self.tape.request_log=[];self.census()
        ranges=[p[0] for m,p in self.tape.request_log if m=='eth_getLogs']
        self.assertTrue(all(int(q['fromBlock'],16)>through for q in ranges))

    def test_transient_provider_error_leaves_retryable_gap_and_deadline(self):
        self.boundary();self.tape.error='provider_transport_failure'
        with self.assertRaisesRegex(BoundaryError,'transport_failure'):self.prep.discover_step()
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM pons_historical_gaps').fetchone()[0],1)
        self.census();self.authenticate()
        token=self.tape.tokens[0];row=self.history.get(token);row['original_deadline']=123;row['generation']=7;self.history.save(row)
        self.prep=self.make();self.prep.resume();self.hydration()
        self.assertEqual(self.history.get(token)['original_deadline'],123)
        self.assertEqual(self.history.get(token)['generation'],7)

    def test_population_reorg_rewinds_affected_tail_not_whole_domain(self):
        self.boundary();self.census()
        first=self.tape.first+100
        self.tape.reorg(first)
        p=self.make();p.resume()
        through=self.history.get_meta('discovery_block')
        self.assertGreater(through,self.tape.first-1)
        self.assertLess(through,first)
        self.prep=p;self.tape.request_log=[];self.census()
        self.assertTrue(all(int(params[0]['fromBlock'],16)>through for method,params in self.tape.request_log if method=='eth_getLogs'))
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM pons_historical_gaps').fetchone()[0],0)

    def test_candidate_reorg_preserves_controller_and_replays_native_history(self):
        self.complete()
        token=self.tape.tokens[0];row=self.history.get(token)
        row.update(original_deadline=123,generation=7,position='qualified-unfunded',state='qualified')
        self.history.save(row)
        self.tape.reorg(self.tape.grad+100)
        self.prep=self.make();self.prep.resume()
        self.assertFalse(self.prep.readiness()['ready'])
        self.assertEqual(self.history.get(token)['position'],'qualified-unfunded')
        self.assertTrue(self.prep.recover_candidate(self.runtime,token))
        while self.history.get(token)['block']<self.tape.top:self.prep.history_step(self.runtime,token)
        row=self.history.get(token)
        self.assertNotIn('recovery',row);self.assertTrue(row['complete'])
        self.assertEqual(row['original_deadline'],123);self.assertEqual(row['generation'],7)

    def test_database_corruption_cannot_certify_restore(self):
        self.complete()
        self.history.db.execute("UPDATE pons_historical_ranges SET hash='wrong'")
        self.prep=self.make()
        with self.assertRaisesRegex(ValueError,'corruption'):self.prep.resume()
        self.assertFalse(self.prep.restored)

    def test_missing_journal_event_is_detected_by_range_replay(self):
        self.boundary();self.census()
        self.history.db.execute('DELETE FROM pons_historical_events WHERE id=(SELECT id FROM pons_historical_events LIMIT 1)')
        self.prep=self.make()
        with self.assertRaisesRegex(BoundaryError,'event_replay'):self.prep.resume()

    def test_population_watermark_alone_cannot_release_survivor(self):
        self.boundary();self.census()
        self.assertFalse(self.prep.readiness()['ready'])
        self.authenticate()
        self.assertFalse(self.prep.readiness()['ready'])
        self.assertEqual(self.prep.readiness()['current_readiness'],
                         'owned by existing Current prerequisites and startup guard')

    def test_prospective_enrollment_keeps_seven_day_requirement(self):
        self.boundary(prospective=True)
        self.assertFalse(self.prep.readiness()['ready'])
        enrollment=self.history.get_meta(PLAN)['enrollment_at']
        self.tape.top+=168
        self.prep.extend(self.tape.header(self.tape.top));self.census()
        self.assertEqual(self.history.get_meta(PLAN)['enrollment_at'],enrollment)
        self.assertFalse(self.prep.readiness()['seven_day_domain_mature'])
        self.assertFalse(self.prep.readiness()['ready'])
        self.tape.top+=1
        self.prep.extend(self.tape.header(self.tape.top));self.census()
        self.assertTrue(self.prep.readiness()['seven_day_domain_mature'])
        self.assertTrue(self.prep.readiness()['ready'])

    def test_usage_counts_physical_batches_separately_from_elements(self):
        self.boundary();self.census()
        u=self.history.get_meta('pons_historical_usage')
        self.assertEqual(u['logical_rpc_elements'],self.tape.logical)
        self.assertEqual(u['physical_http_attempts'],self.tape.physical)
        self.assertGreater(u['logical_rpc_elements'],u['physical_http_attempts'])
        self.assertIsNone(u['actual_billed_cu'])

    def test_receipt_pins_reuse_native_cache_domain_and_restore_session(self):
        seen=[];original=self.tape.batch
        def batch(calls,**kw):
            for method,params in calls:
                if method=='eth_getTransactionReceipt':
                    expected=self.tape.receipt_value(params[0])['blockHash']
                    self.assertEqual(self.tape.evidence_receipts.get(params[0]),expected)
                    seen.append(params[0])
            return original(calls,**kw)
        with patch.object(self.tape,'batch',side_effect=batch):self.boundary();self.census();self.authenticate()
        self.assertTrue(seen)
        self.assertFalse(hasattr(self.tape,'evidence_receipts'))

    def test_native_local_receipt_cache_hits_are_counted_with_shared_telemetry(self):
        from meme_machine.lanes.pons.provider import Rpc
        from meme_machine.lanes.pons.pons_historical import _NativeReads
        rpc=Rpc('https://offline.invalid',limit=200,per_scope=200,retries=0,transport=self.tape._read)
        rpc.canonical_authority=rpc.chain_verified=True;rpc.provider_fingerprint='offline-cache'
        telemetry=rpc.telemetry
        rpc.telemetry=lambda:dict(telemetry(),immutable_reuse={})
        p=Preparation(self.history,lambda:rpc)
        event=next(e for e in self.tape.logs if e['topics'][0]==GRADUATION)
        reads=_NativeReads(p)
        for _ in range(2):reads.receipt(event['transactionHash'],event['blockHash'],scope='offline')
        u=self.history.get_meta('pons_historical_usage')
        self.assertEqual(u['logical_rpc_elements'],2)
        self.assertEqual(u['cache_hits'],1)
        self.assertEqual(u['physical_http_attempts'],0)

    def test_historical_priority_yields_to_current_and_position_work(self):
        from meme_machine.lanes.pons.provider_admission import priority,position_work,decision_work
        observed=[]
        original=self.tape.batch
        def batch(*args,**kwargs):observed.append(priority(kwargs['scope']));return original(*args,**kwargs)
        with patch.object(self.tape,'batch',side_effect=batch):self.boundary();self.census()
        self.assertTrue(observed);self.assertEqual(set(observed),{50})
        self.assertEqual(decision_work(1)(lambda:priority('pons_current'))(),5)
        self.assertEqual(position_work(lambda:priority('pons_monitor'))(),0)

    def test_runtime_increment_limit_and_provider_blocker_preserved(self):
        self.complete()
        row=self.history.get(self.tape.tokens[0])
        with self.assertRaisesRegex(BoundaryError,'incremental_slice_required'):
            self.runtime._increment(row,row['block']+41)
        self.assertIn('combined_position_and_candidate_provider_latency_not_certified',
            (Path(__file__).parents[1]/'meme_machine/solana_selective_source.py').read_text())
