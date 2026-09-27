"""Externalize consumed Pons observation logs after their native snapshot is verified.

Only copied successor state changes. Qualifiers, lifecycle receipts, native books,
re-entry vectors and the preceding artifact retain their original authority.
"""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from certification.journal import canonical,digest

FOLDER='pons-selective-continuation-v1-cohort'
LOGS={'rows':'candidate-rows.jsonl','discovery_sessions':'provider-sessions.jsonl',
      'sequencer_recoveries':'sequencer-recoveries.jsonl'}


def externalize(destination,artifact,window):
    from certification.autonomous_window import verify_snapshot,checksum
    destination=Path(destination);files=destination/'files'
    plane=files/'shared/shared-robinhood-evidence.candidates.sqlite'
    snapshot=verify_snapshot(artifact)
    prefix='certification-native/'+snapshot['phase']+'/'
    saved_files={r['target'][len(prefix):]:r for r in snapshot['files'] if r.get('target','').startswith(prefix)}
    with closing(sqlite3.connect(plane)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='runtime'").fetchone():return None
        row=db.execute("SELECT body FROM runtime WHERE key='pons_cohort'").fetchone()
        if row is None:return None
        saved=json.loads(row[0]);result=saved['result']
        preserved=Path(artifact)/('certification-'+snapshot['phase'])/plane.name
        with closing(sqlite3.connect(preserved.resolve().as_uri()+'?mode=ro',uri=True)) as original:
            previous=original.execute("SELECT body FROM runtime WHERE key='pons_cohort'").fetchone()
        if previous is None or json.loads(previous[0])!=saved:raise ValueError('pons_checkpoint_not_preserved')
        # Position-only handoffs keep the last discovery checkpoint untouched.
        expected={k:window[k] for k in ('campaign_id','authorization_hash','index','workflow_run_id')}
        if saved.get('phase')!='finalizing' or saved.get('autonomous_window')!=expected:return None
        old=result.get('archived_observations') or dict(count=0,rejections={},discovery_sessions=0,sequencer_recoveries=0)
        summary=deepcopy(old);inventory=[];paths=[];counts=saved.get('archive_counts',{})
        for key,name in LOGS.items():
            expected_path=FOLDER+'/'+name
            if result.get('native_archive_paths',{}).get(key)!=expected_path:
                raise ValueError('pons_archive_path_identity')
            path=files/'pons'/expected_path
            if not path.exists():
                if counts.get(key,0):raise ValueError('pons_archive_missing')
                continue
            item=saved_files.get('pons/'+expected_path)
            if not item or checksum(path)!=item['sha256'] or path.stat().st_size!=item['bytes']:
                raise ValueError('pons_archive_not_preserved')
            n=0
            with path.open() as stream:
                for line in stream:
                    if not line.strip():continue
                    record=json.loads(line);n+=1
                    if key=='rows':
                        for reason in (record.get('vector') or {}).get('all_rejections') or []:
                            summary['rejections'][reason]=summary['rejections'].get(reason,0)+1
            if n<counts.get(key,0):raise ValueError('pons_archive_regression')
            summary['count' if key=='rows' else key]+=n
            inventory.append(dict(path='pons/'+expected_path,sha256=item['sha256'],bytes=item['bytes'],records=n))
            paths.append(path)
        if not any(r['records'] for r in inventory):return None
        proof=dict(schema='pons-observation-prefix-v1',window=expected,
            preserved_snapshot_hash=digest(snapshot),inventory=inventory,previous=old.get('chain_hash'))
        summary['chain_hash']=digest(proof);summary['proof']=proof
        result['archived_observations']=summary
        result['autonomous_observation_offset']=0
        for key in LOGS:
            result[key]=[];saved.setdefault('archive_counts',{})[key]=0
        # An incomplete capsule has no manifest and can never authorize restore.
        with db:db.execute("UPDATE runtime SET body=? WHERE key='pons_cohort'",(canonical(saved),))
        for path in paths:path.unlink()
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('pons_archive_integrity')
    return proof
