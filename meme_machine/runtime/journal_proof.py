"""Exact bounded summaries of already-preserved native action prefixes."""
from copy import deepcopy
from meme_machine.runtime.journal import digest


def chain(hashes,previous='0'*64):
    for checksum in hashes:previous=digest([previous,checksum])
    return previous


def extend(events,prior=None):
    result=deepcopy(prior or dict(events=0,chain_hash='0'*64,actions={},entry_at=None,
                                 last_monitor_at=None,last_version=None,version_violations=0))
    for event in events:
        action=event['action'];position=event.get('position') or {}
        result['actions'][action]=result['actions'].get(action,0)+1
        result['events']+=1;result['chain_hash']=chain([digest(event)],result['chain_hash'])
        at=event.get('at',position.get('last_at',position.get('at')))
        if action in ('entry','open','fill','filled') and isinstance(at,(int,float)) and result['entry_at'] is None:
            result['entry_at']=at
        if action in ('mark','monitor') and isinstance(at,(int,float)):result['last_monitor_at']=at
        version=position.get('version')
        if version is not None:
            if result['last_version'] is not None and version!=result['last_version']+1:
                result['version_violations']=result.get('version_violations',0)+1
            result['last_version']=version
    return result


def continues(old,new):
    """New compact prefix must be a provable prefix of the preceding report."""
    old_start=old.get('event_offset',0);new_start=new.get('event_offset',0)
    old_hashes=old.get('event_hashes',[]);new_hashes=new.get('event_hashes',[])
    if not old_hashes and old.get('events',0)==0:return False
    if not old_start<=new_start<=old_start+len(old_hashes):return False
    consumed=new_start-old_start
    if chain(old_hashes[:consumed],old.get('prefix_hash','0'*64))!=new.get('prefix_hash','0'*64):return False
    remainder=old_hashes[consumed:]
    return new_hashes[:len(remainder)]==remainder
