"""Fold acknowledged current-Pump sleeve terminals in an unsealed successor.

Current Pons uses its native cohort's joined terminal proof. Survivor archival is
unchanged. Native journals remain the evidence authority for this sleeve fold.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from certification.journal import canonical,digest
from certification.lifecycle_identity import parsed,scope


def compact(destination,artifact,window):
    from certification.autonomous_window import verify_snapshot,checksum
    from certification.robinhood.window_archive import _preserved
    from certification.sleeve_reservations import SleeveReservations
    from certification.survivor_terminal_archive import _sleeve_commit
    from meme_machine.paper_accounting import PaperBook
    from meme_machine.pump_acceleration_strategy import STRATEGY_ID,policy_hash
    root=Path(destination)/'files/pump';path=root/'directional-sleeve.sqlite'
    books=sorted(root.glob('*.accounting.sqlite3'))
    if not path.exists() or not books:return None
    if len(books)!=1:raise ValueError('current_sleeve_native_book_identity')
    snapshot=verify_snapshot(artifact);artifact=Path(artifact);prefix=artifact/('certification-native/'+snapshot['phase']+'/pump')
    inventory={artifact/r['target'] for r in snapshot['files'] if 'target' in r}
    _preserved(path,prefix/path.name,inventory);_preserved(books[0],prefix/books[0].name,inventory)
    book=object.__new__(PaperBook);book.lock=threading.RLock()
    book.db=sqlite3.connect(books[0].resolve().as_uri()+'?mode=ro',uri=True)
    sleeve=object.__new__(SleeveReservations);sleeve.lock=threading.RLock();sleeve.db=sqlite3.connect(path,isolation_level=None)
    try:
        book.identity=json.loads(book.db.execute('SELECT body FROM genesis WHERE id=1').fetchone()[0])
        if book.identity['lane']!=STRATEGY_ID or book.identity['policy_hash']!=policy_hash():raise ValueError('current_sleeve_policy_identity')
        replay=book.replay()
        if replay['verified'] is not True:raise ValueError('current_sleeve_native_replay')
        native={i:json.loads(b) for i,b in book.db.execute('SELECT id,body FROM positions')}
        sleeve.identity=json.loads(sleeve.db.execute('SELECT body FROM sleeve_genesis WHERE id=1').fetchone()[0])
        before=sleeve.reconcile();campaign=scope(window);fence=dict(campaign=campaign['campaign'],through=campaign['index'])
        retired={}
        for identity,position in native.items():
            issued=parsed(identity)
            if (not issued or issued['campaign']!=fence['campaign'] or issued['index']>fence['through']
                    or position['status'] not in ('settled','cancelled')):continue
            held=sleeve.get(identity)
            if held is None:continue  # Already folded; native replay cannot reserve again.
            if (held['strategy']!=STRATEGY_ID or held['status']!='settled' or held['held']
                    or held['pnl']!=position['realized'] or held.get('terminal_hash')!=digest(position)):
                raise ValueError('current_sleeve_native_acknowledgement')
            if any(position[k] for k in ('tokens','reserved','basis')):raise ValueError('current_sleeve_native_exposure')
            retired[identity]=held
        if not retired:return None
        authority=dict(state_hash=digest(snapshot),snapshot_sha256=checksum(prefix/path.name),
            artifact={'digest':'sha256:'+digest(snapshot)},campaign_id=window['campaign_id'],
            authorization_hash=window['authorization_hash'],window_index=window['index'])
        sleeve._compact_preserved(prefix/path.name,authority)
        plan=dict(schema='current-sleeve-terminal-retirement-v1',scope=fence,strategy=STRATEGY_ID,
            state_hash=authority['state_hash'],artifact=authority['artifact'],sleeve_positions=retired,candidates={})
        plan['hash']=digest(plan)
        _sleeve_commit(sleeve,plan)
        if sleeve.reconcile()!=before:raise ValueError('current_sleeve_accounting_changed')
        return dict(schema=plan['schema'],retired=len(retired),retired_hash=digest(retired),
            preserved_snapshot_hash=digest(snapshot),scope=fence)
    finally:book.close();sleeve.close()


def externalize(destination,artifact,window,source_root):
    root=Path(destination)/'files/pump'
    if not (root/'directional-sleeve.sqlite').exists() or not list(root.glob('*.accounting.sqlite3')):return None
    env={k:v for k,v in os.environ.items() if not k.startswith('MM_')};env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])
    result=subprocess.run([sys.executable,'-m','certification.current_sleeve_archive',str(Path(destination).resolve()),str(Path(artifact).resolve()),canonical(window)],
        cwd=source_root,env=env,capture_output=True,text=True,timeout=60)
    if result.returncode:raise ValueError('current_sleeve_archive_failed:'+result.stderr[-2000:])
    return json.loads(result.stdout)

if __name__=='__main__':
    sys.path.insert(0,os.getcwd())
    from certification.offline_tests import install_network_guard
    install_network_guard()
    print(canonical(compact(sys.argv[1],sys.argv[2],json.loads(sys.argv[3]))))
