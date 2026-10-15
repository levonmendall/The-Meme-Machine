import argparse
import json
import os
from pathlib import Path

from .supervisor import Supervisor,validate_environment
from meme_machine.runtime.usd_valuation import ValuationUnavailable


def main():
    parser=argparse.ArgumentParser(description='Autonomous PAPER application; no signing or real transactions.')
    parser.add_argument('command',choices=('run','observe','bootstrap','normal','check','health','portfolio','offline'),nargs='?',default='run')
    parser.add_argument('--state-root',default=os.environ.get('MM_STATE_ROOT'))
    parser.add_argument('--seconds',type=float,help='Offline or observation duration; bootstrap has a fixed 1,800s hard limit.')
    args=parser.parse_args()
    if args.command=='check':
        try:validate_environment()
        except ValuationUnavailable as error:print(json.dumps(dict(paper_only=True,status='BLOCKED',blocker=str(error))));return 2
        return 0
    if not args.state_root:parser.error('MM_STATE_ROOT or --state-root is required')
    if args.command in ('health','portfolio'):
        print((Path(args.state_root)/(args.command+'.json')).read_text());return 0
    try:
        mode={'observe':'OBSERVATION','bootstrap':'BOOTSTRAP'}.get(args.command,'NORMAL')
        if args.seconds is not None and (args.command not in ('observe','offline') or args.seconds<=0):
            parser.error('--seconds is positive and valid only for observe/offline')
        seconds=args.seconds if args.command in ('observe','offline') else None
        if args.command=='offline' and seconds is None:seconds=5
        if args.command=='observe' and seconds is None:parser.error('observation requires an explicit finite --seconds')
        Supervisor(args.state_root,offline=args.command=='offline',admission=mode).run(seconds=seconds)
    except ValuationUnavailable as error:
        print(json.dumps(dict(paper_only=True,status='BLOCKED',blocker=str(error))));return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
