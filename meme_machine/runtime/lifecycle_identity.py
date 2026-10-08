"""Local identity retirement fence; grants no permission and requires no keys."""
import os,re,time
MARKER=':paper-epoch:'
def parsed(identity):
    if MARKER not in identity:return None
    prefix,tag=identity.rsplit(MARKER,1)
    match=re.fullmatch(r'([A-Za-z0-9_-]+):([0-9]+)',tag)
    if not prefix or match is None:raise ValueError('lifecycle_identity')
    return dict(epoch=match[1],index=int(match[2]))
def issue(identity):
    if not isinstance(identity,str) or not identity or parsed(identity):raise ValueError('lifecycle_identity')
    epoch=os.environ.get('MM_PAPER_EPOCH')
    return identity if not epoch else identity+MARKER+epoch+':'+str(time.time_ns())
def scope(value):
    return dict(epoch=value['epoch_id'],index=int(value['window_index']))
def archived_scope(value):
    return dict(epoch=value['epoch_id'],through=int(value['window_index']))
def validate_new(identity,*,archived=None):
    value=parsed(identity)
    if archived is not None and (value is None or value['epoch']!=archived['epoch'] or value['index']<=archived['through']):
        raise ValueError('archived_lifecycle_replay')
