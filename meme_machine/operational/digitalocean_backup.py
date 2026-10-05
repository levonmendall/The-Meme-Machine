"""Ordinary bounded Volume snapshots of coherent application backup points."""
from datetime import datetime,timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from .backup import prepare
from .digitalocean import request
from .observation import read_json,atomic_json,stamp
from .storage_guard import verify_storage

OUTPUT=Path('/var/lib/meme-machine-backup')

def execute(config='/etc/meme-machine/backup.json',output=OUTPUT):
    output=Path(output);output.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (output/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        c=read_json(config);root=Path(os.environ['MM_STATE_ROOT']).resolve()
        storage=verify_storage(root)
        parent=Path(c['point_parent']).resolve()
        if Path(storage['mount_target']) not in parent.parents or parent==root or root in parent.parents:
            raise ValueError('backup_point_location')
        status,vol=request('GET','/v2/volumes/'+c['volume_id'])
        vol=vol['volume']
        if vol['droplet_ids']!=[c['droplet_id']] or vol['region']['slug']!=c['region']:
            raise ValueError('backup_volume_topology')
        name=c['snapshot_prefix']+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
        if not name.startswith('meme-machine-paper-') or len(name)>100:raise ValueError('backup_snapshot_name')
        point=parent/name
        row=dict(status='COPYING',start_time=stamp(),epoch_id=storage['epoch_id'],
            volume_id=c['volume_id'],snapshot_name=name,point=str(point),snapshot_id=None)
        path=output/'latest.json';atomic_json(path,row)
        try:
            row['coherent_point']=prepare(root,point);row['status']='CREATING_SNAPSHOT';atomic_json(path,row)
            # The frozen application copy was synced and its writers thawed.
            # Only this complete point is restored from a running-volume snapshot.
            status,data=request('POST','/v2/volumes/'+c['volume_id']+'/snapshots',{'name':name})
            snapshot=data['snapshot'];row['snapshot_id']=snapshot['id'];atomic_json(path,row)
            _,data=request('GET','/v2/volumes/snapshots/'+snapshot['id'])
            actual=data['snapshot']
            if actual['resource_id']!=c['volume_id'] or actual['resource_type']!='volume':
                raise ValueError('backup_off_host_resource_identity')
            row.update(status='SNAPSHOT_READY',end_time=stamp(),off_host=True,
                restore_relative_point=str(point.relative_to(storage['mount_target'])))
            atomic_json(path,row);atomic_json(point/'off-host.json',row)
            retention=max(2,min(7,int(c.get('retained_snapshots',3))))
            _,listing=request('GET','/v2/volumes/'+c['volume_id']+'/snapshots?per_page=200')
            ours=[s for s in (listing.get('snapshots') or []) if s.get('resource_id')==c['volume_id'] and s['name'].startswith(c['snapshot_prefix'])]
            for old in sorted(ours,key=lambda s:s['created_at'],reverse=True)[retention:]:
                request('DELETE','/v2/volumes/snapshots/'+old['id'])
                local=parent/old['name']
                if local.is_dir() and not local.is_symlink() and (local/'off-host.json').exists():
                    shutil.rmtree(local)
            return row
        except BaseException as error:
            row.update(status='FAIL',end_time=stamp(),error_type=type(error).__name__)
            # A timeout can leave a successfully created remote snapshot. Never
            # retry a creation blindly; use this exact snapshot_name to inspect.
            atomic_json(path,row);raise

def main():
    try:row=execute()
    except Exception as error:
        print(json.dumps(dict(status='FAIL',error_type=type(error).__name__)));return 1
    print(json.dumps({k:row[k] for k in ('status','epoch_id','snapshot_id','point')},sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
