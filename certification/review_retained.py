"""Hash-verified artifact postprocessing, with no market or strategy authority."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import urllib.error
import urllib.request
import zipfile

from certification.inspect_artifact import NoRedirect
from certification.analysis import report
from certification.shadow import analyze


def review(artifact_id,expected_sha,output):
    request=urllib.request.Request(f'https://api.github.com/repos/levonmendall/The-Meme-Machine/actions/artifacts/{artifact_id}/zip',
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request,timeout=60) as response:data=response.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in (301,302,303,307,308):raise
        with urllib.request.urlopen(exc.headers['Location'],timeout=120) as response:data=response.read()
    if hashlib.sha256(data).hexdigest()!=expected_sha:raise ValueError('retained_artifact_digest_mismatch')
    output=Path(output);output.mkdir(parents=True,exist_ok=False);source=output/'source';source.mkdir()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        results=[x.filename for x in archive.infolist() if x.filename.endswith('/result.json')
                 and any(part.startswith('certification-') for part in PurePosixPath(x.filename).parts)]
        if len(results)!=1:raise ValueError('unique_certification_result_required')
        prefix=results[0].removesuffix('result.json')
        for info in archive.infolist():
            if not info.filename.startswith(prefix) or info.is_dir():continue
            relative=PurePosixPath(info.filename.removeprefix(prefix))
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('unsafe_artifact_path')
            path=source/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(info))
    capacity=report(source);shadow=analyze(source,output/'shadow',Path(__file__).with_name('shadow_registry.json'))
    (output/'artifact-identity.json').write_text(json.dumps(dict(artifact_id=artifact_id,sha256=expected_sha),indent=2)+'\n')
    print('CAPACITY_STRATEGY '+json.dumps(capacity,sort_keys=True))
    print('SHADOW_RESEARCH '+json.dumps(shadow,sort_keys=True))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--artifact-id',required=True,type=int);p.add_argument('--sha256',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();review(args.artifact_id,args.sha256,args.output)
