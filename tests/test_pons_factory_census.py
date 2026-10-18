"""Original native factory replay over synthetic wire, with no financial book."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engineering.pons_history.fixtures import Tape
from meme_machine.lanes.pons.pons_historical import Preparation,PLAN
from meme_machine.lanes.pons.pons_history import PonsHistory
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
from meme_machine.lanes.pons.provider_admission import fingerprint
from meme_machine.runtime.pons_economic_cohort import PonsEconomicCohorts
from meme_machine.runtime.journal import canonical,digest
from tests.test_pons_dense_v4_receipts import ENDPOINT


class PonsFactoryCensusTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.tape=Tape();self.tape.provider_fingerprint=fingerprint(ENDPOINT)
        self.history=PonsHistory(Path(temporary.name)/'native.sqlite',policy=POLICY_HASH)
        self.addCleanup(self.history.close)
        self.prep=Preparation(self.history,self.tape.provider,
            clock=lambda:int(self.tape.header(self.tape.top)['timestamp'],16)+1)
        self.runtime=Runtime.__new__(Runtime);self.runtime.history=self.history
        self.runtime.economic_cohorts=None

    def complete(self):
        self.prep.begin()
        for _ in range(40):
            if 'first' in self.history.get_meta(PLAN):break
            self.prep.boundary_step()
        for _ in range(100):
            p=self.history.get_meta(PLAN)
            if self.prep._frontier('population',p['first'],p['anchor'])['block']==self.tape.top:break
            self.prep.discover_step()
        for _ in range(100):
            if not self.history.pending_graduations():break
            self.prep.authenticate_step()
        for token in self.tape.tokens:
            for _ in range(100):
                row=self.history.get(token)
                if row['block']>=self.tape.top:break
                self.prep.history_step(self.runtime,token)
        self.assertTrue(self.prep.readiness()['ready'])

    def attach(self):
        meter=PonsEconomicCohorts('synthetic-factory-census',ENDPOINT)
        self.history.economic_cohorts=meter
        return meter

    def test_actual_resume_complete_domain_preserves_original_sql_and_provider_calls(self):
        self.complete();outputs=[];methods=[];sql=[]
        usage=self.history.get_meta('pons_historical_usage')
        for enabled in (False,True):
            self.history.set_meta('pons_historical_usage',usage)
            meter=self.attach() if enabled else None
            trace=[];self.history.db.set_trace_callback(trace.append);self.tape.request_log=[]
            outputs.append(self.prep.resume())
            self.history.db.set_trace_callback(None);sql.append(trace);methods.append(deepcopy(self.tape.request_log))
            if enabled:
                result=meter.snapshot()['factory_domain']
                self.assertEqual(result['state'],'OBSERVED',result)
                self.assertTrue(result['source_complete']);self.assertEqual(result['graduations'],2)
                self.assertEqual(result['through_hash'],self.tape.header(self.tape.top)['hash'])
                self.assertEqual(result['consumer_completion'],'UNESTABLISHED')
                self.assertEqual(meter.snapshot()['completed_cohorts'],0)
        self.assertEqual(outputs[0],outputs[1]);self.assertEqual(sql[0],sql[1]);self.assertEqual(methods[0],methods[1])

    def test_forward_ready_is_not_historical_domain(self):
        prep=Preparation(self.history,self.tape.provider,forward_only=True)
        prep.begin();prep.discover_step();meter=self.attach()
        self.assertTrue(prep.resume()['ready'])
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def test_native_incomplete_candidate_skips_resolution_and_cannot_pass(self):
        self.complete();row=self.history.get(self.tape.tokens[0]);row.update(complete=False,recovery='native-pending')
        self.history.save(row);meter=self.attach();self.assertFalse(self.prep.resume()['ready'])
        result=meter.snapshot()['factory_domain'];self.assertFalse(result['source_complete'])
        self.assertTrue(result['acquisition_complete']);self.assertEqual(result['graduation_resolution'],'NOT_EVALUATED')

    def test_omitted_whole_range_hook_cannot_fake_complete(self):
        self.complete();meter=self.attach()
        with patch('meme_machine.runtime.pons_factory_census._Replay.range'):
            self.assertTrue(self.prep.resume()['ready'])
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def test_omitted_graduation_hook_cannot_fake_resolution(self):
        self.complete();meter=self.attach()
        with patch('meme_machine.runtime.pons_factory_census._Replay.graduation'):
            self.assertTrue(self.prep.resume()['ready'])
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def test_omitted_empty_reconciliation_cannot_fake_checked_zero(self):
        self.tape=Tape(candidates=0);self.tape.provider_fingerprint=fingerprint(ENDPOINT)
        self.prep.provider=self.tape.provider;self.complete();meter=self.attach()
        with patch('meme_machine.runtime.pons_factory_census._Replay.reconciliation'):
            self.assertTrue(self.prep.resume()['ready'])
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def test_retained_wrong_filter_refuses_measurement_without_changing_native_replay(self):
        self.complete();meter=self.attach()
        ident,body,checksum=self.history.db.execute("SELECT id,body,hash FROM pons_historical_ranges WHERE kind='population' LIMIT 1").fetchone()
        evidence=self.history._verified((body,checksum));evidence['query']['address']='0x'+'ab'*20
        self.history.db.execute('UPDATE pons_historical_ranges SET body=?,hash=? WHERE id=?',
            (canonical(evidence),digest(evidence),ident))
        self.assertTrue(self.prep.resume()['ready'])
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def test_failed_native_resume_invalidates_previous_witness_and_preserves_error(self):
        self.complete();meter=self.attach();self.prep.resume()
        self.assertTrue(meter.snapshot()['factory_domain']['source_complete'])
        self.tape.provider_fingerprint='changed-source'
        with self.assertRaisesRegex(Exception,'historical_provider_identity_changed'):self.prep.resume()
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def test_extension_invalidates_frozen_witness_before_native_work(self):
        self.complete();meter=self.attach();self.prep.resume()
        self.assertTrue(meter.snapshot()['factory_domain']['source_complete'])
        self.prep.extend(self.tape.header(self.tape.top))
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def test_observer_failure_cannot_fail_native_replay_or_write_extra_rows(self):
        self.complete();meter=self.attach()
        with patch('meme_machine.runtime.pons_factory_census._Replay.result',side_effect=RuntimeError('side-channel')):
            self.assertTrue(self.prep.resume()['ready'])
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def test_exact_prospective_seven_day_equality_is_insufficient(self):
        self.complete();p=self.history.get_meta(PLAN)
        p.update(prospective=True,enrollment_at=p['cutoff']);self.history.set_meta(PLAN,p)
        meter=self.attach();self.assertFalse(self.prep.resume()['ready'])
        self.assertEqual(meter.snapshot()['factory_domain']['reason'],'PRE_ENROLLMENT_UNOBSERVED')

    def test_missing_native_disposition_cannot_be_inferred_from_candidate_presence(self):
        self.complete();self.history.db.execute('DELETE FROM meta WHERE key=?',
            ('pons_historical_identity:'+self.tape.tokens[0],))
        meter=self.attach();self.assertFalse(self.prep.resume()['ready'])
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def test_metadata_overflow_preserves_original_replay_and_returns_unknown(self):
        self.complete();meter=self.attach()
        with patch('meme_machine.runtime.pons_factory_census.MAX_EVENTS',1):
            self.assertTrue(self.prep.resume()['ready'])
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def test_foreign_transaction_cannot_publish_a_frozen_witness(self):
        self.complete();meter=self.attach();self.history.db.execute('BEGIN')
        try:
            self.assertTrue(self.prep.resume()['ready']);self.assertTrue(self.history.db.in_transaction)
            self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])
        finally:self.history.db.execute('ROLLBACK')

    def test_nonblocking_observer_contention_cannot_republish_previous_positive(self):
        self.complete();meter=self.attach();self.prep.resume()
        self.assertTrue(meter.snapshot()['factory_domain']['source_complete'])
        meter.factory.lock.acquire()
        try:self.assertTrue(self.prep.resume()['ready'])
        finally:meter.factory.lock.release()
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def test_unresolved_graduations_never_accept_arbitrary_retained_disposition(self):
        self.complete();key='pons_historical_identity:'+self.tape.tokens[0]
        disposition=self.history.get_meta(key);disposition['disposition']='invented_terminal'
        self.history.set_meta(key,disposition);meter=self.attach()
        self.assertTrue(self.prep.resume()['ready'])
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def forged_allowed_terminal(self,terminal):
        self.complete();token=self.tape.tokens[0];key='pons_historical_identity:'+token
        disposition=self.history.get_meta(key);disposition['disposition']=terminal
        self.history.set_meta(key,disposition)
        self.history.db.execute('DELETE FROM candidates WHERE id=?',(token,))
        meter=self.attach();self.assertTrue(self.prep.resume()['ready'])
        self.assertFalse(meter.snapshot()['factory_domain']['source_complete'])

    def test_allowed_structural_label_cannot_hide_native_quote_missing_candidate(self):
        self.forged_allowed_terminal('non_native_quote')

    def test_allowed_horizon_label_cannot_hide_still_eligible_missing_candidate(self):
        self.forged_allowed_terminal('strategy_horizon_expired')
