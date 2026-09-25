"""Read-only preservation gate before the repaired cohort may be dispatched."""
import argparse
import base64
from copy import deepcopy
import json
from pathlib import Path
import subprocess

from certification.journal import digest
from certification.prospective_program import GitHub,git,ROOT

PREDECESSOR_SHA='c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66'
PREDECESSOR_COHORT='prospective-four-lane-v5-market-assurance-20260923'
PREDECESSOR_BRANCH='cert/cohort-state-59078c3dec08'
PREDECESSOR_PROTOCOL='d473936a59a5ab309858c5cfa7347a002677467c90984c0ecffe3986dd053664'
PREDECESSOR_RECORD='90b6440a6429f8dc1f14f0ae63900bbcb2e7d8523c9719d55ad2561e6da8ff48'
PREDECESSOR_RUN=35935431384
PREDECESSOR_ARTIFACT=10785439707
PREDECESSOR_ARCHIVE='sha256:1729982afa710db37dc401b0d515125f7cd7d5c6fd2d8a43fafaf334a86e326c'
SUCCESSOR_COHORT='prospective-four-lane-v6-coverage-repair-20260924'


def acceptance_terms(protocol):
    value=deepcopy(protocol)
    for key in ('cohort_id','frozen_parent_integration_sha'):value.pop(key,None)
    for row in value['frozen_lanes'].values():row.pop('source_diff_sha256',None)
    return value


def verify_state(state):
    records=state.get('records') or []
    if (state.get('phase')!='HALTED' or state.get('integration_sha')!=PREDECESSOR_SHA
            or state.get('cohort_id')!=PREDECESSOR_COHORT
            or state.get('protocol_sha256')!=PREDECESSOR_PROTOCOL
            or state.get('current_workflow_run_id')!=PREDECESSOR_RUN
            or len(records)!=1 or digest(records[0])!=PREDECESSOR_RECORD
            or records[0].get('block_admission_passed') is not False):
        raise ValueError('coverage_predecessor_not_preserved')
    for row in records[0]['lanes'].values():
        if row.get('accounting_reconciled') is not True or (row.get('economics') or {}).get('flat') is not True:
            raise ValueError('coverage_predecessor_not_flat')
    return dict(cohort_id=PREDECESSOR_COHORT,integration_sha=PREDECESSOR_SHA,
        workflow_run_id=PREDECESSOR_RUN,record_sha256=PREDECESSOR_RECORD,
        preserved_censored=True,verified_flat=True,records_imported_into_successor=0)


def verify_policy():
    original=json.loads(subprocess.check_output(['git','show',PREDECESSOR_SHA+':certification/profitability_protocol.json'],cwd=ROOT))
    current=json.loads((ROOT/'certification/profitability_protocol.json').read_text())
    if current['cohort_id']!=SUCCESSOR_COHORT or acceptance_terms(original)!=acceptance_terms(current):
        raise ValueError('coverage_acceptance_or_strategy_policy_changed')
    baseline=json.loads(subprocess.check_output(['git','show',PREDECESSOR_SHA+':certification/sources.json'],cwd=ROOT))
    current_sources=json.loads((ROOT/'certification/sources.json').read_text())
    for lane,row in baseline['lanes'].items():
        for field in ('source_sha','source_branch','execution_sha','policy_hash','strategy_version','file_hashes'):
            if row.get(field)!=current_sources['lanes'][lane].get(field):
                raise ValueError('coverage_frozen_source_identity_changed:'+lane+':'+field)
    return dict(acceptance_terms_sha256=digest(acceptance_terms(current)),
                strategy_economics_unchanged=True,target_market_scope_unchanged=True,
                provider_limits_unchanged=True,paper_only_unchanged=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--replay',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    api=GitHub();sha=git('rev-parse','HEAD')
    run=api.request('GET',f'actions/runs/{PREDECESSOR_RUN}')
    if run['head_sha']!=PREDECESSOR_SHA or run['status']!='completed':raise ValueError('coverage_predecessor_active_or_foreign')
    artifact=api.request('GET',f'actions/artifacts/{PREDECESSOR_ARTIFACT}')
    if artifact.get('digest')!=PREDECESSOR_ARCHIVE or artifact.get('expired'):raise ValueError('coverage_original_artifact_unavailable')
    blob=api.request('GET','contents/certification/PROSPECTIVE_PROGRAM_STATE.json?ref='+PREDECESSOR_BRANCH)
    prior=verify_state(json.loads(base64.b64decode(blob['content'])))
    replay=json.loads(Path(a.replay).read_text())
    if replay.get('integration_sha')!=sha or replay.get('passed') is not True or replay.get('source_run')!=PREDECESSOR_RUN:
        raise ValueError('coverage_final_historical_replay_missing')
    receipt=dict(passed=True,integration_sha=sha,predecessor=prior,invariants=verify_policy(),
        successor_cohort_id=SUCCESSOR_COHORT,source_artifact=artifact['id'],source_artifact_digest=artifact['digest'],
        historical_replay_sha256=digest(replay))
    Path(a.output).write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print(json.dumps(receipt,sort_keys=True))


if __name__=='__main__':main()
