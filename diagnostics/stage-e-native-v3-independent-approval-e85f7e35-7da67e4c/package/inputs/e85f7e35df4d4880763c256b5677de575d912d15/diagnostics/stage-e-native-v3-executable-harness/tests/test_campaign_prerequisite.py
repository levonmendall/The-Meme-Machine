"""Counterfactual campaign metadata only; signatures/native proof are mocked.

Every on-disk permit contains a nonauthorizing UNIT payload. No fixture can pass
authorize(), and neither controller execution nor any native runner is invoked.
"""
import ast
from copy import deepcopy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'harness'));sys.path.insert(0,str(ROOT))
import campaign
import verify_evidence
from core import S, T, file_sha, read, sha
from declaration import preview
from ledger import Ledger, fresh_campaign
from preserve import persist, seal, redundant_copy
from run import _finalize_campaign
from verify import OVERLOAD, verify_observer


class CampaignPrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.published = self.root/'published';self.published.mkdir()

    def fixture(self, *, kind='A', stopped=False, overload=False, identity_changed=False):
        name = fresh_campaign(kind)
        capability = self.root/(name+'-capability');capability.write_bytes(b'UNIT NOT ALLOCATION AUTHORITY')
        allocation = dict(allocation_evidence=[dict(path=str(capability),sha256=sha(capability.read_bytes()))],
                          unit_not_authenticated=True)
        d = preview(kind,name,executor=dict(executor_id='UNIT',boot_id='unit-boot',hostname='unit-host'),
            environment={'runtime_dependency_identities':{},'unit_not_admitted':True},
            workflow={'unit_not_dispatched':True},allocation=allocation,storage_bounds={},
            trust_keys={'owner_public_key_sha256':'unit-A-owner','allocation_public_key_sha256':'unit-A-allocation'},
            paths={'campaign_registry':str(self.root/'registry'),'durable_publication_root':str(self.published)})
        # Counterfactual verifier input only: the preserved signatures deliberately
        # remain invalid and nonauthorizing, so this is never executable authority.
        d.update(execution_authorized=True,disposition='AUTHORIZED PAPER EXECUTION')
        declared = self.root/(name+'-UNIT-UNSIGNED-declaration.json');persist(declared,d)
        digest = file_sha(declared)
        ledger = Ledger.create(self.root/'registry',kind,digest,name)
        folder = ledger.path.parent
        public = folder/'public-authority';public.mkdir()
        persist(folder/'DECLARATION.json',d);persist(public/'original-declaration.json',d)
        for file in ('owner-permit.json','allocation.json'):
            persist(public/file,dict(payload={'UNIT ONLY':True,'execution_authorized':False},signature_base64=''))
        (public/'CAPABILITY-0.bin').write_bytes(capability.read_bytes())
        persist(folder/'PUBLIC_AUTHORITY_RECEIPTS.json',dict(original_declaration_sha256=digest,
            owner_permit_path='public-authority/owner-permit.json',allocation_document_path='public-authority/allocation.json',
            original_declaration_path='public-authority/original-declaration.json',
            capability_files=[dict(original_path=str(capability),preserved_path='public-authority/CAPABILITY-0.bin')]))
        permit = dict(version='stage-e-native-v3-owner-execution-permit',declaration_sha256=digest,class_id=kind,
            campaign=name,workflow=d['workflow'],executor_id='UNIT',paper_only=True,provider_authorized=False,stage_f_authorized=False)
        trial = d['trials'][0]
        ledger.append('STARTED',1,dict(trial_id=trial['trial_id'],mode=trial['mode']))
        raw = folder/'t1';raw.mkdir();persist(raw/'UNIT_RAW_NO_FRAMES.json',{'source_frames_released':0})
        raw_hash = seal(raw)
        verification = dict(class_id=kind,native_verified=True,passed=True,candidate_sha=S,candidate_tree=T,
            environment_sha256=d['environment_sha256'],production_workload_sha256=d['production_workload_sha256'],
            declaration_sha256=digest,trial_id=trial['trial_id'],mode=trial['mode'],raw_inventory_sha256=raw_hash,
            safety_only=overload,capacity_credit=kind=='A',diagnostic_outcome='FAILED_DIAGNOSTIC' if overload else 'PASS',
            outcome=OVERLOAD if overload else 'COMPLETE_NATIVE_COHORT_PASS')
        copied = redundant_copy(raw,self.published/(name+'-t1'))
        persist(folder/'TRIAL-1-PRESERVATION.json',dict(copied,source=str(raw)))
        ledger.append('DIAGNOSTIC_OVERLOAD' if overload else 'COMPLETE_VALID',1,
                      dict(raw_inventory_sha256=raw_hash,verification=verification))
        if stopped:ledger.append('STOPPED',None,dict(reason='UNIT failed final preservation'))
        if identity_changed:
            path = folder/'IDENTITY.json';identity = read(path);identity['declaration_sha256'] = 'forged-unit'
            path.unlink();persist(path,identity)
        persist(folder/'VERIFICATION.json',verification)
        _finalize_campaign(folder,d,ledger,digest)
        receipt = folder.with_name(name+'.PRESERVATION.json')
        return dict(d=d,declared=declared,digest=digest,folder=folder,receipt=receipt,
                    verification=verification,permit=permit,allocation=allocation,ledger=ledger)

    def signatures(self, unit):
        def signed(path,key,expected_hash):
            if Path(path).name == 'owner-permit.json':
                self.assertEqual(expected_hash,unit['d']['trust_keys']['owner_public_key_sha256'])
                return unit['permit']
            self.assertEqual(expected_hash,unit['d']['trust_keys']['allocation_public_key_sha256'])
            return unit['allocation']
        return patch('campaign.signed_document',side_effect=signed)

    def verify(self, unit):
        with self.signatures(unit),patch('campaign.verify_trial',return_value=unit['verification']):
            return campaign.verify_campaign(unit['folder'],'UNIT TRUSTED OWNER','UNIT TRUSTED ALLOCATION',
                                             preservation_receipt=unit['receipt'])

    def B(self, unit):
        d = preview('B',fresh_campaign('B'),executor=unit['d']['executor'],environment=unit['d']['environment'],
                    workflow={},paths={},allocation={'unit_B_allocation_must_not_replace_A':True})
        d['prerequisites']['capacity'] = dict(declaration=str(unit['declared']),declaration_sha256=unit['digest'],
                        sealed_campaign=str(unit['folder']),preservation_receipt=str(unit['receipt']))
        return d

    def test_valid_metadata_protocol_requires_complete_sealed_authority_and_preservation(self):
        unit = self.fixture();verified = self.verify(unit)
        self.assertTrue(verified['campaign_verified']);self.assertTrue(verified['preservation_verified'])

    def test_raw_A_trial_pass_from_STOPPED_campaign_is_rejected(self):
        unit = self.fixture(stopped=True)
        with self.assertRaisesRegex(ValueError,'consumed_invalid_campaign'):self.verify(unit)

    def test_B_prerequisite_rejects_STOPPED_A_despite_mocked_passing_trial(self):
        unit = self.fixture(stopped=True);d = self.B(unit)
        with self.signatures(unit),patch('campaign.verify_trial',return_value=unit['verification']) as trial:
            with self.assertRaisesRegex(ValueError,'consumed_invalid_campaign'):
                campaign.verify_capacity_prerequisite(d,'UNIT OWNER','UNIT ALLOCATION')
            trial.assert_not_called()

    def test_B_uses_A_own_allocation_and_permit_in_complete_campaign(self):
        unit = self.fixture();d = self.B(unit)
        with self.signatures(unit),patch('campaign.verify_trial',return_value=unit['verification']) as trial:
            capacity = campaign.verify_capacity_prerequisite(d,'UNIT OWNER','UNIT ALLOCATION')
            self.assertEqual(trial.call_args.kwargs['allocation'],unit['allocation'])
            self.assertTrue(capacity['preservation_verified'])

    def test_changed_actual_A_declaration_bytes_fail_before_campaign_or_trial(self):
        unit = self.fixture();d = self.B(unit)
        unit['declared'].write_bytes(unit['declared'].read_bytes()+b' ')
        with patch('campaign.verify_campaign') as sealed:
            with self.assertRaisesRegex(ValueError,'declaration_changed'):
                campaign.verify_capacity_prerequisite(d,'UNIT OWNER','UNIT ALLOCATION')
            sealed.assert_not_called()

    def test_missing_or_wrong_A_owner_authority_fails_before_native_trial_verification(self):
        unit = self.fixture();unit['permit']['class_id'] = 'B'
        with self.assertRaisesRegex(ValueError,'raw_owner_permit_binding'):self.verify(unit)
        with patch('campaign.signed_document',side_effect=ValueError('unit missing signature')),\
             patch('campaign.verify_trial') as trial:
            with self.assertRaisesRegex(ValueError,'missing signature'):
                campaign.verify_campaign(unit['folder'],'unit','unit',preservation_receipt=unit['receipt'])
            trial.assert_not_called()

    def test_A_allocation_document_must_match_A_declared_allocation(self):
        unit = self.fixture();unit['allocation'] = dict(unit['allocation'],changed=True)
        with self.assertRaisesRegex(ValueError,'authenticated_allocation_changed'):self.verify(unit)

    def test_chain_and_inventory_cannot_authenticate_wrong_ledger_declaration(self):
        unit = self.fixture(identity_changed=True)
        with self.assertRaisesRegex(ValueError,'ledger_authority_binding'):self.verify(unit)

    def test_missing_successful_campaign_preservation_status_fails(self):
        unit = self.fixture();unit['receipt'].unlink()
        with self.assertRaises(FileNotFoundError):self.verify(unit)

    def test_self_asserted_copy_success_requires_actual_readback_bytes(self):
        unit = self.fixture()
        (self.published/(unit['d']['campaign']+'-campaign')/'VERIFICATION.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'inventory_mismatch'):self.verify(unit)

    def test_lost_trial_publication_cannot_be_hidden_by_final_campaign_copy(self):
        unit = self.fixture();shutil.rmtree(self.published/(unit['d']['campaign']+'-t1'))
        with self.assertRaises(FileNotFoundError):self.verify(unit)

    def test_B_bindings_are_checked_after_A_campaign_verification(self):
        unit = self.fixture();d = self.B(unit);d['environment_sha256'] = 'changed'
        with self.signatures(unit),patch('campaign.verify_trial',return_value=unit['verification']):
            with self.assertRaisesRegex(ValueError,'A_B_required_bindings_changed'):
                campaign.verify_capacity_prerequisite(d,'unit','unit')

    def test_C_safe_overload_ledger_is_accepted_only_after_full_campaign_verification(self):
        unit = self.fixture(kind='C',overload=True);verified = self.verify(unit)
        self.assertEqual(verified['outcome'],OVERLOAD)
        self.assertTrue(verified['safety_only']);self.assertFalse(verified['capacity_credit'])
        self.assertEqual(verified['diagnostic_outcome'],'FAILED_DIAGNOSTIC')

    def test_A_raw_verification_object_cannot_directly_satisfy_B(self):
        unit = self.fixture()
        with self.assertRaisesRegex(ValueError,'fresh_A_pass_required'):
            verify_observer([],self.B(unit),unit['verification'])

    def test_admission_and_retrospective_use_same_complete_campaign_prerequisite(self):
        controller = ast.parse((ROOT/'harness/run.py').read_bytes())
        calls = [n for n in ast.walk(controller) if isinstance(n,ast.Call) and
                 isinstance(n.func,ast.Name) and n.func.id == 'verify_capacity_prerequisite']
        self.assertEqual(len(calls),1)
        self.assertIs(verify_evidence.verify_campaign,campaign.verify_campaign)
