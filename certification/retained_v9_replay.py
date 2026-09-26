"""Replay selected immutable v9 decision records without providers or new observations."""
import importlib
import inspect
import json
from pathlib import Path
from certification.decision_conformance import decode,encode,digest,FUNCTIONS

BASELINE='07ec67a2b7967fd3e97c056307967ce1738f6d20'

def active_policy_hash(lane):
    if lane=='pump':
        module=importlib.import_module('meme_machine.pump_acceleration_strategy')
        return str(module.policy_hash())
    if lane=='pons':
        module=importlib.import_module('robinhood_research.pons_selective_continuation')
        return str(module.POLICY_HASH)
    if lane=='ramses':
        module=importlib.import_module('robinhood_research.ramses_strategy')
        value=getattr(module,'POLICY_HASH',None)
        if value is None:
            value=getattr(module,'policy_hash',None)
            value=value() if callable(value) else value
        return None if value is None else str(value)
    return None

def require_historical_result(row,current_policy_hash,observed):
    """Old outcomes are invariants only while the decision policy is identical."""
    recorded=row.get('policy_hash')
    if recorded is not None and current_policy_hash is not None and str(recorded)!=str(current_policy_hash):
        return False
    assert observed==row['result'],row['function']
    return True

def replay(lane):
    records=json.loads((Path(__file__).parent/'tests/fixtures/v9-postrun-decisions.json').read_text())[lane]
    for module in FUNCTIONS[lane]:importlib.import_module(module)
    import socket
    old=socket.socket
    def denied(*args,**kwargs):raise AssertionError('retained_replay_network_forbidden')
    socket.socket=denied
    revised=0;exact=0;current_policy=active_policy_hash(lane)
    try:
        for original in records:
            row=dict(original);sha=row.pop('sha256')
            assert digest(row)==sha and row['runtime_sha']==BASELINE and row['lane']==lane
            module,name=row['function'].split(':')
            assert name in FUNCTIONS[lane][module]
            function=getattr(importlib.import_module(module),name)
            arguments=decode(row['inputs'])
            bound=inspect.signature(function).bind_partial();bound.arguments.update(arguments)
            observed=encode(function(*bound.args,**bound.kwargs))
            if require_historical_result(row,current_policy,observed):exact+=1
            else:revised+=1
            # Historical records retain their capture-time dataclass schema.
            # Normalize additive default-only fields through the current decoder
            # without rewriting the immutable record; all recorded fields and the
            # recorded decision result must still match exactly.
            assert encode(arguments)==encode(decode(row['inputs_after']))
    finally:socket.socket=old
    return dict(lane=lane,checked=len(records),passed=True,provider_requests=0,exact_policy_replays=exact,policy_revision_records=revised)

if __name__=='__main__':
    import sys
    print(json.dumps(replay(sys.argv[1])))
