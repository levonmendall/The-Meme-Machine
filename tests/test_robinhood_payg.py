"""Synthetic RPC regressions. No account capability or market acceptance claim."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.log_windows import LogWindows, filter_profile, load_capability
from meme_machine.lanes.pons.pons_history import PonsHistory
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
from meme_machine.runtime.robinhood.provider_authority import fingerprint
from meme_machine.runtime.journal import digest

ENDPOINT='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_PAYG_FIXTURE'
QUERY=dict(address='0x'+'11'*20,topics=['0x'+'22'*32,['0x'+'33'*32]])


def event(block, index=0):
    return dict(address=QUERY['address'],topics=[QUERY['topics'][0],QUERY['topics'][1][0]],
        blockNumber=hex(block),blockHash='0x'+f'{block:064x}',transactionIndex=hex(index),
        transactionHash='0x'+f'{block*10000+index:064x}',logIndex=hex(index),data='0x',removed=False)


def capability(query=QUERY, *, endpoint=ENDPOINT, blocks=40):
    static,counts=filter_profile(query)
    return dict(schema='pons-log-window-capability-v1',provider_fingerprint=fingerprint(endpoint),
        chain_id=4663,entitlement_status='VERIFIED',app_id='synthetic-app',team_id='synthetic-team',
        equal=True,event_count=1,canonical_end_hash='0x'+'44'*32,baseline_digest=digest([event(1)]),
        filter=static,indexed_filter_counts=counts,range_blocks=blocks)


class WindowsCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.file=self.root/'capability.json'
        self.history=PonsHistory(self.root/'history.sqlite',policy=POLICY_HASH)
        self.addCleanup(self.history.close)
        self.calls=[]

    def write(self, row=None):
        self.file.write_text(json.dumps(dict(comparisons=[row or capability()])))

    def planner(self, *, query=QUERY, endpoint=ENDPOINT):
        return LogWindows(endpoint,query,state=self.history,capability_path=self.file)

    def provider(self, calls):
        self.calls.extend(deepcopy(calls))
        return [[event(n) for n in range(int(p[0]['fromBlock'],16),int(p[0]['toBlock'],16)+1)]
                for _,p in calls]

    def test_unverified_endpoint_stays_at_ten_blocks(self):
        rows=self.planner().read(1,40,self.provider)
        self.assertEqual(rows,[event(n) for n in range(1,41)])
        self.assertEqual(len(self.calls),4)
        self.assertTrue(all(int(p[0]['toBlock'],16)-int(p[0]['fromBlock'],16)<10 for _,p in self.calls))

    def test_verified_filter_reduces_log_elements_without_changing_the_tape(self):
        self.write();planner=self.planner()
        self.assertEqual(planner.read(1,40,self.provider),[event(n) for n in range(1,41)])
        self.assertEqual(len(self.calls),1)
        self.assertEqual(planner.turn_blocks(),160)

    def test_one_wide_success_never_authorizes_larger_windows(self):
        self.write();planner=self.planner();planner.read(1,160,self.provider)
        self.assertTrue(all(int(p[0]['toBlock'],16)-int(p[0]['fromBlock'],16)<40 for _,p in self.calls))
        self.assertLessEqual(planner.width,40)

    def test_entitlement_empty_sample_wrong_chain_and_incomplete_comparison_fall_back(self):
        for changes in (dict(entitlement_status='UNVERIFIED'),dict(equal=False),dict(event_count=0),
                dict(chain_id=1),dict(team_id=''),dict(baseline_digest=None),dict(range_blocks=100000)):
            with self.subTest(changes=changes):
                self.write(dict(capability(),**changes))
                self.assertEqual(self.planner().ceiling,10)

    def test_credential_rotation_invalidates_capability_and_density_domain(self):
        self.write();old=self.planner()
        rotated=self.planner(endpoint=ENDPOINT+'_ROTATED')
        self.assertEqual(rotated.ceiling,10);self.assertNotEqual(old.key,rotated.key)

    def test_unproved_filter_or_larger_pool_union_falls_back_without_dropping_pools(self):
        self.write()
        for q in (dict(QUERY,address='0x'+'55'*20),dict(QUERY,topics=['0x'+'66'*32,QUERY['topics'][1]]),
                dict(QUERY,topics=[QUERY['topics'][0],QUERY['topics'][1]+['0x'+'77'*32]])):
            self.assertEqual(self.planner(query=q).ceiling,10)

    def test_range_rejection_uses_exact_ten_block_fallback_and_survives_restart(self):
        self.write();rejected=[]
        def limited(calls):
            if any(int(p[0]['toBlock'],16)-int(p[0]['fromBlock'],16)>=10 for _,p in calls):
                rejected.extend(calls);raise BoundaryError('provider_log_block_range_limit')
            return self.provider(calls)
        self.assertEqual(self.planner().read(1,40,limited),[event(n) for n in range(1,41)])
        self.assertEqual(len(rejected),1);self.assertEqual(len(self.calls),4)
        self.history.close();self.history=PonsHistory(self.root/'history.sqlite',policy=POLICY_HASH)
        self.assertEqual(self.planner().ceiling,10)

    def test_dense_saturation_subdivides_deterministically_without_buyer_loss(self):
        self.write();requests=[]
        def dense(calls):
            requests.extend(calls)
            return [[event(n,i) for n in range(int(p[0]['fromBlock'],16),int(p[0]['toBlock'],16)+1)
                     for i in range(30)] for _,p in calls]
        planner=self.planner();rows=planner.read(1,40,dense)
        self.assertEqual(len(rows),1200)
        self.assertEqual({e['transactionHash'] for e in rows},
                         {event(n,i)['transactionHash'] for n in range(1,41) for i in range(30)})
        self.assertEqual([(int(p[0]['fromBlock'],16),int(p[0]['toBlock'],16)) for _,p in requests],
                         [(1,40),(1,20),(21,40)])
        self.assertLessEqual(self.planner().width,20)

    def test_new_comparison_can_clear_prior_rejection_but_not_reuse_an_old_proof(self):
        self.write();planner=self.planner()
        def limited(calls):
            if any(int(p[0]['toBlock'],16)-int(p[0]['fromBlock'],16)>=10 for _,p in calls):
                raise BoundaryError('provider_log_block_range_limit')
            return self.provider(calls)
        planner.read(1,40,limited);self.assertEqual(self.planner().ceiling,10)
        newer=dict(capability(),canonical_end_hash='0x'+'88'*32)
        self.write(newer);self.assertEqual(self.planner().ceiling,40)

    def test_aggregate_byte_overflow_splits_batch_before_block_ranges(self):
        attempts=[]
        def bounded(calls):
            attempts.append(len(calls))
            if len(calls)>1:raise BoundaryError('provider_response_capacity')
            return self.provider(calls)
        rows=self.planner().read(1,40,bounded)
        self.assertEqual(rows,[event(n) for n in range(1,41)])
        self.assertEqual(attempts,[4,2,1,1,2,1,1])

    def test_single_block_saturation_never_advances_canonical_checkpoint(self):
        self.history.set_meta('economic_cursor',0)
        with self.assertRaisesRegex(BoundaryError,'saturation'):
            self.planner().read(1,1,lambda calls:[[event(1,i) for i in range(1000)]])
        self.assertEqual(self.history.get_meta('economic_cursor'),0)

    def test_single_block_pool_union_saturation_splits_filters_without_losing_buyers(self):
        ids=[QUERY['topics'][1][0],'0x'+'77'*32]
        query=dict(QUERY,topics=[QUERY['topics'][0],ids]);requests=[]
        all_rows=[dict(event(1,i),topics=[query['topics'][0],ids[i//600]]) for i in range(1200)]
        def crowded(calls):
            requests.extend(calls)
            return [[r for r in all_rows if r['topics'][1] in p[0]['topics'][1]] for _,p in calls]
        planner=self.planner(query=query);rows=planner.read(1,1,crowded)
        self.assertEqual(rows,all_rows);self.assertEqual(len(requests),3)
        self.assertEqual(planner.events,1200)
        self.assertEqual(planner.telemetry()['filter_subdivisions'],1)

    def test_mixed_forks_in_one_block_are_not_a_complete_canonical_tape(self):
        rows=[event(1,0),dict(event(1,1),blockHash='0x'+'99'*32)]
        with self.assertRaisesRegex(BoundaryError,'mixed_block_forks'):
            self.planner().read(1,1,lambda calls:[rows])

    def test_reordered_duplicates_reduce_to_exact_order(self):
        rows=self.planner().read(1,3,lambda calls:[[event(3),event(1),event(2),event(1)]])
        self.assertEqual(rows,[event(1),event(2),event(3)])

    def test_removed_and_conflicting_logs_are_gaps_never_complete(self):
        for rows in ([dict(event(1),removed=True)],[event(1),dict(event(1),data='0xab')],
                [event(1),dict(event(1),transactionHash='0x'+'77'*32)],[event(99)]):
            with self.subTest(rows=rows):
                with self.assertRaises(BoundaryError):self.planner().read(1,1,lambda calls:[rows])

    def test_unknown_pagination_envelope_is_not_a_complete_array(self):
        with self.assertRaisesRegex(BoundaryError,'array'):
            self.planner().read(1,2,lambda calls:[dict(logs=[event(1)],next='page2')])

    def test_rate_limit_and_slow_provider_do_not_start_duplicate_recovery(self):
        calls=[]
        def limited(values):calls.append(values);raise BoundaryError('provider_http_429')
        with self.assertRaisesRegex(BoundaryError,'429'):self.planner().read(1,40,limited)
        self.assertEqual(len(calls),1)
        self.assertIsNone(self.history.get_meta('discovery_block'))

    def test_recovery_exhaustion_has_no_false_checkpoint_or_infinite_retry(self):
        from meme_machine.lanes.pons import log_windows
        def overloaded(calls):raise BoundaryError('provider_response_capacity')
        with patch.object(log_windows,'MAX_ATTEMPTS',2):
            with self.assertRaisesRegex(BoundaryError,'work_bound'):self.planner().read(1,40,overloaded)
        self.assertIsNone(self.history.get_meta('discovery_block'))

    def test_bad_density_hint_never_expands_the_capability_ceiling(self):
        planner=self.planner()
        self.history.set_meta(planner.key,dict(width=1000000,bytes_per_block='nan'))
        restored=self.planner();self.assertEqual(restored.ceiling,10)
        self.assertLessEqual(restored.width,10);self.assertEqual(restored.bytes_per_block,0)

    def test_optional_fifty_element_batching_does_not_omit_any_block(self):
        batches=[]
        def acquire(calls):batches.append(len(calls));return self.provider(calls)
        rows=LogWindows(ENDPOINT,QUERY,batch_elements=50).read(1,600,acquire)
        self.assertEqual(batches,[50,10]);self.assertEqual(rows,[event(n) for n in range(1,601)])

    def test_paid_scout_fallback_uses_complete_filter_while_public_reads_keep_ten(self):
        from meme_machine.lanes.pons.pons_natural_observation import MarketScout
        from meme_machine.runtime.robinhood.plane import Plane
        plane=Plane(self.root/'plane');self.addCleanup(plane.close);scout=MarketScout(plane)
        query=dict(address=scout.factory,topics=[[scout.launch,scout.graduation]])
        self.write(capability(query));calls=[]
        class Client:
            endpoint=ENDPOINT;canonical_authority=True
            def batch(client,values,**kw):
                calls.extend(values)
                return [[dict(event(n),address=scout.factory,topics=[scout.launch])
                    for n in range(int(p[0]['fromBlock'],16),int(p[0]['toBlock'],16)+1)] for _,p in values]
        pages=[dict(query,fromBlock=hex(n),toBlock=hex(n+9)) for n in (1,11,21,31)]
        with patch.dict(os.environ,{'MM_PONS_LOG_CAPABILITY_FILE':str(self.file)}):
            client=Client();paid=scout._pages(client,pages)
            self.assertEqual(len(calls),1);self.assertEqual(len(paid[0]),40)
            calls.clear();client.canonical_authority=False;public=scout._pages(client,pages)
            self.assertEqual(len(calls),4)
            self.assertEqual([e for p in public for e in p],paid[0])


class EvidenceCase(unittest.TestCase):
    def test_cached_hash_header_cannot_certify_an_orphaned_economic_block(self):
        from engineering.pons_history.fixtures import Tape
        from engineering.robinhood_scout.replay import WireTape,markets
        from meme_machine.lanes.pons.pons_selective_v4 import collect_v4_activities
        tape=Tape(candidates=1);wire=WireTape(tape);original=tape._read
        def read(method,params):
            value=original(method,params)
            if method=='eth_getBlockByNumber' and params[0]!=hex(0):value=dict(value,hash='0x'+'99'*32)
            return value
        tape._read=read
        selected=[dict(m,pool_id=m['key'].pool_id()) for m in markets(tape)]
        with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=wire.response), \
             patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',side_effect=wire.session):
            with self.assertRaisesRegex(BoundaryError,'canonical_header_membership'):
                collect_v4_activities(ENDPOINT,markets=selected,start_block=tape.grad+1,end_block=tape.grad+4)
        self.assertNotIn('eth_getTransactionReceipt',wire.snapshot()['methods'])

    def test_range_rejection_in_success_http_envelope_is_classified_and_not_retried(self):
        from meme_machine.lanes.pons.provider import Rpc
        replies=io.BytesIO(json.dumps(dict(jsonrpc='2.0',id=1,error=dict(code=-32600,
            message='Under the Free tier plan, up to a 10 block range; '+ENDPOINT))).encode())
        with patch('meme_machine.lanes.pons.provider.urlopen',return_value=replies) as wire:
            rpc=Rpc(ENDPOINT,retries=2)
            with self.assertRaisesRegex(BoundaryError,'^provider_log_block_range_limit$'):
                rpc.call('eth_getLogs',[dict(QUERY,fromBlock='0x1',toBlock='0x28')])
        self.assertEqual(wire.call_count,1);self.assertEqual(rpc.physical_http_requests,1)
        self.assertNotIn('OFFLINE_PAYG_FIXTURE',json.dumps(rpc.telemetry()))

    def test_historical_witness_receipt_sender_matches_transaction_body_fallback(self):
        from engineering.pons_history.fixtures import Tape
        from meme_machine.lanes.pons.pons_historical import Preparation, MANAGER, SWAP
        with tempfile.TemporaryDirectory() as tmp:
            history=PonsHistory(Path(tmp)/'history',policy=POLICY_HASH)
            try:
                tape=Tape(candidates=1);first,last=tape.grad+1,tape.grad+4
                # The native tape's exact PoolKey determines the indexed filter.
                from engineering.robinhood_scout.replay import markets
                pool=markets(tape)[0]['key'].pool_id();query=dict(address=MANAGER,topics=[[SWAP],[pool]])
                logs=tape._read('eth_getLogs',[dict(query,fromBlock=hex(first),toBlock=hex(last))])
                p=Preparation(history,tape.provider)
                before=tape.telemetry()['methods'].get('eth_getTransactionByHash',0)
                full=p._witness(logs,query,first,last)
                body_reads=tape.telemetry()['methods'].get('eth_getTransactionByHash',0)-before
                original=tape.receipt_value
                tape.receipt_value=lambda tx:dict(original(tx),**{'from':tape.senders.get(tx,'0x'+'01'*20)})
                before=tape.telemetry()['methods'].get('eth_getTransactionByHash',0)
                native=p._witness(logs,query,first,last)
                self.assertEqual({k:dict(hash=v['hash'],blockHash=v['blockHash'],sender=v['from']) for k,v in native['txs'].items()},
                                 {k:dict(hash=v['hash'],blockHash=v['blockHash'],sender=v['from']) for k,v in full['txs'].items()})
                self.assertEqual(native['raw'],full['raw']);self.assertGreater(body_reads,0)
                self.assertEqual(tape.telemetry()['methods'].get('eth_getTransactionByHash',0),before)
            finally:history.close()

    def test_runtime_rates_keep_physical_billing_and_throughput_units_distinct(self):
        from meme_machine.lanes.pons.provider_admission import Admission
        from meme_machine.runtime.robinhood import provider_usage as usage
        clock=[1000.]
        with tempfile.TemporaryDirectory() as tmp:
            gate=Admission(Path(tmp)/'provider',ENDPOINT,lane='pons',clock=lambda:clock[0],
                sleeper=lambda t:clock.__setitem__(0,clock[0]+t))
            def wire():usage.http_started(128);usage.http_received(256)
            gate.invoke(wire,['eth_chainId','eth_getBlockReceipts'],'pons_diagnostics',batch=True)
            with gate.connect() as db:
                db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',('pending',gate.endpoint,20,999.,1010.))
                db.execute('INSERT INTO queue_meta VALUES(?,?)',('pending','pons-survivor'))
            with patch.object(usage.time,'monotonic',return_value=1000.):row=gate.telemetry()
            rate=row['rolling_10_seconds'];self.assertEqual(rate['physical_rps'],.1)
            self.assertEqual(rate['logical_rpc_elements'],2)
            self.assertEqual(rate['diagnostic_method_cu']['estimated_cu'],20)
            self.assertEqual(rate['diagnostic_throughput_cu'],505)
            self.assertEqual(rate['admission_arrival_rate'],.1)
            self.assertEqual(row['health']['oldest_queue_wait_seconds'],1)
            self.assertEqual(row['health']['original_deadline_remaining_seconds'],10)
            self.assertIsNone(rate['verified_billed_cu'])

    def test_unknown_method_is_never_zero_priced_in_throughput_telemetry(self):
        from meme_machine.lanes.pons.provider_admission import Admission
        from meme_machine.runtime.robinhood import provider_usage as usage
        with tempfile.TemporaryDirectory() as tmp:
            gate=Admission(Path(tmp)/'provider',ENDPOINT,lane='pons',clock=lambda:1000.)
            gate.invoke(lambda:usage.http_started(),['unknown_read'],'pons_diagnostics')
            with patch.object(usage.time,'monotonic',return_value=1000.):row=gate.telemetry()
            self.assertIsNone(row['rolling_10_seconds']['diagnostic_throughput_cu'])
            self.assertEqual(row['rolling_10_seconds']['unpriced_throughput_methods'],{'unknown_read':1})

    def test_two_application_binding_and_rotation_are_secret_free(self):
        from engineering.robinhood_payg.identity import reconcile
        pons='SYNTHETIC_SECRET_PONS';pump='SYNTHETIC_SECRET_PUMP'
        env='MM_ROBINHOOD_READ_RPC_URL='+ENDPOINT.replace('OFFLINE_PAYG_FIXTURE',pons)+'\n'+ \
            'MM_SOLANA_READ_RPC_URL=https://solana-mainnet.g.alchemy.com/v2/'+pump
        metadata={'v5h0vqr0wpp9zscj':{'masked_api_key':'********PONS'},
            '9bin99s96t7ga5e9':{'api_key':pump}}
        row=reconcile(env,metadata)
        self.assertEqual([r['administrative_key_agreement'] for r in row['applications']],[True,True])
        rotated=reconcile(env.replace(pons,pons+'_ROTATED'),metadata)
        self.assertFalse(rotated['applications'][0]['administrative_key_agreement'])
        self.assertNotEqual(row['applications'][0]['endpoint_fingerprint'],rotated['applications'][0]['endpoint_fingerprint'])
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(row))


class ProofCase(unittest.TestCase):
    def test_separate_wider_comparison_preserves_original_proof_and_authenticates_nonempty_union(self):
        from engineering.robinhood_payg import proof,capability as probe
        from engineering.pons_history.fixtures import Tape
        from meme_machine.lanes.pons.pons_historical import FACTORY,LAUNCH,GRADUATION
        tape=Tape(candidates=1);query=dict(address=FACTORY,topics=[[LAUNCH,GRADUATION]])
        def opener(request,**kw):
            qs=json.loads(request.data);batch=isinstance(qs,list)
            replies=[dict(jsonrpc='2.0',id=q['id'],result=tape._read(q['method'],q['params']))
                     for q in (qs if batch else [qs])]
            return io.BytesIO(json.dumps(replies if batch else replies[0]).encode())
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp);proof.isolate(root,{'MM_ROBINHOOD_READ_RPC_URL':ENDPOINT})
            budget=probe.RangeBudget()
            with proof.transports(budget,opener=opener,offline=True):
                row=probe.compare(root,budget,query=query,first=tape.grad-12,team_id='synthetic-team')
            self.assertEqual(row['status'],'SUPPORTED_40_BLOCK_SAMPLE')
            self.assertGreater(row['comparison']['event_count'],0)
            self.assertEqual(proof.contract()['maximum_getLogs_blocks_per_element'],10)
            cap=load_capability(ENDPOINT,query,path=root/'comparison.json')
            self.assertEqual(cap['range_blocks'],40)
            self.assertFalse(row['guard_removed'])

    def test_unscoped_wider_comparison_and_unreviewed_subscription_filters_are_refused(self):
        from engineering.robinhood_payg.capability import validate
        for query in (dict(address='0x'+'66'*20,topics=QUERY['topics']),
                dict(topics=[QUERY['topics'][0]]),dict(QUERY,fromBlock='0x1')):
            with self.assertRaises(ValueError):validate(query)

    def test_native_forward_workload_runs_offline_without_creating_a_paper_book(self):
        from engineering.robinhood_payg import proof
        from tests.test_robinhood_scout import ObservationTape
        from meme_machine.lanes.pons.provider import Rpc
        tape=ObservationTape(candidates=1);tape.top=tape.grad
        def opener(request,**kw):
            qs=json.loads(request.data);batch=isinstance(qs,list)
            replies=[dict(jsonrpc='2.0',id=q['id'],result=tape._read(q['method'],q['params']))
                     for q in (qs if batch else [qs])]
            return io.BytesIO(json.dumps(replies if batch else replies[0]).encode())
        def canonical(*a,**kw):
            from meme_machine.lanes.pons.provider_topology import configured_rpc
            return configured_rpc(ENDPOINT,limit=200,per_scope=200,retries=0)
        def public(*a,**kw):return Rpc('https://'+proof.PUBLIC,limit=200,per_scope=200,retries=0)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp);proof.isolate(root,{'MM_ROBINHOOD_READ_RPC_URL':ENDPOINT})
            budget=proof.Budget()
            with proof.transports(budget,opener=opener,offline=True), \
                 patch('meme_machine.lanes.pons.pons_selective_cohort._discovery',side_effect=public), \
                 patch('meme_machine.lanes.pons.pons_survivor_runtime.configured_rpc',side_effect=canonical):
                result=proof.workload(root,budget,stop_after=30)
            self.assertEqual(result['status'],'INSUFFICIENT_SAMPLE')
            self.assertEqual(len(result['samples']),2);self.assertFalse(result['guard_removed'])
            self.assertGreater(budget.counts['total_physical_http_attempts'],0)
            self.assertFalse(list(root.rglob('paper.sqlite')))
            self.assertEqual(result['authentic_funded_position_samples'],0)
            self.assertTrue(result['samples'][0]['provider_governor']['rolling_10_seconds']['available'])
            self.assertEqual(result['samples'][0]['scout']['pre_enrollment_coverage'],'UNOBSERVED')
            self.assertIn('current_immutable_cache',result['samples'][0])

    def test_default_preflight_is_provider_free_and_keeps_all_reviewed_limits(self):
        from engineering.robinhood_payg import proof
        with patch('sys.stdout',new_callable=io.StringIO) as output, \
             patch('meme_machine.lanes.pons.provider.urlopen',side_effect=AssertionError('provider dispatch')):
            self.assertEqual(proof.main([]),0)
        row=json.loads(output.getvalue());self.assertEqual(row['execution_status'],'NOT_RUN')
        self.assertEqual(row['contract']['maximum_elapsed_seconds'],300)
        self.assertEqual(row['contract']['maximum_getLogs_blocks_per_element'],10)
        self.assertFalse(row['contract']['guard_removal_allowed_by_this_plan'])

    def test_edited_proof_contract_is_rejected_before_any_work(self):
        from engineering.robinhood_payg import proof
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'plan';path.write_text('{}')
            with patch.object(proof,'PLAN',path):
                with self.assertRaisesRegex(ValueError,'contract_changed'):proof.contract()

    def test_unreviewed_wider_query_is_refused_before_dispatch(self):
        from engineering.robinhood_payg.proof import Budget,ProofStop
        b=Budget()
        with self.assertRaisesRegex(ProofStop,'maximum_getLogs_blocks_per_element'):
            b.reserve(ENDPOINT,[dict(method='eth_getLogs',params=[dict(QUERY,fromBlock='0x1',toBlock='0x28')])])
        self.assertEqual(b.counts['total_physical_http_attempts'],0)

    def test_paused_and_unpriced_provider_endpoints_are_refused(self):
        from engineering.robinhood_payg.proof import Budget,ProofStop
        for url in ('https://arbitrum-mainnet.g.alchemy.com/v2/OFFLINE',
                    'https://solana-mainnet.g.alchemy.com/v2/OFFLINE'):
            with self.assertRaisesRegex(ProofStop,'unreviewed_endpoint'):
                Budget().reserve(url,[dict(method='eth_chainId',params=[])])

    def test_physical_logical_cu_and_response_reservations_are_independent(self):
        from engineering.robinhood_payg.proof import Budget
        b=Budget();row=b.reserve(ENDPOINT,[dict(method='eth_chainId',params=[]),
            dict(method='eth_getLogs',params=[dict(QUERY,fromBlock='0x1',toBlock='0xa')])])
        b.received(row,512)
        self.assertEqual(b.counts['total_physical_http_attempts'],1)
        self.assertEqual(b.counts['total_logical_rpc_elements'],2)
        self.assertEqual(b.counts['diagnostic_estimated_alchemy_cu'],60)
        self.assertEqual(b.counts['http_response_bytes'],512)
        self.assertIsNone(b.snapshot()['verified_billed_cu'])

    def test_original_physical_limit_cannot_be_overrun_by_a_batch(self):
        from engineering.robinhood_payg.proof import Budget,ProofStop
        b=Budget();b.counts['alchemy_physical_http_attempts']=300
        with self.assertRaisesRegex(ProofStop,'maximum_alchemy_physical_http_attempts'):
            b.reserve(ENDPOINT,[dict(method='eth_chainId',params=[])])
        self.assertEqual(b.counts['total_physical_http_attempts'],0)

    def test_original_wall_deadline_is_not_extended_by_retries(self):
        from engineering.robinhood_payg.proof import Budget,ProofStop
        clock=[0.];b=Budget(clock=lambda:clock[0]);clock[0]=300
        with self.assertRaisesRegex(ProofStop,'maximum_elapsed_seconds'):
            b.reserve(ENDPOINT,[dict(method='eth_chainId',params=[])])

    def test_transport_counts_real_http_boundary_without_revealing_endpoint(self):
        from engineering.robinhood_payg.proof import Budget,transports
        from meme_machine.lanes.pons.provider import Rpc
        b=Budget()
        with transports(b,opener=lambda r,**kw:io.BytesIO(b'{"id":1,"jsonrpc":"2.0","result":"0x1237"}'),offline=True):
            self.assertEqual(Rpc(ENDPOINT,retries=0).verify_chain(),4663)
        self.assertEqual(b.counts['total_physical_http_attempts'],1)
        self.assertEqual(b.reserved_bytes,0)
        self.assertNotIn('OFFLINE_PAYG_FIXTURE',json.dumps(b.snapshot()))

    def test_provider_errors_are_terminal_without_retry_or_error_text(self):
        from engineering.robinhood_payg.proof import Budget,transports,ProofStop
        from meme_machine.lanes.pons.provider import Rpc
        b=Budget();calls=[]
        def response(request,**kwargs):
            calls.append(request)
            return io.BytesIO(json.dumps(dict(id=1,error=dict(message=ENDPOINT,code=429))).encode())
        with transports(b,opener=response,offline=True):
            with self.assertRaisesRegex(ProofStop,'rpc_error_no_retry'):Rpc(ENDPOINT,retries=0).verify_chain()
        self.assertEqual(len(calls),1);self.assertNotIn('OFFLINE_PAYG_FIXTURE',json.dumps(b.snapshot()))

    def test_proof_stop_is_not_caught_by_native_provider_retry_handlers(self):
        from engineering.robinhood_payg.proof import ProofStop
        self.assertFalse(issubclass(ProofStop,Exception))

    def test_resource_and_subscription_byte_ceilings_stop_before_more_work(self):
        from engineering.robinhood_payg.proof import Budget,ProofStop
        budget=Budget();budget.counts['http_response_bytes']=budget.plan['maximum_http_response_bytes']-1
        with self.assertRaisesRegex(ProofStop,'http_response_reservation'):
            budget.reserve(ENDPOINT,[dict(method='eth_chainId',params=[])])
        self.assertEqual(budget.counts['total_physical_http_attempts'],0)
        budget=Budget()
        with self.assertRaisesRegex(ProofStop,'maximum_sequencer_decoded_bytes'):
            budget.feed(budget.plan['maximum_sequencer_decoded_bytes']+1)
        self.assertEqual(budget.counts['sequencer_decoded_bytes'],0)

    def test_independent_supervisor_reaps_resource_exhaustion_without_provider_work(self):
        """Synthetic process samples exercise the actual parent stop/reap path."""
        from types import SimpleNamespace
        from engineering.robinhood_payg import proof
        plan=proof.contract()
        safe=dict(at=0.,cpu_seconds=0.,rss_bytes=1,artifact_bytes=0,
                  volume_available_bytes=plan['minimum_volume_free_bytes']+1)
        cases=[('maximum_process_group_rss_bytes',[dict(safe,rss_bytes=plan['maximum_process_group_rss_bytes']+1)],[0.,0.]),
          ('maximum_temporary_artifact_bytes',[dict(safe,artifact_bytes=plan['maximum_temporary_artifact_bytes'])],[0.,0.]),
          ('minimum_volume_free_bytes',[dict(safe,volume_available_bytes=plan['minimum_volume_free_bytes']-1)],[0.,0.]),
          ('maximum_process_group_cpu_core_equivalent',[safe,dict(safe,at=30.,cpu_seconds=60.)],[0.,0.,30.]),
          ('maximum_elapsed_seconds',[safe],[0.,301.]),
          ('resource_measurement_unavailable',[OSError('synthetic sample failure')],[0.,0.])]
        for reason,samples,clock in cases:
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as tmp, \
                 patch.object(proof.os,'fork',return_value=987654), \
                 patch.object(proof.os,'waitpid',side_effect=[(0,0)]*len(samples)+[(987654,9)]) as reap, \
                 patch.object(proof.os,'killpg') as kill, \
                 patch.object(proof,'proc_sample',side_effect=samples), \
                 patch.object(proof.time,'monotonic',side_effect=clock), \
                 patch.object(proof.time,'sleep'),patch.object(proof,'identity',return_value={'synthetic':True}), \
                 patch.object(proof,'transports',side_effect=AssertionError('provider work forbidden')) as transport:
                row=proof.supervise(Path(tmp),{},budget_factory=lambda:SimpleNamespace(plan=dict(plan)))
                self.assertEqual(row['status'],'FAIL');self.assertEqual(row['forced_stop'],reason)
                kill.assert_called_once_with(987654,proof.signal.SIGKILL)
                self.assertEqual(reap.call_args.args,(987654,0));transport.assert_not_called()

    def test_final_diagnostics_cannot_exceed_resource_limit_or_claim_pass(self):
        from engineering.robinhood_payg.proof import write_report,ProofStop,proc_sample
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'history.sqlite').write_bytes(b'0123456')
            (root/'history.sqlite-wal').write_bytes(b'01234567890')
            with patch('os.statvfs',return_value=SimpleNamespace(f_bavail=100,f_frsize=4096)):
                row=proc_sample(os.getpid(),root)
            self.assertEqual(row['sqlite_database_bytes'],7);self.assertEqual(row['sqlite_wal_bytes'],11)
            path=root/'result.json'
            result=write_report(path,dict(status='PASS',samples=['synthetic'*1000]),512)
            self.assertEqual(result['status'],'FAIL');self.assertTrue(result['diagnostics_too_large'])
            self.assertLessEqual(sum(p.stat().st_size for p in root.iterdir()),512)
            with self.assertRaisesRegex(ProofStop,'maximum_temporary_artifact_bytes'):
                write_report(path,dict(status='PASS'),1)

    def test_historical_malformed_receipt_sender_never_triggers_untrusted_buyer_evidence(self):
        from engineering.pons_history.fixtures import Tape
        from meme_machine.lanes.pons.pons_historical import Preparation, MANAGER, SWAP
        from engineering.robinhood_scout.replay import markets
        with tempfile.TemporaryDirectory() as tmp:
            history=PonsHistory(Path(tmp)/'history',policy=POLICY_HASH)
            try:
                tape=Tape(candidates=1);first,last=tape.grad+1,tape.grad+4
                query=dict(address=MANAGER,topics=[[SWAP],[markets(tape)[0]['key'].pool_id()]])
                logs=tape._read('eth_getLogs',[dict(query,fromBlock=hex(first),toBlock=hex(last))])
                original=tape.receipt_value;tape.receipt_value=lambda tx:dict(original(tx),**{'from':'invalid'})
                with self.assertRaisesRegex(BoundaryError,'sender_identity'):
                    Preparation(history,tape.provider)._witness(logs,query,first,last)
            finally:history.close()
