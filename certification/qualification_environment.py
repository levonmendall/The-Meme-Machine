"""Fail before an authoritative fixed trial when the frozen runner is different."""
from __future__ import annotations
import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess

PYTHON='3.12.14'
DEPENDENCIES={'websockets':'17.1'}
POLICY_PREDECESSOR='af60b355995dfa960555288fa73808bb7aba5d25'
ROOT=Path(__file__).resolve().parents[1]


def inspect():
    dependencies={}
    for name in DEPENDENCIES:
        try:dependencies[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:dependencies[name]=None
    python=platform.python_version()
    history=subprocess.run(['git','cat-file','-e',POLICY_PREDECESSOR+':certification/sources.json'],
        cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    failures=[]
    if python!=PYTHON:failures.append('frozen_python_mismatch')
    if dependencies!=DEPENDENCIES:failures.append('frozen_dependencies_mismatch')
    if not history:failures.append('required_policy_predecessor_missing')
    return dict(passed=not failures,failures=failures,python=python,expected_python=PYTHON,
        dependencies=dependencies,expected_dependencies=DEPENDENCIES,
        policy_predecessor_available=history,canonical_authority=False,market_authority=False)


def require():
    row=inspect()
    if not row['passed']:raise RuntimeError('qualification_environment_blocked:'+','.join(row['failures']))
    return row


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    row=inspect();target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(row,indent=2)+'\n');print(json.dumps(row,sort_keys=True))
    return 0 if row['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
