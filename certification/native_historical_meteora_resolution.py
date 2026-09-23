"""Deterministically resolve one archived Meteora paper exposure on a disposable copy.

The original artifact is never mutated. This script runs under the exact historical
source+overlay worktree, denies network access, verifies the original journal/economic
replay, and applies the native append-only zero-proceeds writeoff transition.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--copy',required=True)
    p.add_argument('--expected-journal-hash',required=True)
    p.add_argument('--expected-reason',required=True)
    args=p.parse_args()

    def deny_network(event,values):
        if event in ('socket.connect','socket.sendto'):
            raise RuntimeError('historical_resolution_has_no_network_authority')
    sys.addaudithook(deny_network)
    sys.path.insert(0,os.getcwd())

    from meme_machine.dlmm_independent_accounting import PaperBook
    from tests import solana_dlmm_independent_v1 as strategy

    path=Path(args.copy)
    with sqlite3.connect(path) as db:
        rows=[json.loads(raw) for (raw,) in db.execute(
            'SELECT body FROM events ORDER BY seq')]
    if not rows or rows[0].get('action')!='genesis':
        raise ValueError('historical_genesis_missing')
    genesis=rows[0]['data']
    book=PaperBook(path,run_id=genesis['run_id'],
                   policy_hash=genesis['policy_hash'],capital=genesis['capital'])
    before=book.reconcile()
    if before['journal_hash']!=args.expected_journal_hash:
        raise ValueError('historical_resolution_journal_hash_mismatch')
    if (before['open_positions'],before['unsettled'],before['stale_marks'],
            before['writeoffs'])!=(1,1,1,0):
        raise ValueError('historical_resolution_expected_one_unresolved_position')
    last=rows[-1]
    if last.get('action')!='unresolved' or last.get('data',{}).get('reason')!=args.expected_reason:
        raise ValueError('historical_resolution_reason_mismatch')
    identity=last.get('identity')
    if not isinstance(identity,str) or not identity.startswith(
            'solana_meteora_independent_v1:'+genesis['run_id']+':'):
        raise ValueError('historical_resolution_identity_mismatch')

    economics=book.replay_economics(
        strategy._build_position,strategy._advance_position,strategy._mark)
    if not economics.get('verified') or int(economics.get('checked_economic_events') or 0)<1:
        raise ValueError('historical_resolution_economic_replay_failed')

    entry=next((row for row in rows if row.get('action')=='entry'
                and row.get('identity')==identity),None)
    if entry is None:raise ValueError('historical_resolution_entry_missing')
    basis=int(entry['data']['capital']);entry_cost=int(entry['data']['entry_cost'])
    expected_loss=-(basis+entry_cost)

    disposition='certified_historical_unreplayable_zero_proceeds_writeoff'
    book.append(identity,'writeoff',
        dict(reason=disposition+':'+args.expected_reason),
        at_ns=int(before['capital_time_through_ns']))
    after=book.reconcile()
    if (after['open_positions'],after['unsettled'],after['stale_marks'],
            after['reserved'],after['writeoffs'])!=(0,0,0,0,1):
        raise ValueError('historical_resolution_writeoff_not_terminal')
    if after['cash']!=before['cash'] or after['realized_pnl_lamports']!=expected_loss:
        raise ValueError('historical_resolution_cash_or_loss_mismatch')
    if after['available']!=after['cash'] or after['marked_equity']!=after['cash']:
        raise ValueError('historical_resolution_terminal_equity_mismatch')

    code=Path('meme_machine/dlmm_independent_accounting.py')
    receipt=dict(
        scope='digest_pinned_historical_copy_zero_proceeds_resolution',
        source_sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        overlay_sha256=hashlib.sha256(
            subprocess.check_output(['git','diff','--binary','HEAD'])).hexdigest(),
        accounting_source_sha256=hashlib.sha256(code.read_bytes()).hexdigest(),
        lifecycle_id=identity,
        original_journal_hash=before['journal_hash'],
        resolved_journal_hash=after['journal_hash'],
        unresolved_reason=args.expected_reason,
        disposition=disposition,
        market_settlement_performed=False,
        current_chain_reauthentication_performed=False,
        proceeds_lamports=0,
        economic_replay=economics,
        before=before,
        after=after,
    )
    receipt['receipt_sha256']=hashlib.sha256(canonical(receipt).encode()).hexdigest()
    print(json.dumps(receipt,sort_keys=True))


if __name__=='__main__':main()
