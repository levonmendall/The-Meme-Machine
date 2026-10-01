"""Witness parser fixtures carry no native or exact-assembly qualification credit."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from certification.stage_e_native_v2.contract import HERE, canonical, read, sha256
from certification.stage_e_native_v2.m1 import (WITNESS_VERSION, SCOPE, PROGRESS_SELECT,
    evidence_fields, witness_gates, validate_witness)
from certification.stage_e_native_v2.tests.test_binding import raw_fixture
from certification.stage_e_native_v2.verify import aggregate, validate_raw


def seal(payload):
    payload.update(evidence_fields(payload))
    payload['gates'] = witness_gates(payload)
    payload['passed'] = all(payload['gates'].values())
    return payload


def approved_sequence():
    """Read 2 interrupts; exactly one accounting retry reads the durable 512."""
    from meme_machine.solana_maintenance_state import MAX_SCOPES
    generation='parser-fixture-generation'
    decision=dict(generation=generation,sequence=1,side='archive')
    plan=[dict(identity=str(i),hash=sha256(str(i).encode())) for i in range(1000)]
    receipt=dict(name='f'*64+'.jsonl.gz',hash='f'*64,bytes=100)
    before=dict(pending=False,pending_identity=None,arbiter_failed=False,runtime_failure=None,
        hot=1288,progress=[512,512],committed_records=plan[:512],episodes=[['original',120]],
        open_transaction=False,receipt_remaining=488,receipt_remaining_identities=[r['identity'] for r in plan[512:]],
        receipt_hash=receipt['hash'],integrity='ok')
    reads=[dict(ordinal=i,purpose='initial_observation' if i==1 else 'completion_accounting',
        query_hash=sha256((PROGRESS_SELECT+'?').encode()),limit=MAX_SCOPES*2+3,
        pending=None if i==1 else decision,transaction_open=False,preemption_enabled=i!=3,
        status='interrupted' if i==2 else 'completed',sqlite_errorcode=9 if i==2 else None,
        owner_interrupt_flag=i==2,rows=[[SCOPE,'archive',1800000000,512,1800000000,512]] if i==3 else []) for i in (1,2,3)]
    call=dict(decision=decision,pending_before=decision,exact_pending_identity=True,read_ordinal=3,
        transaction_open=False,progress={SCOPE:512},record_progress={SCOPE:512},ledger=[512,512],
        returned=True,error=None,pending_after=None)
    after=copy.deepcopy(before)
    after.update(hot=800,progress=[1000,1000],committed_records=plan,receipt_remaining=0,
        receipt_remaining_identities=[],receipt_hash=None)
    return seal(dict(witness_version=WITNESS_VERSION,generation=generation,ledger_reads=reads,
        interruption_injections=[2],completion_accounting=[call],before=before,after=after,
        first_turn=dict(accepted=True,completed=True),urgent=dict(accepted=True,completed=True,error=None,result=1928),
        next_turn=dict(accepted=True,completed=True,error=None,result=dict(side='retirement'),
            event=dict(sequence=2,generation=generation,selected='archive',completion='completed',durable_records={SCOPE:488})),first_error='EvidenceUnavailable:evidence_background_yield',
        second_error=None,seed_records=1928,input_plan=plan,archive_receipt=receipt,
        durable_archive_hash=receipt['hash'],original_thresholds=True,repair_applied=False,material_executions=0))


def raw_m1(payload):
    raw,manifest=raw_fixture()
    manifest['identity']['expected_trial_matrix']=['m1-completion']
    raw['identity']['expected_trial_matrix']=['m1-completion']
    raw['children'][0]['identity']['expected_trial_matrix']=['m1-completion']
    raw.update(case_id='m1-completion',trial_id='m1-completion:parser-fixture',
        classification='DETERMINISTIC_BOUNDED',payload=payload,generation=payload['generation'],passed=payload['passed'])
    return raw,manifest


class M1WitnessTests(unittest.TestCase):
    def reject(self,payload):
        seal(payload)
        self.assertFalse(validate_witness(payload))
        raw,manifest=raw_m1(payload)
        self.assertFalse(validate_raw(raw,manifest,'m1-completion',allow_failed=True))
        # Merely asserting success cannot override any independently derived gate.
        payload['passed']=True;payload['gates']={k:True for k in payload['gates']};raw['passed']=True
        with self.assertRaisesRegex(ValueError,'m1_'):
            validate_raw(raw,manifest,'m1-completion',allow_failed=True)

    def test_approved_read_two_interruption_and_exactly_one_retry_accepted(self):
        payload=approved_sequence()
        self.assertTrue(validate_witness(payload))
        self.assertEqual((payload['interruption_injected_at_read'],payload['completion_read_count'],
            payload['bounded_completion_retry_count'],payload['retry_read_ordinal']),(2,3,1,3))
        raw,manifest=raw_m1(payload)
        self.assertTrue(validate_raw(raw,manifest,'m1-completion'))

    def test_interruption_on_read_one_rejected(self):
        p=approved_sequence();p['interruption_injections']=[1]
        p['ledger_reads'][0].update(status='interrupted',sqlite_errorcode=9,owner_interrupt_flag=True)
        p['ledger_reads'][1].update(status='completed',sqlite_errorcode=None,owner_interrupt_flag=False)
        self.reject(p)

    def test_interruption_on_read_three_rejected(self):
        p=approved_sequence();p['interruption_injections']=[3]
        p['ledger_reads'][1].update(status='completed',sqlite_errorcode=None,owner_interrupt_flag=False)
        p['ledger_reads'][2].update(status='interrupted',sqlite_errorcode=9,owner_interrupt_flag=True)
        self.reject(p)

    def test_no_real_interruption_rejected(self):
        p=approved_sequence();p['ledger_reads'][1].update(status='completed',sqlite_errorcode=None,owner_interrupt_flag=False)
        self.reject(p)

    def test_repaired_sequence_without_retry_rejected(self):
        p=approved_sequence();p['ledger_reads'].pop();self.reject(p)

    def test_two_or_more_retries_rejected(self):
        for extra in (1,2):
            with self.subTest(extra=extra):
                p=approved_sequence()
                for i in range(extra):
                    row=copy.deepcopy(p['ledger_reads'][2]);row['ordinal']=4+i;p['ledger_reads'].append(row)
                self.reject(p)

    def test_three_final_reads_without_read_two_injection_rejected(self):
        p=approved_sequence();p['interruption_injections']=[];self.reject(p)

    def test_retry_with_pending_decision_rejected(self):
        p=approved_sequence();p['before'].update(pending=True,pending_identity=p['ledger_reads'][1]['pending'])
        self.reject(p)

    def test_pending_clear_without_legitimate_accounting_rejected(self):
        p=approved_sequence();p['completion_accounting']=[];self.reject(p)

    def test_retry_duplicate_durable_progress_rejected(self):
        p=approved_sequence();p['after']['progress']=[1024,1024];self.reject(p)
        p=approved_sequence();p['completion_accounting'][0]['record_progress'][SCOPE]=1024;self.reject(p)

    def test_next_turn_receipt_progress_requires_new_committed_records(self):
        p=approved_sequence()
        self.assertTrue(validate_witness(p))
        self.assertEqual(p['before']['progress'],[512,512])
        self.assertEqual(p['after']['progress'],[1000,1000])
        self.assertEqual(p['after']['receipt_remaining'],0)
        p['next_turn']['event']['durable_records'][SCOPE]=512;self.reject(p)

    def test_urgent_request_never_completes_rejected(self):
        p=approved_sequence();p['urgent']['completed']=False;self.reject(p)

    def test_receipt_continuation_lost_rejected(self):
        p=approved_sequence();p['before']['receipt_remaining_identities'].pop();self.reject(p)

    def test_next_admission_unusable_rejected(self):
        p=approved_sequence();p['next_turn'].update(error='EvidenceUnavailable:maintenance_decision_in_flight',result=None)
        self.reject(p)

    def test_fabricated_decision_completed_rejected(self):
        p=approved_sequence();p['completion_accounting'][0]['returned']=False
        p['gates']['decision_completed']=True
        with self.assertRaisesRegex(ValueError,'m1_fabricated_gate'):validate_witness(p)

    def test_fabricated_next_admission_usable_rejected(self):
        p=approved_sequence();p['next_turn']['completed']=False
        p['gates']['next_admission_usable']=True
        with self.assertRaisesRegex(ValueError,'m1_fabricated_gate'):validate_witness(p)

    def test_retry_does_not_inject_second_urgent_request(self):
        p=approved_sequence();p['interruption_injections']=[2,3];self.reject(p)

    def test_wrong_sqlite_error_or_nonaccounting_read_rejected(self):
        for field,value in [('sqlite_errorcode',1),('owner_interrupt_flag',False),('purpose','initial_observation')]:
            p=approved_sequence();p['ledger_reads'][1][field]=value;self.reject(p)

    def test_unrepaired_negative_keeps_read_two_and_zero_retry(self):
        p=approved_sequence();p['ledger_reads'].pop();p['completion_accounting']=[]
        decision=p['ledger_reads'][1]['pending']
        p['before'].update(pending=True,pending_identity=decision)
        p['after']=copy.deepcopy(p['before'])
        p['after'].update(pending=True,pending_identity=decision,arbiter_failed=True,
            runtime_failure='EvidenceUnavailable:maintenance_decision_in_flight')
        p['second_error']='EvidenceUnavailable:maintenance_decision_in_flight'
        p['next_turn'].update(error=p['second_error'],result=None,event=dict(sequence=None,generation=p['generation']))
        seal(p);self.assertFalse(validate_witness(p))
        self.assertTrue(p['interruption_observed']);self.assertEqual(p['completion_read_count'],2)
        self.assertEqual(p['bounded_completion_retry_count'],0)
        self.assertTrue(p['gates']['native_slice_committed']);self.assertFalse(p['gates']['decision_completed'])
        self.assertFalse(p['gates']['next_admission_usable'])

    def test_aggregation_preserves_negative_and_rejects_fabricated_success(self):
        p=approved_sequence();p['completion_accounting']=[];seal(p)
        raw,manifest=raw_m1(p)
        with tempfile.TemporaryDirectory() as td,patch('certification.stage_e_native_v2.verify.verify_assembly',return_value=manifest):
            path=Path(td)/'raw.json';path.write_bytes(canonical(raw))
            inv={'m1-completion':dict(trial_id=raw['trial_id'],sha256=sha256(path.read_bytes()),candidate_sha='a'*40,
                assembly_digest='0'*64,run_id='fixture-run',attempt=1,generation=p['generation'])}
            result=aggregate(td,'0'*64,[str(path)],inv,Path(td)/'aggregate.json')
            self.assertFalse(result['passed']);self.assertEqual(result['failed_trials'],['m1-completion'])
            p['passed']=True;p['gates']={k:True for k in p['gates']};raw['passed']=True
            path.write_bytes(canonical(raw));inv['m1-completion']['sha256']=sha256(path.read_bytes())
            with self.assertRaisesRegex(ValueError,'m1_fabricated_gate'):
                aggregate(td,'0'*64,[str(path)],inv,Path(td)/'fabricated.json')

    def test_schema_requires_ordinal_retry_and_accounting_evidence(self):
        from jsonschema import Draft202012Validator
        schema=read(HERE/'evidence-schema-v2.json')['$defs']['m1Witness']
        validator=Draft202012Validator(schema);p=approved_sequence();validator.validate(p)
        for field in ('ledger_reads','interruption_injected_at_read','interruption_observed',
                      'bounded_completion_retry_count','retry_read_ordinal','completion_accounting'):
            bad=copy.deepcopy(p);bad.pop(field)
            self.assertTrue(list(validator.iter_errors(bad)),field)


if __name__=='__main__':unittest.main()
