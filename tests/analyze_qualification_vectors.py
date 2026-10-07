"""Aggregate saved shadow qualification reports without granting trading authority."""
import argparse
import json
import zipfile
from pathlib import Path

from meme_machine.research import analyze_reports


def load_reports(paths):
    reports=[]
    for raw in paths:
        path=Path(raw)
        if path.suffix.lower()=='.zip':
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name.endswith('.json'):
                        reports.append(json.loads(archive.read(name)))
        elif path.is_dir():
            for child in sorted(path.rglob('*.json')):
                reports.append(json.loads(child.read_text()))
        else:
            reports.append(json.loads(path.read_text()))
    return reports


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('paths',nargs='+')
    ap.add_argument('--min-sample',type=int,default=50)
    args=ap.parse_args()
    if args.min_sample < 1:
        ap.error('--min-sample must be positive')
    result=analyze_reports(load_reports(args.paths),min_sample=args.min_sample)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
