import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from certification.stage_e_native_v2 import *
from certification.stage_e_native_v2.binding import (check_checkout,workflow_identity,verify_assembly)
from certification.stage_e_native_v2.contract import canonical, sha256
from certification.stage_e_native_v2.transport import verify_run,select_artifacts
from certification.stage_e_native_v2.verify import validate_raw,aggregate


def workflow():
    return dict(workflow_path='.github/workflows/stagee-native-qualification-v2.yml',
        resolved_workflow_sha='a'*40,reusable_workflow_path='.github/workflows/stagee-native-qualification-v2-reusable.yml',
        reusable_workflow_sha='a'*40,candidate_sha='a'*40,run_id='fixture-run',attempt=1,event='local_static_deterministic')


def raw_fixture():
    """Parser fixture only, deliberately incapable of qualifying a real assembly."""
    identity=dict(repository=REPOSITORY,candidate_sha='a'*40,candidate_tree='b'*40,
        contract_version=CONTRACT,cohort_version=COHORT,held_reader_version=HELD_READER,
        schema_version=SCHEMA_VERSION,evidence_schema=SCHEMA,plan_version=PLAN,plan_hash='c'*64,
        input_manifest_hash='d'*64,gate_map_hash='e'*64,workflow_identity=workflow(),
        environment_identity=dict(dependencies={'websockets':{'files':{}}},stdlib='/fixture-stdlib'),
        assembly_recipe='fixture-only',expected_trial_matrix=['preflight'])
    files={f'certification/stage_e_native_v2/{n}.py':dict(sha256='f'*64) for n in ('runner','binding')}
    manifest=dict(identity=identity,assembly_digest='0'*64,files=files)
    raw=dict(identity=dict(identity,assembly_digest=manifest['assembly_digest']),case_id='preflight',
        trial_id='preflight:unique-fixture',classification='STATIC',paper_only=True,
        canonical_authority=False,market_authority=False,passed=True,generation=None,payload={'preflight_only':True},
        errors=[],provider_attempts=[],runtime_origins=[dict(module='certification.stage_e_native_v2.'+n,
            origin='/fixture/source/certification/stage_e_native_v2/'+n+'.py',sha256='f'*64,category='assembled') for n in ('runner','binding')],
        assembly_before='0'*64,assembly_after='0'*64,children=[])
    child=copy.deepcopy(raw);child.update(case_id='origin-child',trial_id='origin-child:fixture-child',payload={'child_origin_probe':True,'foreign_dynamic_import_rejected':True})
    raw['children']=[child]
    return raw,manifest


class CheckoutBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.git('init','-q')
        (self.root/'module.py').write_text('VALUE=1\n');(self.root/'.gitignore').write_text('ignored/\n')
        self.git('add','.');self.git('commit','-qm','fixture candidate')
        self.sha=self.git('rev-parse','HEAD');self.tree=self.git('rev-parse','HEAD^{tree}')
    def tearDown(self):self.temp.cleanup()
    def git(self,*args):
        return subprocess.check_output(['git','-c','user.name=V2 fixture','-c','user.email=v2-fixture@example.invalid',
            '-c','core.hooksPath=/dev/null',*args],cwd=self.root,text=True).strip()
    def test_clean_exact_sha_accepted(self):self.assertIn('module.py',check_checkout(self.root,self.sha,self.tree))
    def test_equal_tree_different_commit_is_rejected(self):
        self.git('commit','--allow-empty','-qm','different commit equal tree')
        self.assertEqual(self.git('rev-parse','HEAD^{tree}'),self.tree)
        self.assertNotEqual(self.git('rev-parse','HEAD'),self.sha)
        with self.assertRaisesRegex(ValueError,'different_candidate_commit'):check_checkout(self.root,self.sha,self.tree)
    def test_foreign_sha_and_foreign_tree_rejected(self):
        with self.assertRaisesRegex(ValueError,'different_candidate_commit'):check_checkout(self.root,'f'*40,self.tree)
        with self.assertRaisesRegex(ValueError,'tree_mismatch'):check_checkout(self.root,self.sha,'f'*40)
    def test_dirty_tracked_and_staged_bytes_rejected(self):
        (self.root/'module.py').write_text('VALUE=2\n')
        with self.assertRaisesRegex(ValueError,'dirty_tracked'):check_checkout(self.root,self.sha,self.tree)
        self.git('add','module.py')
        with self.assertRaisesRegex(ValueError,'dirty_tracked'):check_checkout(self.root,self.sha,self.tree)
    def test_untracked_module_shadow_rejected(self):
        (self.root/'shadow.py').write_text('raise RuntimeError()\n')
        with self.assertRaisesRegex(ValueError,'executable_shadow'):check_checkout(self.root,self.sha,self.tree)
    def test_ignored_module_shadow_rejected(self):
        (self.root/'ignored').mkdir();(self.root/'ignored/shadow.py').write_text('raise RuntimeError()\n')
        with self.assertRaisesRegex(ValueError,'executable_shadow'):check_checkout(self.root,self.sha,self.tree)
    def test_foreign_local_package_and_pth_rejected(self):
        (self.root/'foreign').mkdir();(self.root/'foreign/__init__.py').write_text('VALUE=3\n')
        with self.assertRaisesRegex(ValueError,'executable_shadow'):check_checkout(self.root,self.sha,self.tree)


