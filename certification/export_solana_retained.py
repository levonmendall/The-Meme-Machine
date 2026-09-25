"""Read only completed artifacts; export a small Solana parity subset offline.

No provider access, strategy entrypoint, dispatch, continuation or deployment.
The two source archives are downloaded once each and checksum-pinned.
"""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import urllib.error
import urllib.request
import zipfile

from meme_machine.postgrad import pumpswap_pool

SOURCES=[
 (367,36087556931,10846820233,'faedd0389b57dae7c38790d6f3470cf97632c6f8e5d65ec5b3c7716da6318c5d'),
 (368,36144662109,10872772276,'af99edde03cca57bf0e9e2c1dd1737de550346c4c3d2a52ddca5e27d2a519a0a')]

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def download(artifact,target,expected):
    if target.exists():
        if hashlib.file_digest(target.open('rb'),'sha256').hexdigest()!=expected:
            raise ValueError('cached_archive_digest')
        return
    req=urllib.request.Request(f'https://api.github.com/repos/levonmendall/The-Meme-Machine/actions/artifacts/{artifact}/zip',
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json'})
    try:response=urllib.request.build_opener(NoRedirect()).open(req,timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code!=302:raise
        response=urllib.request.urlopen(exc.headers['Location'],timeout=120)
    with response,target.open('xb') as dest:
        while chunk:=response.read(1024*1024):dest.write(chunk)
    with target.open('rb') as source:actual=hashlib.file_digest(source,'sha256').hexdigest()
    if actual!=expected:raise ValueError('source_archive_digest')


def encode(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),default=lambda b:{'zlib_base64':base64.b64encode(b).decode()})+'\n'


def main():
    out=Path('solana-retained-export');out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        temp=Path(temp)
        for number,run,artifact,expected in SOURCES:
            dest=out/str(number);dest.mkdir(exist_ok=True)
            summary=json.loads(Path(f'tests/fixtures/solana_evidence_plane/run-{number}-pump-summaries.json').read_text())
            mints={r['mint'] for r in summary['full_evidence_candidates']}
            pools={pumpswap_pool(mint) for mint in mints}
            times=[r['observed_at'] for r in summary['full_evidence_candidates']]
            archive=temp/f'{number}.zip';download(artifact,archive,expected)
            receipt=dict(run=run,artifact=artifact,source_zip_sha256=expected,files=[],selected_mints=sorted(mints),selected_pools=sorted(pools),no_market_access=True)
            with zipfile.ZipFile(archive) as z:
                names=z.namelist()
                brokers=[n for n in names if n.endswith('/shared-solana-evidence.sqlite') and 'certification-hourly/' in n]
                if len(brokers)!=1:raise ValueError('broker_source_ambiguous')
                dbpath=temp/f'{number}.sqlite';dbpath.write_bytes(z.read(brokers[0]))
                db=sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
                if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('broker_integrity')
                signatures=set()
                with gzip.open(dest/'broker-subset.jsonl.gz','wt') as sink:
                    for row in db.execute('SELECT * FROM stream_signature_archive'):
                        row=dict(row)
                        if any(str(row.get('stream','')).endswith(':'+pool) for pool in pools):
                            signatures.add(row['signature']);sink.write(encode(dict(table='stream_signature_archive',row=row)))
                    tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                    for table in tables:
                        if table=='stream_signature_archive' or not table.replace('_','').isalnum():continue
                        for raw in db.execute('SELECT * FROM '+table):
                            row=dict(raw)
                            wanted=(row.get('signature') in signatures or row.get('candidate_id') in mints|pools
                                    or row.get('address') in mints|pools or any(str(row.get('stream','')).endswith(':'+p) for p in pools))
                            if wanted:sink.write(encode(dict(table=table,row=row)))
                db.close()
                for lane in ('pump','meteora'):
                    matches=[n for n in names if n.endswith(f'certification-hourly/{lane}/rpc-evidence.jsonl.gz')]
                    if len(matches)!=1:raise ValueError('rpc_archive_ambiguous')
                    count=0
                    with z.open(matches[0]) as raw,gzip.open(raw,'rt') as source,gzip.open(dest/(lane+'-rpc-subset.jsonl.gz'),'wt') as sink:
                        for line in source:
                            row=json.loads(line);at=(row.get('observed_at_ns') or 0)/1e9
                            if lane=='meteora' or any(abs(at-t)<=25 for t in times):
                                sink.write(line);count+=1
                    receipt[lane+'_rpc_rows']=count
                # Native Solana reports/journals are retained independently from
                # evidence. Include bounded files needed to locate exact intervals.
                for name in names:
                    if '/certification-native/hourly/' not in '/'+name:continue
                    if not any('/'+lane+'/' in name for lane in ('pump','meteora')):continue
                    if not name.endswith(('.json','.jsonl','.sqlite','.sqlite3')):continue
                    info=z.getinfo(name)
                    if info.file_size>12*1024*1024:
                        receipt.setdefault('omitted_native_large',[]).append(dict(name=name,bytes=info.file_size));continue
                    target=dest/('native-'+name.split('/hourly/',1)[1].replace('/','_')+'.gz')
                    with z.open(name) as source,gzip.open(target,'wb') as sink:
                        while chunk:=source.read(1024*1024):sink.write(chunk)
                receipt['broker_signature_count']=len(signatures)
                receipt['archive_members']=[dict(name=n,bytes=z.getinfo(n).file_size) for n in names if 'pump' in n or 'meteora' in n or 'shared-solana' in n]
            for path in sorted(dest.glob('*')):
                receipt['files'].append(dict(name=path.name,bytes=path.stat().st_size,sha256=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()))
            (dest/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
            archive.unlink();dbpath.unlink()
    total=sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
    if total>28*1024*1024:raise ValueError('export_requires_further_bounded_selection')
    print(json.dumps(dict(export_bytes=total,market_access=False)))

if __name__=='__main__':main()
