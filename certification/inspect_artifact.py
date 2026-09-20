"""Read-only retained artifact review; never imports a market lane."""
import argparse
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
import urllib.error
import urllib.request
import zipfile


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--artifact-id',type=int,required=True);args=parser.parse_args()
    request=urllib.request.Request(f'https://api.github.com/repos/levonmendall/The-Meme-Machine/actions/artifacts/{args.artifact_id}/zip',
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request,timeout=60) as response:data=response.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in (301,302,303,307,308):raise
        # The signed storage request has no GitHub token attached.
        with urllib.request.urlopen(exc.headers['Location'],timeout=120) as response:data=response.read()
    print(json.dumps(dict(artifact_id=args.artifact_id,zip_sha256=hashlib.sha256(data).hexdigest())))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            if info.filename.endswith(('shared-solana-evidence.sqlite','shared-provider.sqlite','shared-robinhood-admission.sqlite')):
                with tempfile.TemporaryDirectory() as tmp:
                    path=Path(tmp)/'retained.sqlite';path.write_bytes(archive.read(info))
                    # Include retained WAL if present; inspection changes only a
                    # disposable copy, never the archived original evidence.
                    for suffix in ('-wal','-shm'):
                        if info.filename+suffix in archive.namelist():
                            Path(str(path)+suffix).write_bytes(archive.read(info.filename+suffix))
                    db=sqlite3.connect(path)
                    tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                    selected={}
                    for table in tables:
                        if not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',table):continue
                        columns=[r[1] for r in db.execute(f'PRAGMA table_info({table})')]
                        summary=dict(rows=db.execute(f'SELECT count(*) FROM {table}').fetchone()[0],columns=columns)
                        if 'status' in columns:
                            summary['status_counts']=dict(db.execute(f'SELECT status,count(*) FROM {table} GROUP BY status'))
                        if 'priority' in columns and 'status' in columns:
                            summary['priority_status_counts']=[list(r) for r in db.execute(f'SELECT priority,status,count(*) FROM {table} GROUP BY priority,status')]
                        selected[table]=summary
                    db.close();print('FINAL_SHARED_DATABASE '+json.dumps(dict(file=info.filename,tables=selected),sort_keys=True))
            if info.filename.endswith('/result.json'):
                print('CERTIFICATION_RESULT '+archive.read(info).decode())
            elif '/certification-smoke/' in info.filename and info.filename.endswith('/process.log'):
                text=archive.read(info).decode(errors='replace')[-14000:]
                text=re.sub(r'https?://[^\s\"\x27<>]+','[endpoint redacted]',text)
                print('LANE_PROCESS_TAIL '+info.filename+'\n'+text)
            elif info.filename.endswith('/robinhood-ramses-extended-market-report.json'):
                report=json.loads(archive.read(info));forced=report.get('forced_machinery') or {};life=report.get('connected_lifecycle') or {}
                selected={k:report.get(k) for k in ('status','boundary','natural_qualifier_found','unique_active_pools','frontier_discovery')}
                selected['natural_screens']=report.get('natural_screens')
                selected['forced_machinery']={k:forced.get(k) for k in ('mechanics_complete','boundary','pool','final_position','reconciliation')}
                selected['natural_lifecycle']={k:life.get(k) for k in ('status','boundary','ledger_final','ledger_reconciliation')}
                print('RAMSES_NATIVE_TERMINAL '+json.dumps(selected,sort_keys=True))
            elif info.filename.endswith('/status.json'):
                row=json.loads(archive.read(info));report=row.pop('report',None)
                print('LANE_STATUS '+json.dumps(row,sort_keys=True))
                if isinstance(report,dict):
                    selected={k:report[k] for k in ('frontier_discovery','summary','qualification_failure_counts','created_mints_observed','discovery_unique_pool_count','accounting','accounting_replay') if k in report}
                    print('LANE_REPORT_SUMMARY '+json.dumps(selected,sort_keys=True))


if __name__=='__main__':main()
