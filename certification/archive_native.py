"""Collect explicit public paper artifacts; never copy worktree credentials."""
import argparse
from pathlib import Path
import shutil

PATTERNS={
    'pump':['pump-acceleration-natural-prospective*'],
    'meteora':['solana-dlmm-independent-v1-live*'],
    'pons':['pons-selective-continuation-v1-cohort.json','pons-selective-continuation-v1-cohort'],
    'ramses':['robinhood-ramses-extended-market-report.json','robinhood-ramses-extended-market.sqlite*',
              'robinhood-ramses-all-pool-inventory-cache.json'],
}

def collect(worktrees,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    for lane,patterns in PATTERNS.items():
        target=output/lane;target.mkdir(exist_ok=True)
        for pattern in patterns:
            for source in (Path(worktrees)/lane).glob(pattern):
                if source.is_symlink():raise ValueError('artifact_symlink_forbidden')
                if source.is_dir():shutil.copytree(source,target/source.name,dirs_exist_ok=True)
                else:shutil.copy2(source,target/source.name)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--worktrees',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();collect(args.worktrees,args.output)
