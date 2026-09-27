"""Bind newly issued autonomous lifecycle IDs to existing window authority.

This does not grant entry authority. It prevents a retired window's identity from
being admitted again after its terminal projection leaves operational storage.
Existing position IDs are never rewritten, including on position-only restore.
"""
import re
from certification.journal import digest

MARKER=':autonomous-window:'


def scope(window):
    if (not isinstance(window,dict) or type(window.get('index')) is not int
            or window['index']<0 or not window.get('campaign_id')
            or not re.fullmatch('[0-9a-f]{64}',window.get('authorization_hash',''))):
        raise ValueError('lifecycle_window_scope')
    return dict(campaign=digest([window['campaign_id'],window['authorization_hash']]),index=window['index'])


def parsed(identity):
    if MARKER not in identity:return None
    prefix,tag=identity.rsplit(MARKER,1)
    match=re.fullmatch('([0-9a-f]{64}):([0-9]+)',tag)
    if not prefix or not match or MARKER in prefix:raise ValueError('lifecycle_window_identity')
    index=int(match[2])
    if str(index)!=match[2]:raise ValueError('lifecycle_window_identity')
    return dict(campaign=match[1],index=index)


def issue(identity):
    from certification.campaign_state import active_window
    if parsed(identity) is not None:raise ValueError('lifecycle_identity_already_issued')
    window=active_window()
    if window is None:return identity
    value=scope(window)
    return identity+MARKER+value['campaign']+':'+str(value['index'])


def validate_new(identity,*,archived=None):
    from certification.campaign_state import active_window
    value=parsed(identity);window=active_window()
    if value is None:
        if archived is not None:raise ValueError('archived_lifecycle_requires_window_identity')
        return
    if window is None or value!=scope(window):raise ValueError('lifecycle_window_not_current')
    if archived is not None and (value['campaign']!=archived['campaign'] or value['index']<=archived['through']):
        raise ValueError('archived_lifecycle_replay')


def archived_scope(authority):
    # A verified predecessor snapshot identifies its own window. Authority must
    # include the original authorization hash; a bare number is insufficient.
    return dict(campaign=scope(dict(campaign_id=authority['campaign_id'],
        authorization_hash=authority['authorization_hash'],index=authority['window_index']))['campaign'],
        through=authority['window_index'])
