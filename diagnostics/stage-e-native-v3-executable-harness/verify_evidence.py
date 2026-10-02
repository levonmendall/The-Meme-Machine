"""Read-only future raw-evidence verifier. Cannot launch A, B or C."""
import argparse
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'harness'))
from core import ASSEMBLY, S, T, canonical, file_sha, read, relative, require, sha, workload
from attest import signed_document
from binding import infrastructure_identity
from ledger import Ledger, trial_matrix
from preserve import verify_inventory
from verify import verify_trial, verify_observer


def verify_campaign(folder, owner_key, allocation_key):
    folder=Path(folder).resolve()
    verify_inventory(folder,name='CAMPAIGN_INVENTORY.json')
    d=read(folder/'DECLARATION.json')
    require(d['execution_authorized'] is True and d['disposition']=='AUTHORIZED PAPER EXECUTION',
            'preview_has_no_native_acceptance')
    require(d['candidate_sha']==S and d['candidate_tree']==T and d['assembly_digest']==ASSEMBLY,
            'verifier_exact_candidate_identity')
    require(d['trials']==trial_matrix(d['campaign'],d['class_id']) and d['infrastructure']==infrastructure_identity(),
            'verifier_trial_or_executable_identity')
    require(d['workload_sha256']==sha(canonical(workload(d['class_id']))), 'verifier_contract_semantic_binding')
    signature=read(folder/'PUBLIC_AUTHORITY_RECEIPTS.json')
    permit=signed_document(relative(folder,signature['owner_permit_path']),owner_key,d['trust_keys']['owner_public_key_sha256'])
    require(permit['declaration_sha256']==signature['original_declaration_sha256']
            and permit['campaign']==d['campaign'] and permit['class_id']==d['class_id']
            and permit['workflow']==d['workflow'] and permit['executor_id']==d['executor']['executor_id']
            and permit['paper_only'] is True and permit['provider_authorized'] is False
            and permit['stage_f_authorized'] is False,'raw_owner_permit_binding')
    require(read(relative(folder,signature['original_declaration_path']))==d
            and file_sha(relative(folder,signature['original_declaration_path']))==signature['original_declaration_sha256'],
            'original_executable_declaration_bytes')
    allocation=signed_document(relative(folder,signature['allocation_document_path']),allocation_key,
                               d['trust_keys']['allocation_public_key_sha256'])
    require(allocation==d['allocation'], 'raw_authenticated_allocation_changed')
    capabilities = {r['original_path']:str(relative(folder,r['preserved_path'])) for r in signature['capability_files']}
    ledger=Ledger(folder/'LEDGER.jsonl')
    events=ledger.events()
    require([r['sequence'] for r in events if r['event']=='STARTED']==list(range(1,len(d['trials'])+1))
            and [r['sequence'] for r in events if r['event']=='COMPLETE_VALID']==list(range(1,len(d['trials'])+1))
            and not any(r['event'] in ('INVALID','STOPPED') for r in events), 'incomplete_or_consumed_invalid_campaign')
    trials=[verify_trial(folder/f't{r["sequence"]}',d,
                        declaration_sha256=signature['original_declaration_sha256'],allocation=allocation,
                        evidence_files=capabilities)
            for r in d['trials']]
    if d['class_id']=='B':
        a=d['prerequisites']['capacity']
        capacity=verify_trial(a['raw_trial'],read(a['declaration']),
                               declaration_sha256=a['declaration_sha256'],allocation=allocation)
        return verify_observer(trials,d,capacity)
    return trials[0]


def main():
    p=argparse.ArgumentParser();p.add_argument('--campaign',required=True)
    p.add_argument('--owner-public-key',required=True);p.add_argument('--allocation-public-key',required=True)
    args=p.parse_args()
    print(canonical(verify_campaign(args.campaign,args.owner_public_key,args.allocation_public_key)).decode())


if __name__=='__main__':main()
