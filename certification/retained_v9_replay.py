"""Replay selected immutable v9 decision records without providers or new observations."""
import importlib
import inspect
import json
from pathlib import Path
from certification.decision_conformance import decode,encode,digest,FUNCTIONS

BASELINE='07ec67a2b7967fd3e97c056307967ce1738f6d20'

def replay(lane):
    records=json.loads((Path(__file__).parent/'tests/fixtures/v9-postrun-decisions.json').read_text())[lane]
    for module in FUNCTIONS[lane]:importlib.import_module(module)
    import socket
    old=socket.socket
    def denied(*args,**kwargs):raise AssertionError('retained_replay_network_forbidden')
    socket.socket=denied
    try:
        for original in records:
            row=dict(original);sha=row.pop('sha256')
            assert digest(row)==sha and row['runtime_sha']==BASELINE and row['lane']==lane
            module,name=row['function'].split(':')
            assert name in FUNCTIONS[lane][module]
            function=getattr(importlib.import_module(module),name)
            arguments=decode(row['inputs'])
            bound=inspect.signature(function).bind_partial();bound.arguments.update(arguments)
            assert encode(function(*bound.args,**bound.kwargs))==row['result'],row['function']
            # Historical records retain their capture-time dataclass schema.
            # Normalize additive default-only fields through the current decoder
            # without rewriting the immutable record; all recorded fields and the
            # recorded decision result must still match exactly.
            assert encode(arguments)==encode(decode(row['inputs_after']))
    finally:socket.socket=old
    return dict(lane=lane,checked=len(records),passed=True,provider_requests=0)

if __name__=='__main__':
    import sys
    print(json.dumps(replay(sys.argv[1])))
