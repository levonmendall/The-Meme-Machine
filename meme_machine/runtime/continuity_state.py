"""Write-ahead bridge between the native Ramses journal and continuation state.

The journal commits economics. The sidecar records the exact already-computed
state transition before that commit so either side of an interrupted acknowledgement
can be resumed idempotently, without repeating a decision or resetting its clock.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

def fields(state):
    return deepcopy({k:v for k,v in state.items() if k not in ('thread','proxy','pending_native_checkpoint')})

def write(path,state):
    value={k:v for k,v in state.items() if k not in ('thread','proxy')}
    p=Path(path);tmp=p.with_suffix(p.suffix+'.tmp')
    with tmp.open('w') as f:
        json.dump(value,f,sort_keys=True,separators=(',',':'));f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(tmp,p)

def _apply(state,next_state,version):
    for key in list(state):
        if key not in ('thread','proxy'):state.pop(key)
    state.update(deepcopy(next_state));state['last_native_version']=version

def checkpoint(book,identity,*,state,path,action,detail,at,next_state,commit=None):
    if state.get('pending_native_checkpoint'):raise RuntimeError('unresolved_native_checkpoint_intent')
    prior=book.position(identity)
    # Repeated finalized frontiers may produce the identical command. The native
    # ledger already treats this as a no-op; the sidecar must do the same.
    for raw, in book.db.execute('SELECT body FROM ramses_strategy_journal WHERE id=? AND action=?',(identity,action)):
        event=json.loads(raw)
        if event.get('at')==at and event.get('last_controller')==detail:
            if int(state.get('last_native_version',-1))>=event['version']:return prior
            raise RuntimeError('native_checkpoint_missing_acknowledgement_intent')
    intent=dict(identity=identity,action=action,detail=deepcopy(detail),at=int(at),
        previous_version=prior['version'],next_state=fields(next_state))
    state['pending_native_checkpoint']=intent;write(path,state)
    result=(commit or book.checkpoint)(identity,action=action,detail=detail,at=at)
    if result['version']!=prior['version']+1 or result.get('last_controller')!=detail:
        raise RuntimeError('native_checkpoint_acknowledgement_mismatch')
    _apply(state,intent['next_state'],result['version']);write(path,state)
    return result

def recover(book,identity,state,path):
    intent=state.get('pending_native_checkpoint')
    if not intent:return False
    if intent['identity']!=identity:raise RuntimeError('native_checkpoint_intent_identity')
    row=book.position(identity);version=int(intent['previous_version'])
    if row['version']==version:
        row=book.checkpoint(identity,action=intent['action'],detail=intent['detail'],at=intent['at'])
    if (row['version']!=version+1 or row.get('last_controller')!=intent['detail'] or row['at']!=intent['at']):
        raise RuntimeError('native_checkpoint_intent_journal_disagreement')
    _apply(state,intent['next_state'],row['version']);write(path,state)
    return True
