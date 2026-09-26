"""Candidate Plane accounting, not decision authority.

Counts are historical, distinct native candidates per class (classes overlap).
Generation/current-state reconciliation is separate. Superseded work is never loss
or completion. All consumers use this table, including certification's independent
read-only comparison with the durable plane.
"""
import hashlib
import json
from pathlib import Path
import sqlite3

OUTCOMES = {
    'discovered': ('discovered', None),
    'watching': ('candidate_watching', None),
    'canonical_evidence_requested': ('current_state_requested', None),
    'canonical_evidence_complete': ('current_state_complete', 'canonical_completion'),
    'provider_capacity_defer': ('terminal', 'capacity_censored'),
    'freshness_deadline_censored': ('terminal', 'consumer_deadline'),
    'authoritative_evidence_failure': ('terminal', 'provider_failed'),
    'transient_defer': ('candidate_deferred', 'unresolved_transient'),
    'superseded': ('candidate_superseded', 'superseded_generation'),
    'strategy_rejected': ('rejected', 'strategy_rejection'),
    'structural_excluded': ('rejected', 'structural_ineligible'),
    'promoted': ('current_state_progress', None),
    'qualified': ('qualified', None),
    'entry_confirmation': ('entry_confirmation', None),
    'entry_reserved': ('entry_reserved', None),
    'entry_filled': ('entry_filled', None),
    'entry_cancelled': ('entry_cancelled', None),
    'settled': ('settled', None),
    'position_safety': ('forward_observation', None),
}
INFRASTRUCTURE = ('capacity_censored', 'consumer_deadline', 'provider_failed')


def classify(kind):
    try:return OUTCOMES[kind]
    except KeyError:raise ValueError('unclassified_candidate_plane_outcome:'+str(kind)) from None


def screen_outcome(screen):
    return 'structural_excluded' if screen['causal_bucket']=='valid_early_structural_rejection' else 'strategy_rejected'


def immutable_exclusion(evidence):
    """Only the existing authenticated immutable non-native quote proof persists.

    The caller already performed authenticated_early_rejection's freshness check.
    Retained proofs remain interpretable after that decision's freshness window.
    This is reporting scope, never a new admission or strategy predicate.
    """
    e=evidence or {}
    if (e.get('authentication_complete') is True and
        e.get('boundary')=='natural_non_native_quote_not_supported' and
        isinstance(e.get('pair_token'),str) and len(e['pair_token'])==42 and
        e['pair_token']!='0x'+'0'*40 and e.get('curve') and e.get('block_hash') and
        e.get('source_transaction')):
        return dict(basis='authenticated_curve_immutable_pairToken',
                    evidence=e,scope='same_native_candidate_and_frozen_policy')
    return None


def project(plane, pipeline, *, through=None, batch_size=256):
    """One bounded page, atomically deduplicated in the receiving pipeline.

    The durable source is not acknowledged/deleted. Crash/restart replays any page
    safely. A shutdown caller may drain up to a captured high-water mark.
    """
    if not 1<=batch_size<=256:raise ValueError('projection_batch_bound')
    with plane.lock:
        first=plane.db.execute('SELECT t.* FROM transitions t JOIN candidates c ON c.id=t.candidate WHERE c.lane=? ORDER BY t.seq LIMIT 1',(pipeline.lane,)).fetchone()
    if first is None:return 0
    # Immutable source identity survives relocation/restart of either database.
    source='candidate-plane:'+hashlib.sha256(json.dumps(dict(first),sort_keys=True).encode()).hexdigest()
    with pipeline.lock:
        after=pipeline.db.execute('SELECT COALESCE(MAX(sequence),0) FROM progress_sources WHERE source=?',(source,)).fetchone()[0]
    with plane.lock:
        rows=plane.db.execute('''SELECT t.* FROM transitions t JOIN candidates c ON c.id=t.candidate
            WHERE c.lane=? AND t.seq>? AND t.seq<=? ORDER BY t.seq LIMIT ?''',
            (pipeline.lane,after,through if through is not None else 9223372036854775807,batch_size)).fetchall()
    for raw in rows:
        row=dict(raw);stage,classification=classify(row['kind'])
        details=json.loads(row['details'])
        pipeline.record(row['candidate'],stage,row['reason'],classification,
            source=source,source_sequence=row['seq'],candidate_generation=row['generation'],
            candidate_plane_kind=row['kind'],candidate_plane_sequence=row['seq'],
            candidate_plane_at=row['at'],candidate_plane_details=details,
            authenticated_evidence=details.get('authenticated_evidence'))
    return len(rows)


def high_water(plane):
    with plane.lock:return plane.db.execute('SELECT COALESCE(MAX(seq),0) FROM transitions').fetchone()[0]


def consistency(plane_path, pipeline_path, lane, *, reported_classes=None):
    """Fail closed on missing candidate/class membership, not naive count equality.

    Both stores cover cumulative native candidate history for this lane. A later
    generation cannot erase an earlier real loss; fenced results map to no loss.
    A report may overlap classes or count additional native pipeline censoring.
    """
    result=dict(schema='candidate-plane-accounting-v1',status='fail',
        population='cumulative_native_candidates_per_lane; historical_classes_overlap',
        expected_unique_classes={},transition_counts={},missing_memberships={},failures=[])
    if not Path(plane_path).is_file() or not pipeline_path or not Path(pipeline_path).is_file():
        result['failures']=['candidate_plane_or_pipeline_unavailable'];return result
    with sqlite3.connect(Path(plane_path).resolve().as_uri()+'?mode=ro',uri=True) as plane, \
            sqlite3.connect(Path(pipeline_path).resolve().as_uri()+'?mode=ro',uri=True) as pipeline:
        pipeline.execute('ATTACH DATABASE ? AS plane',(Path(plane_path).resolve().as_uri()+'?mode=ro',))
        for kind,n in plane.execute('SELECT t.kind,COUNT(*) FROM transitions t JOIN candidates c ON c.id=t.candidate WHERE c.lane=? GROUP BY t.kind',(lane,)):
            try:_,classification=classify(kind)
            except ValueError:
                result['failures'].append('unclassified_candidate_plane_outcome:'+kind);continue
            result['transition_counts'][kind]=n
            if classification not in INFRASTRUCTURE:continue
            expected=plane.execute('SELECT COUNT(DISTINCT t.candidate) FROM transitions t JOIN candidates c ON c.id=t.candidate WHERE c.lane=? AND t.kind=?',(lane,kind)).fetchone()[0]
            missing=pipeline.execute('''SELECT COUNT(DISTINCT t.candidate) FROM plane.transitions t
                JOIN plane.candidates c ON c.id=t.candidate WHERE c.lane=? AND t.kind=?
                AND NOT EXISTS(SELECT 1 FROM progress p WHERE p.lane=? AND p.candidate=t.candidate AND p.classification=?)''',
                (lane,kind,lane,classification)).fetchone()[0]
            result['expected_unique_classes'][classification]=expected
            result['missing_memberships'][classification]=missing
            if missing:result['failures'].append('candidate_plane_missing:'+classification)
            if reported_classes is not None and reported_classes.get(classification,0)<expected:
                result['failures'].append('candidate_plane_report_understates:'+classification)
    result['status']='fail' if result['failures'] else 'pass'
    return result
