"""Explicit synthetic structural qualification for generic accounting fixtures."""
from meme_machine.runtime.journal import digest
from meme_machine.runtime.rally_cycle import build_cycle


def observe_survivor(sleeve,strategy,candidate,at):
    """Use the real native admission contract without claiming market evidence."""
    evidence=dict(candidate=True,policy_hash=sleeve.decision_policies[strategy],
        features=dict(independent_buyers=6),synthetic_offline_fixture=True)
    cycle=build_cycle(candidate=candidate,venue=sleeve.identity['lane'],
        chain='offline-native',pool='synthetic-native-pool:'+candidate,
        policy_hash=sleeve.decision_policies[strategy],input_version='synthetic-offline-v1',
        graduation=dict(at=at-12000,canonical_event='synthetic:'+candidate),
        peak_at=at-10000,reset_at=at-8000,base_start=at-7000,base_end=at-1000,
        breakout_at=at-100,decision_at=at,evidence_id=digest(evidence),
        authoritative=True,complete=True,minimum_base_seconds=3600)
    return sleeve.observe(candidate,strategy=strategy,at=at,state='qualified',
        evidence=evidence,regime=dict(at=at,rally_cycle=cycle))
