"""Private owner + real Survivor step/history/decision COMMIT, offline only.

The prewrite financial/native replay and anonymous owner IPC are genuine native
operations on disposable state. Root/unit/install and provider/header facts are
explicit fixture inputs. No provider, full-market or normal-readiness result.
"""
from contextlib import closing
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_pump_current_input_native as native
from tests import test_stopped_flat_native_boot as stopped


def child_case(cap,record,fixture):
    import os,time,sqlite3,threading
    from types import SimpleNamespace
    from meme_machine.runtime.survivor_history import Worker
    from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime,SWAP_SCOPE
    from meme_machine.solana_evidence_plane import EvidenceReader
    from meme_machine.solana_selective_history import ConsumerReader
    from meme_machine.runtime import pump_survivor_work as observation
    from meme_machine.runtime import native_work_cohort as common
    from meme_machine.runtime.stop import Shutdown,requested
    from tests.lanes.pump.test_pumpswap_survivor import bridge_facts
    root=Path(os.environ['MM_STATE_ROOT']);mode=fixture.get('mode','normal');at=int(native.NOW)
    os.environ['MM_DIRECTIONAL_SLEEVE_DB']=str(root/'pump/directional-sleeve.sqlite')
    if fixture.get('observe',True):os.environ['MM_ECONOMIC_COHORT_DIAGNOSTICS']='1'
    else:os.environ.pop('MM_ECONOMIC_COHORT_DIAGNOSTICS',None)
    measures=[];owner_threads=[]
    def factory():
        runtime=Runtime(root/'pump/pump-survivor',125000,
            record['boot_eligibility']['epoch_id'],SimpleNamespace(cluster=lambda value:value))
        owner_threads.append(threading.get_native_id())
        runtime.now=lambda:at;runtime.discover=lambda:None
        runtime.plane.close();original_reader=EvidenceReader(root/'shared/solana-evidence.sqlite')
        reader=ConsumerReader(original_reader)
        runtime.plane=SimpleNamespace(reader=reader,_selective_reader=lambda:reader,
            frontier=lambda scope:100,block_time=lambda slot:at,bounds=lambda *a,**k:(100,100),
            interest=lambda *a,**k:None,advance_interest=lambda *a,**k:None,
            command=lambda *a,**k:None,
            close=reader.close)
        def fresh_state(*args,**kwargs):
            if mode=='cancel_before_decision':requested.set();raise Shutdown()
            return dict(slot=100,market_time=at)
        runtime.fresh_state=fresh_state
        facts=bridge_facts(600);offset=at-600
        facts['now']+=offset;facts['graduation_at']+=offset;facts['base_end']+=offset
        facts['price_points']=[dict(value,at=value['at']+offset) for value in facts['price_points']]
        facts['demand_events']=[dict(value,at=value['at']+offset) for value in facts['demand_events']]
        facts['continuity_complete']=False # genuine native rejection, never a fill.
        runtime.reconstruct=lambda *a,**k:facts
        original_step=runtime.step
        def step(*,admit):
            queries=dict(history=0,shared=0);hashes=dict(observer=0,common=0)
            def history_query(sql):queries['history']+=1
            def shared_query(sql):queries['shared']+=1
            runtime.history.db.set_trace_callback(history_query)
            runtime.candidate_history.db.set_trace_callback(shared_query)
            def counted(module,label):
                actual=module.checksum
                def digest(value):hashes[label]+=1;return actual(value)
                return digest
            started=time.perf_counter();cpu=time.thread_time()
            try:
                with patch.object(observation,'checksum',counted(observation,'observer')), \
                     patch.object(common,'checksum',counted(common,'common')):
                    return original_step(admit=admit)
            finally:
                measures.append(dict(admit=admit,wall=time.perf_counter()-started,
                    cpu=time.thread_time()-cpu,queries=queries,metadata_hashes=hashes))
                runtime.history.db.set_trace_callback(None)
                runtime.candidate_history.db.set_trace_callback(None)
        runtime.step=step
        return runtime
    worker=Worker(factory,enrichment_enabled=False)
    error=None;value=None;extra={}
    try:
        worker.prime(timeout=5)
        runtime=worker.service
        def inject():
            if mode=='decision_failure':runtime.candidate_history.db.execute(
                "CREATE TEMP TRIGGER fail_decision BEFORE INSERT ON decisions BEGIN SELECT RAISE(ABORT,'native-unit-decision'); END")
            if mode=='history_failure':runtime.history.db.execute(
                "CREATE TEMP TRIGGER fail_history BEFORE INSERT ON candidates WHEN json_extract(NEW.body,'$.decision_id') IS NOT NULL BEGIN SELECT RAISE(ABORT,'native-unit-history'); END")
        worker.pool.submit(inject).result(timeout=2)
        if mode=='foreign_transaction':
            def foreign_transaction():
                runtime.history.db.execute('BEGIN')
                try:
                    row=runtime.history.get('native-survivor');runtime.history.save(row)
                finally:runtime.history.db.execute('ROLLBACK')
                return runtime.native_work.snapshot()
            extra=worker.pool.submit(foreign_transaction).result(timeout=2)
        elif mode=='rollback':
            def rollback():
                before=runtime.native_work.snapshot()
                try:
                    with runtime.history.transaction():
                        runtime.history.rows(include_retired=True)
                        row=runtime.history.get('native-survivor');row['last_checked']=at
                        runtime.history.save(row)
                        raise RuntimeError('native-unit-rollback')
                except RuntimeError:pass
                return dict(before=before,after=runtime.native_work.snapshot())
            extra=worker.pool.submit(rollback).result(timeout=2)
        else:
            worker.tick(at,admit=True)
            try:value=worker.future.result(timeout=5)
            except sqlite3.Error as failure:error=type(failure).__name__
            except Shutdown:error='Shutdown';requested.clear()
        def stored():
            return dict(observer=(None if runtime.native_work is None else runtime.native_work.snapshot()),
                history=runtime.history.db.execute("SELECT body,hash FROM candidates WHERE id='native-survivor'").fetchone(),
                histories=runtime.history.db.execute('SELECT id,body,hash FROM candidates ORDER BY id').fetchall(),
                decisions=runtime.candidate_history.db.execute("SELECT id,body,hash FROM decisions WHERE candidate='native-survivor' ORDER BY id").fetchall(),
                transaction=runtime.history.db.in_transaction)
        result=worker.pool.submit(stored).result(timeout=2)
        if mode=='foreign':
            result['foreign']=runtime.native_work.snapshot()
            result['after_foreign']=worker.pool.submit(lambda:runtime.native_work.snapshot()).result(timeout=2)
        if mode=='missing_census':
            def missing():
                work=observation.PumpSurvivorWork(cap,runtime.history.path,
                    record['boot_eligibility']['epoch_id'],runtime.native_work.binding['policy_sha256'])
                original=runtime.history._native_work;runtime.history._native_work=work
                try:
                    row=runtime.history.get('native-survivor');runtime.history.save(row)
                    return work.snapshot()
                finally:runtime.history._native_work=original
            result['missing']=worker.pool.submit(missing).result(timeout=2)
        result.update(error=error,status=value,extra=extra,measures=measures,
            worker_thread=owner_threads[0],main_thread=threading.get_native_id())
        return result
    finally:
        try:worker.close(timeout=5)
        except (sqlite3.Error,Shutdown):
            if error is None:raise


