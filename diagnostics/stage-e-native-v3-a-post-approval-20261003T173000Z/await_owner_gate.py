"""Keep the exact first-attempt workflow binding while owner trust is pending."""
import os
import time
import urllib.error

def await_owner(c):
    c.RESULT.update(c.core.read(c.OUTPUT/'FINAL_RESULT.json'))
    c.core.require(c.RESULT.get('owner_signing_candidate_ready') is True,'incomplete_owner_signing_candidate')
    handoff=c.core.read(c.OUTPUT/'OWNER_SIGNING_HANDOFF.json')
    d=c.core.read(c.OUTPUT/'A_DECLARATION_FOR_VERIFIER.json')
    c.core.require(c.core.file_sha(c.OUTPUT/'A_DECLARATION_FOR_VERIFIER.json')==handoff['declaration_sha256'],'frozen_declaration_changed')
    c.save('OWNER_HANDOFF_WAITING.json',dict(status='WAITING_FOR_CONSOLIDATED_OWNER_SIGNING_HANDOFF',declaration_sha256=handoff['declaration_sha256'],latest_owner_handoff_utc_ns=handoff['latest_owner_handoff_utc_ns'],A_slots_consumed=0,source_frames_released=0))
    url='https://raw.githubusercontent.com/levonmendall/The-Meme-Machine/preflight/native-v3-a-owner-permit-ready-20261003T173000Z/OWNER_PERMIT_READY.json'
    while time.time_ns()<handoff['latest_owner_handoff_utc_ns']:
        try:
            ready=c.json.loads(c.read_public(url+'?fresh='+str(time.time_ns())))
        except urllib.error.HTTPError as exc:
            if exc.code!=404:raise
            time.sleep(5)
            continue
        c.core.require(ready['owner_public_key_sha256']==handoff['required_owner_public_key_sha256'] and ready['declaration_sha256']==handoff['declaration_sha256'],'owner_ready_wrong_exact_candidate')
        c.core.require(ready['explicit_owner_role_approval_received'] is True and ready['allocation_key_not_substituted'] is True,'owner_role_not_established')
        role=c.read_public(ready['owner_role_approval_immutable_url'])
        c.core.require(c.core.sha(role)==ready['owner_role_approval_artifact_sha256'],'owner_trust_provenance_changed')
        c.preserve_bytes('OWNER_EXECUTION_TRUST_ROLE_APPROVAL.json',role)
        signed=c.read_public(ready['owner_permit_immutable_url'])
        c.core.require(c.core.sha(signed)==ready['owner_permit_sha256'],'exact_owner_permit_download_changed')
        c.preserve_bytes('OWNER_PERMIT.json',signed)
        from declaration import authorize
        authorize(c.OUTPUT/'A_DECLARATION_FOR_VERIFIER.json',c.OUTPUT/'OWNER_PERMIT.json',c.OUTPUT/'PROPOSED_OWNER_EXECUTION_PUBLIC_KEY.pem',kind='A')
        c.approved_identity()
        c.binding.candidate_integrity(d['paths']['candidate_checkout'])
        c.binding.verify_assembly(d['paths']['assembly'])
        runtime=c.binding.runtime_identity(c.Path(d['paths']['assembly'])/'source')
        c.core.require(runtime==d['environment']['runtime_dependency_identities'],'runtime_changed_since_candidate_freeze')
        allocation=c.attest.signed_document(d['paths']['allocation_document'],d['paths']['allocation_public_key'],d['trust_keys']['allocation_public_key_sha256'])
        c.core.require(allocation==d['allocation'],'frozen_signed_allocation_changed')
        sample=c.attest.inspect(d['paths']['storage_paths'],os.getpid())
        c.core.require(not c.attest.admission_errors(sample,allocation,d['storage_bounds'],runtime),'fresh_owner_gate_resource_refusal')
        reserve=c.attest.reserve_storage(sample,d['storage_bounds'])
        import tape
        proof=tape.validate_existing(d['paths']['tape'],d['paths']['frame_inventory'],kind='A')
        c.save('PREFLIGHT_PASS.json',dict(STAGE_E_NATIVE_V3_A_PREFLIGHT='PASS',declaration_sha256=handoff['declaration_sha256'],owner_signature_verified=True,owner_trust_role_provenance=ready,resource_snapshot=sample,storage_reservation=reserve,tape_proof=proof,independent_approval=c.core.read(c.OUTPUT/'INDEPENDENT_APPROVAL_BINDING.json')))
        c.save('STAGE_A_ADMISSION_PASS_BOUNDARY.json',dict(Stage_A_admitted=True,admitted_utc_ns=time.time_ns(),A_trials_started=0,A_slots_consumed=0,source_frames_released=0))
        c.RESULT.update(status='STAGE_E_NATIVE_V3_A_PREFLIGHT_PASS',Stage_A_admitted=True)
        print(c.json.dumps(dict(STAGE_E_NATIVE_V3_A_PREFLIGHT='PASS',Stage_A_admitted=True)),flush=True)
        campaign=c.run.execute(c.OUTPUT/'A_DECLARATION_FOR_VERIFIER.json',c.OUTPUT/'OWNER_PERMIT.json',c.OUTPUT/'PROPOSED_OWNER_EXECUTION_PUBLIC_KEY.pem',kind='A')
        c.save('STAGE_A_EXECUTION_RETURN.json',dict(campaign=str(campaign),verifier_result=c.core.read(campaign/'VERIFICATION.json'),no_B_C_F_execution=True))
        return
    c.RESULT.update(status='STAGE_E_NATIVE_V3_A_PREFLIGHT_BLOCKED',first_exact_unresolved_blocker='owner_signing_handoff_window_expired',Stage_A_admitted=False,A_slots_consumed=0,A_trials_started=0,source_frames_released=0)
