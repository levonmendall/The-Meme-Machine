"""Deterministic counterfactual tests. Fixtures cannot authorize any campaign."""
from copy import deepcopy
import base64
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from frozen import *
from model import (declaration_template, validate_template, skeleton, validate_skeleton,
                   a_slot, require_a_slot, A_FIELDS, PRESERVED)
from ingestion import check_declaration, equal_runtime, verify_bound_B_preview, ingest_campaign, reject_asserted_state
from preservation import (stage_transport, readback_manifest, validate_transport,
                          preserve_fixture_or_evidence, snapshot_tree, MANIFEST, publish_transport)
from preservation import readback_github
from preserve import seal, verify_inventory, persist
from qualification import generate, evaluate_gate, historical_seal
from retained import transcript, source_test_inventory
from package import seal_package, verify_package
from shared_inputs import (template as shared_template, validate_receipts, check_stat, artifact,
                           published_capabilities, AWAITING)
from storage import calculate, feasibility, PARAMETERS, TAPE, HEADROOM, budget_template
from verify import observer_arithmetic, stress_member_result


class Templates(unittest.TestCase):
    def test_exact_six_template_order_and_no_reservation(self):
        d = declaration_template('B')
        self.assertEqual([t['mode'] for t in d['trials']], ['baseline','observed','observed','baseline','baseline','observed'])
        self.assertEqual(len({t['trial_id'] for t in d['trials']}), 6)
        self.assertFalse(d['actual_slots_reserved']); self.assertFalse(d['execution_authorized'])
        self.assertEqual(d['source_frames_released'], 0)

    def test_complete_frozen_B_and_C_match_approved_workloads(self):
        for kind in ('B','C'):
            d = declaration_template(kind); self.assertTrue(validate_template(d, kind))
            self.assertEqual(d['complete_workload'], workload(kind))
            self.assertEqual(d['envelope']['allocated_vcpu'], 2)
            self.assertEqual(d['envelope']['ram_bytes'], 8*1024**3)

    def test_C_exact_synthetic_contention(self):
        d=declaration_template('C'); s=d['complete_workload']['artificial_contention']
        self.assertEqual(s['source_pause_frames'],[800,1400]); self.assertEqual(s['source_pause_seconds'],8)
        self.assertEqual(s['held_reader_injected_sleeps_seconds'],[1.25,.1])
        self.assertEqual(s['completed_tail_injected_delay_seconds'],.75)
        self.assertEqual(d['acceptance_credit'],dict(A=False,B=False,C=False))

    def test_unresolved_A_admission_fails_closed(self):
        with self.assertRaisesRegex(ValueError,UNRESOLVED_A):require_a_slot(a_slot())
        with self.assertRaisesRegex(ValueError,UNRESOLVED_A):
            verify_bound_B_preview(declaration_template('B'),owner_key=None,allocation_key=None)

    def test_inject_fake_A_prerequisite(self):
        d=declaration_template('B')
        d['A_prerequisite_slot']=dict(state='VERIFIED_COMPLETE_A_CAPACITY_PACKAGE',bindings={})
        with self.assertRaisesRegex(ValueError,'missing_A_prerequisite'):
            verify_bound_B_preview(d,owner_key=None,allocation_key=None)

    def test_fake_A_with_complete_typed_assertions_still_requires_raw(self):
        d=declaration_template('B')
        d['A_prerequisite_slot']=dict(state='VERIFIED_COMPLETE_A_CAPACITY_PACKAGE',bindings={
            k:dict(state='BOUND_FROM_REVERIFIED_RAW_A',expected_type=v,value='FAKE_UNIT_NOT_AUTHORITY') for k,v in A_FIELDS.items()})
        d['prerequisites']['capacity']={'declaration':'/no-such-UNIT-file','declaration_sha256':'0'*64}
        with self.assertRaises((ValueError,OSError,KeyError)):
            verify_bound_B_preview(d,owner_key=None,allocation_key=None)

    def test_all_47_unsatisfied_and_no_historical_auto_PASS(self):
        d=skeleton(); self.assertEqual(len(d['gates']),47)
        self.assertEqual([g['name'] for g in d['gates']],contract_file('contract.json')['required_gates'])
        self.assertTrue(all(g['state']==UNSATISFIED and g['evidence']==[] for g in d['gates']))

    def test_mark_gate_PASS_without_evidence(self):
        d=skeleton(); d['gates'][0]['state']='PASS'
        with self.assertRaisesRegex(ValueError,'manually_asserted_PASS'):generate({},owner_key=None,allocation_key=None,initial_skeleton=d)

    def test_remove_one_required_v3_gate(self):
        d=skeleton();d['gates'].pop()
        with self.assertRaises(ValueError):validate_skeleton(d)

    def test_duplicate_required_gate(self):
        d=skeleton();d['gates'][-1]=deepcopy(d['gates'][0])
        with self.assertRaises(ValueError):validate_skeleton(d)

    def test_every_gate_has_implemented_missing_evidence_predicate(self):
        for g in skeleton()['gates']:
            self.assertFalse(evaluate_gate(g['name'],{},None,None),g['name'])

    def test_empty_final_decision_cannot_be_GREEN(self):
        d=generate({},owner_key=None,allocation_key=None)
        self.assertEqual(d['disposition'],'STAGE_E_NATIVE_V3_QUALIFICATION_BLOCKED')
        self.assertEqual(d['stage_e'],'RED');self.assertEqual(d['stage_f'],'NOT STARTED')
        self.assertEqual(d['unresolved_gate_count'],47)

    def test_manual_results_not_campaign_references(self):
        for field in ('passed','gates','gate_states','stage_e'):
            with self.assertRaisesRegex(ValueError,'manually_asserted_PASS'):reject_asserted_state({field:True})

    def test_native_entrypoints_and_dispatch_never_imported(self):
        import sys
        self.assertFalse(any(n in sys.modules for n in ('run','production','stress','worker','member','trial')))


