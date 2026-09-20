"""Read-only retained artifact review; never imports a market lane."""
import argparse
import hashlib
import io
import json
import os
import re
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
            if info.filename.endswith('/result.json'):
                print('CERTIFICATION_RESULT '+archive.read(info).decode())
            elif '/certification-smoke/' in info.filename and info.filename.endswith('/process.log'):
                text=archive.read(info).decode(errors='replace')[-14000:]
                text=re.sub(r'https?://[^\s\"\x27<>]+','[endpoint redacted]',text)
                print('LANE_PROCESS_TAIL '+info.filename+'\n'+text)
            elif info.filename.endswith('/status.json'):
                row=json.loads(archive.read(info));report=row.pop('report',None)
                print('LANE_STATUS '+json.dumps(row,sort_keys=True))
                if isinstance(report,dict):
                    selected={k:report[k] for k in ('frontier_discovery','summary','qualification_failure_counts','created_mints_observed','discovery_unique_pool_count','accounting','accounting_replay') if k in report}
                    print('LANE_REPORT_SUMMARY '+json.dumps(selected,sort_keys=True))


if __name__=='__main__':main()
