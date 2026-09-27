"""Read a hash-bound predecessor snapshot before opening its mutable hot copy.

Only the controller's verified native artifact supplies preservation authority.
This module creates no campaign, provider or entry authority.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


def authority(name,lane):
    position=os.environ.get('MM_AUTONOMOUS_POSITION_STATE')
    if position:
        from certification.position_continuation import _runtime_identity
        _runtime_identity(position,lane)
        claim=json.loads((Path(position)/'autonomous-position-authority.json').read_text())
        receipt=json.loads((Path(position)/'certification-position/restored-campaign-state.json').read_text())
    else:
        from certification.campaign_state import restored_window
        claim=restored_window()
        if claim is None:return None
        receipt=json.loads(Path(os.environ['MM_AUTONOMOUS_STATE_RECEIPT']).read_text())
    expected=receipt.get('ledger_snapshots',{}).get(name)
    if expected is None:return None
    artifact=(claim.get('previous') or {}).get('artifact') or {}
    if (not re.fullmatch('[0-9a-f]{64}',expected)
            or not re.fullmatch('sha256:[0-9a-f]{64}',str(artifact.get('digest','')))):
        raise ValueError('native_checkpoint_preservation_authority')
    return dict(schema='preserved-native-prefix-v1',state_hash=receipt['state_hash'],
        snapshot_sha256=expected,snapshot_name=name,artifact=artifact,
        campaign_id=claim['campaign_id'],window_index=claim['previous']['index'])


@contextmanager
def snapshot(path,*,name,lane):
    """A later opener may see legitimate new hot writes: then do not compact.

    Copy and hash one descriptor so no concurrent WAL publication or replacement
    can make the archived prefix refer to different bytes. The checkpoint writer
    will preserve every newer journal row in the active database.
    """
    proof=authority(name,lane)
    if proof is None or not Path(path).is_file():
        yield None;return
    with tempfile.TemporaryDirectory(prefix='native-prefix-') as folder:
        target=Path(folder)/'snapshot.sqlite';checksum=hashlib.sha256()
        with Path(path).open('rb') as source,target.open('wb') as dest:
            while chunk:=source.read(1024*1024):
                dest.write(chunk);checksum.update(chunk)
        if checksum.hexdigest()!=proof['snapshot_sha256']:
            yield None;return
        yield target,proof
