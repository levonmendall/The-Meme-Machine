import argparse
import json
import os
from pathlib import Path

from .supervisor import Supervisor,validate_environment
from meme_machine.runtime.usd_valuation import ValuationUnavailable


def main():
    parser=argparse.ArgumentParser(description='Autonomous PAPER application; no signing or real transactions.')
    parser.add_argument('command',choices=('run','check','health','portfolio','offline'),nargs='?',default='run')
    parser.add_argument('--state-root',default=os.environ.get('MM_STATE_ROOT'))
    parser.add_argument('--seconds',type=float,default=5,help='Offline fixture duration only.')
    args=parser.parse_args()
    if args.command=='check':
        try:validate_environment()
        except ValuationUnavailable as error:print(json.dumps(dict(paper_only=True,status='BLOCKED',blocker=str(error))));return 2
        return 0
    if not args.state_root:parser.error('MM_STATE_ROOT or --state-root is required')
    if args.command in ('health','portfolio'):
        print((Path(args.state_root)/(args.command+'.json')).read_text());return 0
    try:
        Supervisor(args.state_root,offline=args.command=='offline').run(seconds=args.seconds if args.command=='offline' else None)
    except ValuationUnavailable as error:
        print(json.dumps(dict(paper_only=True,status='BLOCKED',blocker=str(error))));return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