class DeclarationRejections(unittest.TestCase):
    def counterfactual(self, kind='B'):
        # UNIT dictionary only. No signature/permit/ledger exists and it cannot
        # pass campaign verification or authorize().
        d=declaration_template(kind);d.update(execution_authorized=True,disposition='AUTHORIZED PAPER EXECUTION')
        return d

    def test_reorder_B_trials(self):
        d=self.counterfactual();d['trials'][0],d['trials'][1]=d['trials'][1],d['trials'][0]
        with self.assertRaisesRegex(ValueError,'wrong_order'):check_declaration(d,'B')

    def test_duplicate_B_trial(self):
        d=self.counterfactual();d['trials'][1]=deepcopy(d['trials'][0])
        with self.assertRaisesRegex(ValueError,'duplicate_trial'):check_declaration(d,'B')

    def test_reuse_v2_ID(self):
        d=self.counterfactual();d['trials'][0]['trial_id']=contract_file('historical_observer_seal.json')['all_old_trial_ids_forbidden'][0]
        with self.assertRaisesRegex(ValueError,'v2_reuse'):check_declaration(d,'B')

    def test_change_S_T_assembly_contract_executable(self):
        for key in ('candidate_sha','candidate_tree','assembly_digest','contract_commit','executable_commit'):
            d=self.counterfactual();d[key]='WRONG_UNIT_IDENTITY'
            with self.assertRaises(ValueError,msg=key):check_declaration(d,'B')

    def test_swap_tape_identity(self):
        d=self.counterfactual();d['tape_binding']['physical_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'changed_tape'):check_declaration(d,'B')

    def test_preview_cannot_earn_campaign_credit(self):
        with self.assertRaisesRegex(ValueError,'PREVIEW'):check_declaration(declaration_template('B'),'B')

    def test_warmup_retry_replacement_rejected(self):
        for key in ('warmups','retries','replacements'):
            d=self.counterfactual();d[key]=1
            with self.assertRaisesRegex(ValueError,'forbidden'):check_declaration(d,'B')

    def test_changed_environment_executor_boot_rejected(self):
        d=self.counterfactual();d['environment']={'UNIT':1};d['environment_sha256']=sha(canonical(d['environment']))
        d['executor']={'executor_id':'UNIT','hostname':'UNIT','boot_id':'UNIT'}
        for key in ('environment_sha256','executor_id','hostname','boot_id'):
            changed=deepcopy(d)
            if key=='environment_sha256':changed[key]='0'*64
            else:changed['executor'][key]='changed-UNIT'
            with self.assertRaisesRegex(ValueError,'changed_environment'):equal_runtime(d,changed)

    def test_omit_A_preservation_receipt(self):
        with self.assertRaisesRegex(ValueError,'schema'):
            ingest_campaign({'sealed_campaign':'UNIT_FAKE_A'},kind='A',owner_key=None,allocation_key=None)

    def test_fabricate_C_safety_credit(self):
        row=dict(candidate_sha=S,kind='C',mandatory_native_safety_pass=True,capacity_credit=True,passed=True)
        result=stress_member_result(row)
        self.assertFalse(result['mandatory_native_safety_pass']);self.assertFalse(result['capacity_credit'])

    def test_C_cannot_be_ingested_as_A(self):
        with self.assertRaisesRegex(ValueError,'wrong_candidate'):check_declaration(self.counterfactual('C'),'A')


class ObserverArithmetic(unittest.TestCase):
    def pairs(self, observed=1004):
        return [dict(pair_id=f'UNIT-p{i}',baseline_ns=1000,observed_ns=observed,valid=True,
                     same_workload_hash='production-equivalent-full-cohort-v3') for i in range(3)]

    def test_summed_integer_cost_below_one_percent(self):
        r=observer_arithmetic(self.pairs());self.assertEqual(r['numerator_ns'],12);self.assertEqual(r['denominator_ns'],3000)

    def test_exactly_one_percent_fails(self):
        with self.assertRaisesRegex(ValueError,'strictly_below'):observer_arithmetic(self.pairs(1010))

    def test_observed_below_baseline_fails(self):
        with self.assertRaises(ValueError):observer_arithmetic(self.pairs(999))

    def test_incomplete_pair_fails(self):
        with self.assertRaises(ValueError):observer_arithmetic(self.pairs()[:2])

    def test_boolean_float_nan_durations_fail(self):
        for value in (True,1000.0,float('nan')):
            pairs=self.pairs();pairs[0]['baseline_ns']=value
            with self.assertRaises(ValueError):observer_arithmetic(pairs)

    def test_no_averaging_or_subtraction(self):
        pairs=self.pairs();pairs[0]['subtract_cost_ns']=100
        with self.assertRaises(ValueError):observer_arithmetic(pairs)


class Preservation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def fixture(self):
        source=self.root/'fixture';source.mkdir()
        (source/'UNIT_NOT_CAMPAIGN.bin').write_bytes(b'UNIT deterministic evidence; no source frames\x00')
        (source/'zero.bin').write_bytes(b'')
        seal(source);return source

    def staged(self):
        s=self.fixture();stage=self.root/'transport'
        m=stage_transport(s,stage,class_id='PREFLIGHT',campaign='UNIT-NOT-A-TRIAL',declaration_sha256='a'*64,inventory_name='RAW_INVENTORY.json')
        return s,stage,m

    def readback(self, stage, m, files=None):
        return readback_manifest((stage/MANIFEST).read_bytes(),lambda p:(stage/p).read_bytes(),
            list(validate_transport(m)) if files is None else files,self.root/'readback',
            expected_manifest_sha256=file_sha(stage/MANIFEST))

    def test_fsync_files_parent_directories_and_redundant_immutable_copy(self):
        source=self.fixture();(source/'RAW_INVENTORY.json').unlink()
        r=preserve_fixture_or_evidence(source,self.root/'redundant')
        self.assertTrue(r['files_fsynced']);self.assertTrue(r['parent_directories_fsynced'])
        self.assertTrue(r['local_copy_retained']);self.assertTrue(r['redundant_files_immutable'])
        self.assertFalse((self.root/'redundant/UNIT_NOT_CAMPAIGN.bin').stat().st_mode & 0o222)
        self.assertEqual(snapshot_tree(source),snapshot_tree(self.root/'redundant'))

    def test_readback_all_bytes_and_independent_sha(self):
        source,stage,m=self.staged();r=self.readback(stage,m)
        self.assertTrue(r['complete']);self.assertFalse(r['acceptance_credit'])
        self.assertEqual(snapshot_tree(source),snapshot_tree(self.root/'readback'))

    def test_publish_partial_evidence(self):
        source,stage,m=self.staged();files=list(validate_transport(m));files.remove(next(p for p in files if p!=MANIFEST))
        with self.assertRaisesRegex(ValueError,'partial_torn'):self.readback(stage,m,files)

    def test_modify_package_after_manifest(self):
        source,stage,m=self.staged();(source/'UNIT_NOT_CAMPAIGN.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'inventory_mismatch'):verify_inventory(source)

    def test_modify_remote_bytes(self):
        source,stage,m=self.staged();chunk=m['source_artifacts'][0]['chunks'][0]['path']
        (stage/chunk).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'remote_chunk'):self.readback(stage,m)

    def test_torn_manifest(self):
        source,stage,m=self.staged();data=(stage/MANIFEST).read_bytes()[:-1]
        with self.assertRaisesRegex(ValueError,'manifest_changed'):
            readback_manifest(data,lambda _:b'',[],self.root/'readback',expected_manifest_sha256=file_sha(stage/MANIFEST))

    def test_redundant_destination_is_exclusive(self):
        source=self.fixture();(source/'RAW_INVENTORY.json').unlink()
        preserve_fixture_or_evidence(source,self.root/'copy')
        with self.assertRaises((ValueError,FileExistsError)):preserve_fixture_or_evidence(source,self.root/'copy')

    def test_symlink_or_path_escape_rejected(self):
        source=self.fixture();(source/'escape').symlink_to('/etc/os-release')
        with self.assertRaises(ValueError):snapshot_tree(source)

    def test_publication_forbidden_branch_never_calls_API(self):
        source,stage,m=self.staged()
        def no_API(*args):self.fail('forbidden branch invoked API')
        for branch in ('main','fix/stage-e-native-v3-executable','preflight/A'):
            with self.assertRaisesRegex(ValueError,'fresh_evidence'):publish_transport(stage,branch,parent_commit=EXECUTABLE_COMMIT,api=no_API)

    def test_chunk_inventory_rejects_missing_or_duplicate_chunk(self):
        source,stage,m=self.staged();m['source_artifacts'][0]['chunks'].append(deepcopy(m['source_artifacts'][0]['chunks'][0]))
        with self.assertRaisesRegex(ValueError,'partial_transport'):validate_transport(m)

    def test_mock_GitHub_publication_and_independent_readback_roundtrip(self):
        source,stage,m=self.staged(); blobs={}; remote={}; refs={}; calls=[]
        def api(method,path,value=None):
            calls.append((method,path))
            if (method,path)==('POST','/git/blobs'):
                data=base64.b64decode(value['content'],validate=True)
                ident=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\x00'+data).hexdigest()
                blobs[ident]=data;return {'sha':ident}
            if (method,path)==('POST','/git/trees'):
                remote.update(sha='1'*40,tree=value['tree'],truncated=False);return {'sha':'1'*40}
            if (method,path)==('POST','/git/commits'):
                self.assertEqual(value['parents'],[EXECUTABLE_COMMIT]);return {'sha':'2'*40}
            if (method,path)==('POST','/git/refs'):
                if value['ref'] in refs:raise ValueError('exclusive_mock_ref_already_exists')
                refs[value['ref']]=value['sha'];return value
            if method=='GET' and path.startswith('/git/trees/'):return deepcopy(remote)
            if method=='GET' and path.startswith('/git/blobs/'):
                return dict(encoding='base64',content=base64.b64encode(blobs[path.rsplit('/',1)[-1]]).decode())
            self.fail('unapproved API call: '+method+' '+path)
        branch='diagnostics/stage-e-native-v3-evidence/UNIT-NOT-A-CAMPAIGN'
        publication=publish_transport(stage,branch,parent_commit=EXECUTABLE_COMMIT,api=api)
        receipt=readback_github(publication['commit'],self.root/'readback',
            expected_manifest_sha256=publication['manifest_sha256'],api=api)
        self.assertTrue(receipt['complete']);self.assertFalse(receipt['acceptance_credit'])
        self.assertEqual(snapshot_tree(source),snapshot_tree(self.root/'readback'))
        with self.assertRaisesRegex(ValueError,'already_exists'):
            publish_transport(stage,branch,parent_commit=EXECUTABLE_COMMIT,api=api)
        self.assertFalse(any('/actions' in path or method not in ('GET','POST') for method,path in calls))

    def test_staged_bytes_modified_after_manifest_rejected_before_any_API(self):
        source,stage,m=self.staged();chunk=m['source_artifacts'][0]['chunks'][0]['path']
        (stage/chunk).write_bytes(b'changed')
        def no_API(*args):self.fail('modified staged evidence invoked API')
        with self.assertRaisesRegex(ValueError,'modified_after_manifest'):
            publish_transport(stage,'diagnostics/stage-e-native-v3-evidence/UNIT',
                              parent_commit=EXECUTABLE_COMMIT,api=no_API)

    def test_chunk_boundary_and_empty_file_roundtrip(self):
        with patch('preservation.CHUNK_BYTES',64):
            source=self.fixture();(source/'RAW_INVENTORY.json').unlink()
            (source/'UNIT-large.bin').write_bytes(b'UNIT '*65);seal(source)
            stage=self.root/'transport'
            m=stage_transport(source,stage,class_id='FINAL',campaign='UNIT-NOT-QUALIFICATION',
                declaration_sha256='a'*64,inventory_name='RAW_INVENTORY.json')
            self.assertGreater(max(len(r['chunks']) for r in m['source_artifacts']),1)
            self.readback(stage,m);self.assertEqual(snapshot_tree(source),snapshot_tree(self.root/'readback'))

    def test_preparation_manifest_rejects_post_seal_changes_and_partial_files(self):
        package=self.root/'paper';package.mkdir();(package/'UNIT.txt').write_bytes(b'paper')
        seal_package(package);bound=file_sha(package/'package-manifest.json')
        self.assertTrue(verify_package(package,expected_manifest_sha256=bound)['verified'])
        (package/'UNIT.txt').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'modified_partial_or_extra'):
            verify_package(package,expected_manifest_sha256=bound)
        (package/'UNIT.txt').unlink()
        with self.assertRaisesRegex(ValueError,'modified_partial_or_extra'):
            verify_package(package,expected_manifest_sha256=bound)


