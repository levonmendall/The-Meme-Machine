"""Reconcile a disposable archived book with its original pinned native code.

No controller resume, current-policy migration, writeoff, or settlement occurs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def main():
    p=argparse.ArgumentParser();p.add_argument('--copy',required=True);args=p.parse_args()
    def deny_network(event,values):
        if event in ('socket.connect','socket.sendto'):
            raise RuntimeError('historical_replay_has_no_network_authority')
    sys.addaudithook(deny_network)
    sys.path.insert(0,os.getcwd())
    from meme_machine.dlmm_independent_accounting import PaperBook
    path=Path(args.copy)
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        first=json.loads(db.execute('SELECT body FROM events ORDER BY seq LIMIT 1').fetchone()[0])
    if first.get('action')!='genesis':raise ValueError('historical_genesis_missing')
    genesis=first['data']
    book=PaperBook(path,run_id=genesis['run_id'],policy_hash=genesis['policy_hash'],capital=genesis['capital'])
    result=book.reconcile()
    from tests import solana_dlmm_independent_v1 as strategy
    try:
        economics=book.replay_economics(strategy._build_position,strategy._advance_position,strategy._mark)
    except Exception as exc:
        economics=dict(verified=False,error_type=type(exc).__name__)
    code=Path('meme_machine/dlmm_independent_accounting.py')
    print(json.dumps(dict(scope='original_native_book_reconciliation_only',
        source_sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        overlay_sha256=hashlib.sha256(subprocess.check_output(['git','diff','--binary','HEAD'])).hexdigest(),
        accounting_source_sha256=hashlib.sha256(code.read_bytes()).hexdigest(),
        result=result,economic_replay=economics,
        settlement_performed=False,monitoring_resumed=False),sort_keys=True))


if __name__=='__main__':main()
