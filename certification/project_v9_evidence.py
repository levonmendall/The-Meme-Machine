"""Bounded read-only projection of the immutable v9 artifact for offline repairs."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

EXPECTED='59c5eccd9a57ff0bd746c11a174afbe434b38e56650d14e1b63994b7260b6002'

def project(archive, destination):
    with Path(archive).open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=EXPECTED:
            raise ValueError('historical_artifact_digest_mismatch')
    out=Path(destination);out.mkdir(exist_ok=False)
    inventory=[];total=0
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir():continue
            p=Path(info.filename)
            if p.is_absolute() or '..' in p.parts:raise ValueError('archive_path')
            # Large shared raw caches are inventoried, never copied wholesale.
            include=(info.file_size<=120*1024*1024 and 'shared-solana-evidence' not in p.name)
            row=dict(path=info.filename,bytes=info.file_size,included=include)
            if include:
                total+=info.file_size
                if total>450*1024*1024:raise ValueError('projection_capacity')
                target=out/p;target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(info) as source,target.open('wb') as target_file:
                    digest=hashlib.sha256()
                    for chunk in iter(lambda: source.read(1024*1024),b''):
                        digest.update(chunk);target_file.write(chunk)
                row['sha256']=digest.hexdigest()
            inventory.append(row)
    (out/'projection.json').write_text(json.dumps(dict(run_id=36043064083,
        artifact_id=10832096927,artifact_sha256=EXPECTED,files=inventory),indent=2)+'\n')

if __name__=='__main__':project(*sys.argv[1:])