ANCHOR="        else:\n            from meme_machine.runtime.candidate_history import CandidateHistory"
if native.CHILD.count(ANCHOR)!=1:raise AssertionError('private fixture anchor changed')
CHILD=native.CHILD.split(ANCHOR,1)[0]+'''        else:
            from tests.test_pump_survivor_work import child_case
            print(json.dumps(child_case(cap,record,fixture)),flush=True)
            sys.stdin.readline();cap.close()
except BaseException:
    import traceback;traceback.print_exc(file=sys.stderr)
    raise SystemExit(2)
'''


class PumpSurvivorWorkTests(unittest.TestCase):
    def case(self,*,observe=True,mode='normal',age=600,population=1):
        case=native.CurrentPrivateInputTests()
        original=stopped.StoppedFlatNativeBootTests.original_context
        # The original empty native books earn the same genuine flat prewrite
        # proof; no terminal fixture candidate is omitted from this corpus.
        with patch.object(stopped.StoppedFlatNativeBootTests,'original_context',
                lambda value,**kwargs:original(value,terminals=False)):
            case.setUp()
        self.addCleanup(case.doCleanups)
        from meme_machine.runtime.survivor_history import History
        from meme_machine.lanes.pump.pumpswap_survivor import POLICY_HASH
        from tests.test_solana_closure import state_at
        path=case.root/'pump/pump-survivor/history.sqlite'
        with closing(History(path,policy=POLICY_HASH)) as history:
            for index in range(population):
                identity='native-survivor' if index==0 else 'queued-survivor:'+str(index)
                history.graduate(identity,dict(at=int(native.NOW)-age,slot=100,
                    pool='native-pool',quote_asset='SOL',quote_amount=100,mint_amount=10,
                    identity='synthetic-native-migration:'+str(index),source='offline-native-fixture'))
                history.append(identity,through=int(native.NOW)-age,events=[],
                    points=[(int(native.NOW)-age,'10')],complete=True)
        # A real candidate binding is required even when genuine complete
        # program-filtered archive coverage subsequently proves zero swaps.
        # Both are native writes before the original full prewrite reseal.
        state,source_history=state_at(case.root/'shared/solana-evidence.sqlite')
        try:source_history.bind('pumpswap','native-pool')
        finally:state.writer.close()
        case.prepare(0);case.child('source')
        with patch.object(native,'CHILD',CHILD):_,value=case.child('pump',observe=observe,mode=mode)
        return value

    def test_actual_native_branch_and_both_original_durable_outcomes(self):
        value=self.case();view=value['observer']
        self.assertIsNone(value['error']);self.assertFalse(value['transaction'])
        self.assertNotEqual(value['worker_thread'],value['main_thread'])
        self.assertEqual(view['state'],'MEASURING')
        self.assertEqual(view['inherited_inventory']['rows'],1)
        self.assertEqual(view['preparation']['completed_cohorts'],1,
            dict(boundary=value['status']['last_boundary'],observer=view))
        self.assertEqual(view['evaluation']['completed_cohorts'],1)
        self.assertEqual(view['latest_native_attention']['evaluation_requests'],1)
        self.assertEqual(len(value['decisions']),1)
        self.assertFalse(view['readiness_authority'] or view['funding_authority'])

    def test_decision_sql_failure_cannot_complete_evaluation(self):
        value=self.case(mode='decision_failure')
        self.assertEqual(value['error'],'IntegrityError');self.assertEqual(value['decisions'],[])
        self.assertEqual(value['observer']['evaluation']['completed_cohorts'],0)
        self.assertEqual(value['observer']['evaluation']['pending_units'],1)

    def test_shared_decision_without_final_history_commit_remains_pending(self):
        value=self.case(mode='history_failure')
        self.assertEqual(value['error'],'IntegrityError');self.assertEqual(len(value['decisions']),1)
        self.assertEqual(value['observer']['evaluation']['completed_cohorts'],0)
        self.assertEqual(value['observer']['evaluation']['pending_units'],1)

    def test_original_outer_rollback_discards_inventory_and_save_observations(self):
        value=self.case(mode='rollback');before=value['extra']['before'];after=value['extra']['after']
        self.assertEqual(before['committed_candidate_saves'],after['committed_candidate_saves'])
        self.assertEqual(before['committed_candidate_save_chain'],after['committed_candidate_save_chain'])
        self.assertEqual(before['latest_native_inventory'],after['latest_native_inventory'])

    def test_foreign_thread_cannot_continue_native_owner_measurement(self):
        value=self.case(mode='foreign')
        self.assertEqual(value['foreign']['state'],'UNKNOWN')
        self.assertEqual(value['after_foreign']['state'],'UNKNOWN')

    def test_first_native_mutation_without_inherited_traversal_is_unknown(self):
        value=self.case(mode='missing_census')
        self.assertEqual(value['missing']['state'],'UNKNOWN')

    def test_empty_native_inventory_is_not_an_evaluation_request(self):
        value=self.case(population=0);view=value['observer']
        self.assertIsNone(value['error']);self.assertEqual(view['inherited_inventory']['rows'],0)
        self.assertEqual(view['latest_native_attention']['native_nonheld_rows'],0)
        self.assertEqual(view['evaluation']['completed_cohorts'],0)
        self.assertEqual(view['evaluation']['active_cohorts'],0)

    def test_original_ten_minute_floor_prepares_without_evaluation(self):
        value=self.case(age=1);view=value['observer']
        self.assertIsNone(value['error']);self.assertEqual(value['status']['last_boundary'],None)
        self.assertEqual(view['preparation']['completed_cohorts'],1)
        self.assertEqual(view['latest_native_attention']['age_eligible_rows'],0)
        self.assertEqual(view['evaluation']['active_cohorts'],0)
        self.assertEqual(view['evaluation']['completed_cohorts'],0)
        self.assertEqual(json.loads(value['history'][0])['state'],'aging')

    def test_original_horizon_retirement_is_not_evaluation_completion(self):
        from meme_machine.lanes.pump.pumpswap_survivor import POLICY
        value=self.case(age=POLICY['maximum_age_seconds']+1);view=value['observer']
        self.assertIsNone(value['error']);self.assertEqual(value['status']['last_boundary'],None)
        self.assertEqual(json.loads(value['history'][0])['state'],'retired')
        self.assertEqual(view['evaluation']['completed_cohorts'],0)
        self.assertEqual(view['evaluation']['active_cohorts'],0)

    def test_actual_branch_cancellation_keeps_request_pending_without_decision(self):
        value=self.case(mode='cancel_before_decision');view=value['observer']
        self.assertEqual(value['error'],'Shutdown');self.assertEqual(value['decisions'],[])
        self.assertFalse(value['transaction'])
        self.assertEqual(view['evaluation']['pending_units'],1)
        self.assertEqual(view['evaluation']['completed_cohorts'],0)

    def test_foreign_native_transaction_cannot_publish_a_save_receipt(self):
        value=self.case(mode='foreign_transaction')
        self.assertFalse(value['transaction']);self.assertEqual(value['extra']['state'],'UNKNOWN')

    def test_default_and_observed_same_native_workload_keep_sql_and_payloads_equal(self):
        # Identical 64-member inherited corpus and one real selected native
        # evaluation; metadata does not issue64 strategy calls or extraSQL.
        plain=self.case(observe=False,population=64);observed=self.case(population=64)
        self.assertIsNone(plain['observer'])
        self.assertEqual(plain['history'],observed['history'])
        self.assertEqual(plain['histories'],observed['histories'])
        self.assertEqual(plain['decisions'],observed['decisions'])
        self.assertEqual(plain['measures'][-1]['queries'],observed['measures'][-1]['queries'])
        print('pump-survivor-native-step-observation-cost '+json.dumps(dict(
            plain=plain['measures'][-1],observed=observed['measures'][-1]),sort_keys=True))


if __name__=='__main__':unittest.main()
