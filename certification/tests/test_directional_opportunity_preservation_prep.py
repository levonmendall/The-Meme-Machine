import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "certification/strategy-prep/directional-opportunity-preservation-v1.json"
DOC = ROOT / "docs/DIRECTIONAL_OPPORTUNITY_PRESERVATION_V1_PREP.md"

def load():
    return json.loads(SPEC.read_text())

def test_prep_is_paper_only_and_stage_e_isolated():
    s = load()
    assert s["paper_only"] is True
    assert s["live_money_authority"] is False
    isolation = s["stage_e_isolation"]
    assert isolation["stage_e_candidate_modified"] is False
    assert isolation["stage_e_branch_modified"] is False
    assert isolation["stage_e_workflow_modified"] is False
    assert isolation["workflow_dispatch_authorized"] is False
    assert isolation["market_run_authorized"] is False
    assert isolation["activation_allowed"] is False

def test_prep_changes_no_strategy_economics():
    effect = load()["policy_effect"]
    assert all(value is False for value in effect.values())

def test_both_directional_families_are_required():
    families = load()["families"]
    assert set(families) == {"pump", "pons"}
    assert families["pump"]["current"] == "pump-acceleration-independent-v1"
    assert families["pump"]["survivor"] == "pumpswap-survivor-momentum-v1"
    assert families["pons"]["current"] == "pons-selective-continuation-v1"
    assert families["pons"]["survivor"] == "pons-postgrad-survivor-momentum-v1"

def test_current_rejection_cannot_suppress_survivor():
    req = load()["current_to_survivor_requirements"]
    assert req["survivor_discovery_independent_of_current_qualification"] is True
    assert req["current_rejection_must_never_tombstone_or_suppress_survivor_interest"] is True
    assert req["current_rejection_must_not_be_a_survivor_admission_gate"] is True
    assert req["link_and_survivor_interest_must_survive_restart"] is True
    assert req["duplicate_exposure_for_same_family_asset_forbidden"] is True

def test_instrumentation_has_no_decision_authority_or_provider_expansion():
    inst = load()["marginal_reject_instrumentation"]
    joined = " ".join(inst["runtime_constraints"]).lower()
    assert "zero order, reservation, sizing, or qualification authority" in joined
    assert "must not add provider calls" in joined
    assert inst["outcome_windows"] == ["5m", "15m", "1h", "6h", "24h"]

def test_composition_follows_yesterdays_prepared_changes():
    order = load()["composition_order"]
    assert order[-3:] == [
        "directional-capital-parity-v1",
        "exit-optimization-v1",
        "directional-opportunity-preservation-v1",
    ]
    doc = DOC.read_text()
    assert "PREPARED REQUIREMENT — NOT ACTIVE" in doc
    assert "No Stage-E branch or candidate is modified." in doc
