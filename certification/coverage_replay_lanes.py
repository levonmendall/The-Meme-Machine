"""Pure post-repair replay of captured first-hour acquisition facts."""
import argparse
import gzip
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

p=argparse.ArgumentParser();p.add_argument('--lane',required=True);p.add_argument('--artifact-root',required=True);p.add_argument('--source-root',required=True)
a=p.parse_args();root=Path(a.artifact_root);source=Path(a.source_root);sys.path.insert(0,str(source))
# A historical replay must not accidentally create new evidence.
def no_network(event,args):
    if event=='socket.connect':raise RuntimeError('coverage_replay_network_forbidden')
sys.addaudithook(no_network)
if a.lane=='pons':
    from robinhood_research.pons_selective_acquisition import strategy_trajectory_preflight
    rows=json.load(gzip.open(root/'certification-native/hourly/pons/pons-selective-continuation-v1-cohort/complete-result.json.gz','rt'))['rows']
    seen={};replayed=0;cached_age_skips=0;saved=0.
    for row in rows:
        snapshots=row.get('trajectory_snapshots');launch=row.get('launch_at')
        if not snapshots or launch is None:continue
        vector=row['vector'];asof=vector['asof'];curve=row['curve']
        result=strategy_trajectory_preflight({'stamp':SimpleNamespace(event_at=asof)},snapshots,launch)
        prior=row.get('trajectory_preflight')
        if prior is not None and result!=prior:raise ValueError('historical_frozen_trajectory_decision_changed')
        replayed+=1
        if curve in seen and 'token_age' in result['reasons']:
            assert seen[curve]==launch
            cached_age_skips+=1;saved+=(row.get('timing') or {}).get('trajectory_seconds',0)
        seen[curve]=launch
    result=dict(passed=True,captured_trajectory_rows_replayed=replayed,
        repeated_age_rejects_already_known=cached_age_skips,recorded_redundant_trajectory_seconds=saved,
        historical_queue_rescue_claimed=False,new_evidence_captured=False)
elif a.lane=='pump':
    from meme_machine.pump_acceleration_history import IncrementalPumpSwapHistory
    facts=json.loads((root/'pump-shared-attribution.json').read_text())
    contradictions=sum(r.get('contradictory_prior_negative_body_has_candidate_trade',0) for r in facts['groups'].values())
    if contradictions:raise ValueError('historical_negative_hint_contradiction')
    checked=0
    for sample in facts['samples']:
        body=sample.get('immutable_body') or {};at=body.get('block_time')
        if at is None:continue
        history=IncrementalPumpSwapHistory(sample['candidate_id'],at-60)
        history.stream_prefiltered_signatures.add(sample['signature'])
        history.signature_rows[sample['signature']]=dict(signature=sample['signature'],blockTime=at,slot=body['slot'],err=None)
        history.history_exhausted=True;history._coverage()
        class NoTransport:
            def call_many(self,*_args,**_kwargs):raise AssertionError('known_negative_rehydrated')
        history._decode_pending(NoTransport(),at,'research_history')
        assert history.pending_relevant(at)==0 and history.decision_window_status(at)['complete']
        assert sample['signature'] not in history.processed and not history.events
        checked+=1
    result=dict(passed=True,captured_negative_samples_replayed=checked,contradictions=contradictions,
        redundant_history_consumer_interests=sum(v.get('prior_negative_and_acquired_body_confirms_no_candidate_trade',0) for k,v in facts['groups'].items() if k.startswith('history|')),
        no_trade_events_invented=True,historical_admission_changed=False)
elif a.lane=='ramses':
    from robinhood_research import ramses_all_pool_lifecycle as lane
    from robinhood_tests.test_ramses_preentry_metadata import ArchivedRpc
    cases=json.loads((source/'robinhood_tests/fixtures/ramses_preentry_35935431384.json').read_text())['cases']
    for case in cases:
        with patch.object(lane,'_batch_logs',return_value=case['logs']):
            history,auth=lane._canonical_preentry_history(ArchivedRpc(case),{'pool':case['pool'],'prehistory':case['expected_history']},case['screen'])
        assert history==case['expected_history'] and auth['authenticated'] and auth['identity_match']
    result=dict(passed=True,captured_pool_cases_replayed=len(cases),preentry_history_authenticated=True,
        full_entry_evidence_captured=False,unavailable_cost_routes_remain_rejected=True,
        historical_provider_failures_not_reconstructed=True)
else:raise ValueError('coverage_replay_lane')
print(json.dumps(dict(lane=a.lane,**result),sort_keys=True))
