"""Resolve the known digest-pinned historical Meteora exposure on a copy only."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

from certification.inspect_artifact import NoRedirect


def download(artifact_id,expected_sha):
    url=f'https://api.github.com/repos/levonmendall/The-Meme-Machine/actions/artifacts/{artifact_id}/zip'
    req=urllib.request.Request(url,headers={
        'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],
        'Accept':'application/vnd.github+json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=30) as response:
            data=response.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in (301,302,303,307,308):raise
        with urllib.request.urlopen(exc.headers['Location'],timeout=60) as response:
            data=response.read()
    if hashlib.sha256(data).hexdigest()!=expected_sha:
        raise ValueError('historical_resolution_artifact_digest_mismatch')
    return data


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--artifact-id',type=int,required=True)
    p.add_argument('--sha256',required=True)
    p.add_argument('--native-meteora-root',required=True)
    p.add_argument('--expected-journal-hash',required=True)
    p.add_argument('--expected-reason',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    data=download(args.artifact_id,args.sha256)
    with zipfile.ZipFile(io.BytesIO(data)) as archive,tempfile.TemporaryDirectory() as tmp:
        names=set(archive.namelist())
        dbname=next((n for n in names if n.endswith(
            '/solana-dlmm-independent-v1-live.accounting.sqlite3')),None)
        if dbname is None:raise ValueError('historical_resolution_book_missing')
        path=Path(tmp)/'book.sqlite3';path.write_bytes(archive.read(dbname))
        for suffix in ('-wal','-shm'):
            if dbname+suffix in names:Path(str(path)+suffix).write_bytes(archive.read(dbname+suffix))
        env={k:v for k,v in os.environ.items() if not k.startswith(('MM_','GH_','GITHUB_'))
             and not any(x in k.upper() for x in ('TOKEN','SECRET','PRIVATE_KEY'))}
        command=[sys.executable,str(Path(__file__).with_name(
            'native_historical_meteora_resolution.py')),
            '--copy',str(path),
            '--expected-journal-hash',args.expected_journal_hash,
            '--expected-reason',args.expected_reason]
        run=subprocess.run(command,cwd=args.native_meteora_root,env=env,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=30)
        if run.returncode:
            raise RuntimeError('historical_resolution_native_failed:'+run.stderr[-1000:])
        receipt=json.loads(run.stdout)
    receipt.update(
        artifact_id=args.artifact_id,
        artifact_sha256=args.sha256,
        immutable_original_artifact_preserved=True,
    )
    Path(args.output).write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print('HISTORICAL_RESOLUTION '+json.dumps(receipt,sort_keys=True))


if __name__=='__main__':main()