class EvidenceBindingTests(unittest.TestCase):
    def test_raw_identity_mutations_rejected(self):
        keys=['candidate_sha','candidate_tree','contract_version','schema_version','plan_hash','input_manifest_hash','assembly_digest','gate_map_hash']
        for key in keys:
            raw,manifest=raw_fixture();raw['identity'][key]='foreign'
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'identity'):validate_raw(raw,manifest,'preflight')
    def test_missing_identity_and_contradictory_success_rejected(self):
        raw,manifest=raw_fixture();raw.pop('identity')
        with self.assertRaisesRegex(ValueError,'schema'):validate_raw(raw,manifest,'preflight')
        raw,manifest=raw_fixture();raw['errors']=['failure']
        with self.assertRaisesRegex(ValueError,'contradictory'):validate_raw(raw,manifest,'preflight')
    def test_wrong_workflow_reusable_sha_event_and_attempt_rejected(self):
        for key,value in [('workflow_path','old.yml'),('reusable_workflow_sha','b'*40),('attempt',2),('event','push')]:
            row=workflow();row[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):workflow_identity(row,'a'*40)
    def test_same_sha_raw_different_assembly_and_runtime_origin_rejected(self):
        raw,manifest=raw_fixture();raw['assembly_after']='9'*64
        with self.assertRaisesRegex(ValueError,'before_and_after'):validate_raw(raw,manifest,'preflight')
        raw,manifest=raw_fixture();raw['runtime_origins'][0]['origin']='/root-checkout/certification/stage_e_native_v2/runner.py'
        with self.assertRaisesRegex(ValueError,'foreign_assembly_origin'):validate_raw(raw,manifest,'preflight')
    def test_attempted_provider_call_counts_as_failure(self):
        raw,manifest=raw_fixture();raw['provider_attempts']=['socket.connect']
        with self.assertRaisesRegex(ValueError,'attempted_calls'):validate_raw(raw,manifest,'preflight')
    def test_failed_attempt_is_preserved_and_cannot_be_a_pass(self):
        raw,manifest=raw_fixture();raw['passed']=False
        self.assertFalse(validate_raw(raw,manifest,'preflight',allow_failed=True))
        with self.assertRaisesRegex(ValueError,'failed_trial'):validate_raw(raw,manifest,'preflight')
    def test_missing_duplicate_wrong_attempt_and_replaced_artifact_rejected(self):
        raw,manifest=raw_fixture()
        with tempfile.TemporaryDirectory() as td,patch('certification.stage_e_native_v2.verify.verify_assembly',return_value=manifest):
            path=Path(td)/'raw.json';path.write_bytes(canonical(raw))
            inv={'preflight':dict(trial_id=raw['trial_id'],sha256=sha256(path.read_bytes()),candidate_sha='a'*40,
                assembly_digest='0'*64,run_id='fixture-run',attempt=1,generation=None)}
            self.assertTrue(aggregate(td,'0'*64,[str(path)],inv,Path(td)/'aggregate.json')['passed'])
            for paths in ([],[str(path),str(path)]):
                with self.assertRaisesRegex(ValueError,'missing_or_duplicate'):aggregate(td,'0'*64,paths,inv,Path(td)/'bad.json')
            for key,value in [('attempt',2),('sha256','wrong'),('generation','foreign'),('candidate_sha','b'*40)]:
                wrong=copy.deepcopy(inv);wrong['preflight'][key]=value
                with self.subTest(key=key),self.assertRaisesRegex(ValueError,'stale_or_replaced'):aggregate(td,'0'*64,[str(path)],wrong,Path(td)/'bad.json')
    def test_remote_workflow_api_identity_and_replacement_checks(self):
        run=dict(id=1,head_sha='a'*40,run_attempt=1,event='workflow_dispatch',path=workflow()['workflow_path'],
            referenced_workflows=[dict(sha='a'*40,path=REPOSITORY+'/'+workflow()['reusable_workflow_path']+'@'+('a'*40))])
        self.assertEqual(verify_run(run,candidate='a'*40,run_id=1,attempt=1)['candidate_sha'],'a'*40)
        run['referenced_workflows'][0]['sha']='b'*40
        with self.assertRaisesRegex(ValueError,'reusable_workflow_sha'):verify_run(run,candidate='a'*40,run_id=1,attempt=1)
        rows=[dict(name='native-v2-'+('a'*40)+'-1-1-'+suffix,id=i+1,digest='sha256:'+('b'*64),expired=False,
            workflow_run=dict(id=1,head_sha='a'*40)) for i,suffix in enumerate(['preflight','clock-contract-clock-contract_uuid'])]
        self.assertEqual(set(select_artifacts(rows,'a'*40,1,1,['clock-contract'])),{'preflight','clock-contract'})
        with self.assertRaisesRegex(ValueError,'duplicate'):select_artifacts(rows+rows[1:],'a'*40,1,1,['clock-contract'])
    def test_schema_rejects_duplicate_json_keys_and_nonfinite_numbers(self):
        from certification.stage_e_native_v2.contract import strict_json
        for data in ('{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}'):
            with self.subTest(data=data),self.assertRaises(ValueError):strict_json(data)


class AssemblyIntegrityTests(unittest.TestCase):
    def test_wrong_assembly_missing_and_drifted_content_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'source').mkdir();path=root/'source/module.py';path.write_text('VALUE=1\n');path.chmod(0o444)
            manifest=dict(version='fixture',identity={},files={'module.py':dict(sha256=sha256(path.read_bytes()),mode='100644')})
            digest=sha256(canonical(manifest));manifest['assembly_digest']=digest;(root/'assembly.json').write_bytes(canonical(manifest))
            with self.assertRaisesRegex(ValueError,'wrong_or_substituted'):verify_assembly(root,'f'*64)
            path.chmod(0o644);path.write_text('VALUE=2\n');path.chmod(0o444)
            with self.assertRaisesRegex(ValueError,'assembly_drift'):verify_assembly(root,digest)
            path.unlink()
            with self.assertRaisesRegex(ValueError,'added_or_missing'):verify_assembly(root,digest)


if __name__=='__main__':unittest.main()