class SharedAndStorage(unittest.TestCase):
    def test_physical_inputs_explicitly_deferred_and_not_PASS(self):
        d=shared_template();self.assertEqual(d['state'],AWAITING);self.assertFalse(d['verified'])
        self.assertTrue(all(r['state']==AWAITING and r['value'] is None for r in d['bindings'].values()))
        self.assertFalse(d['substitutes_execution_time_checks']);self.assertFalse(d['production_volume_accessed'])

    def test_deferred_physical_receipts_fail_closed(self):
        with self.assertRaisesRegex(ValueError,AWAITING):
            validate_receipts('/no-production-volume-access',{},expected_executor={},expected_environment_sha256='',budget_values={},allocation_key=None)

    def test_complete_stat_and_positive_inode_required(self):
        for row in ({},{'inode':1},{k:0 for k in ('device','inode','size','mtime_ns','ctime_ns','mode')}):
            with self.assertRaises(ValueError):check_stat(row)

    def test_manual_receipt_sha_assertion_needs_actual_bytes(self):
        with self.assertRaises((ValueError,OSError)):artifact('/no-physical-access',{'path':'fake','sha256':'0'*64})

    def test_signed_capabilities_resolved_only_to_published_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);file=root/'CAPABILITY.json';file.write_bytes(b'UNIT NOT RESOURCE EVIDENCE')
            allocation={'allocation_evidence':[dict(path='/no-production-access/CAPABILITY.json',sha256=file_sha(file))]}
            self.assertEqual(published_capabilities(root,allocation),
                             {'/no-production-access/CAPABILITY.json':str(file)})
            file.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'signed_capability_missing'):published_capabilities(root,allocation)

    def values(self):return {k:1024 for k in PARAMETERS}

    def test_storage_formula_counts_six_trials_copies_and_final_bundle(self):
        r=calculate(self.values());self.assertEqual(r['B_raw_bytes'],6*1024)
        self.assertEqual(r['B_redundant_bytes'],6*1024)
        self.assertEqual(r['C_one_raw_restart_failure_bytes'],4*1024)
        self.assertEqual(r['final_bundle_two_bytes'],2*r['final_bundle_one_bytes'])
        self.assertEqual(r['headroom_bytes'],HEADROOM);self.assertEqual(r['immutable_tape_bytes'],TAPE)
        self.assertFalse(r['actual_disk_reserved'])

    def test_final_ABC_set_exceeds_available_storage(self):
        r=feasibility(self.values(),[dict(path='UNIT',free_bytes=HEADROOM,total_bytes=100*1024**3)])
        self.assertFalse(r['fits_all_declared_filesystems']);self.assertGreater(r['shortfall_by_path']['UNIT'],0)

    def test_free_space_not_pooled_between_filesystems(self):
        r=calculate(self.values());bound=r['required_new_free_bytes']
        fs=[dict(path='UNIT1',free_bytes=bound//2,total_bytes=100*1024**3),dict(path='UNIT2',free_bytes=bound,total_bytes=100*1024**3)]
        self.assertFalse(feasibility(self.values(),fs)['fits_all_declared_filesystems'])

    def test_storage_missing_boolean_negative_float_fail_closed(self):
        for value in (-1,True,1.5,None):
            v=self.values();v['working_peak_bytes']=value
            with self.assertRaises(ValueError):calculate(v)
        with self.assertRaises(ValueError):calculate({})


class RawParsers(unittest.TestCase):
    def test_summary_PASS_without_full_transcript_rejected(self):
        with self.assertRaisesRegex(ValueError,'fabricated_PASS'):transcript(b'PASS\n',['test_m.C.test_x'])

    def test_test_transcript_verified_and_torn_skipped_rejected(self):
        good=b'test_x (test_m.C.test_x) ... ok\n\nRan 1 test in 0.001s\n\nOK\n'
        self.assertEqual(transcript(good,['test_m.C.test_x'])['tests'],1)
        for body in (good.replace(b' ... ok',b' ... skipped'),good.replace(b'Ran 1',b'Ran 2'),good.replace(b'OK\n',b'')):
            with self.assertRaises(ValueError):transcript(body,['test_m.C.test_x'])

    def test_static_test_inventory_executes_no_test_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test_m.py').write_text("raise RuntimeError('MUST NEVER IMPORT')\nclass C:\n def test_x(self): pass\n")
            self.assertEqual(source_test_inventory(p,['test_m']),['test_m.C.test_x'])

    def test_historical_seal_does_not_earn_observer_credit(self):
        r=historical_seal();self.assertEqual(r['outcome'],'OBSERVER_V2: INVALID_PAIR');self.assertEqual(r['verified_files'],159)


if __name__=='__main__':unittest.main(verbosity=2)
