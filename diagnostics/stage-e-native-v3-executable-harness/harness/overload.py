"""Native restart witness on the actual C DB, never a substitute fixture."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3

from core import REAL_NS, canonical, require, sha
from preserve import inventory, persist, fsync_dir


def snapshot(path):
    from production import read_snapshot
    row = read_snapshot(path)
    require(row is not None, 'restart_native_DB_missing')
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as db:
        tables = {name: [list(r) for r in db.execute('SELECT * FROM '+name+' ORDER BY 1,2')]
                  for name in ('interests', 'service_interests', 'account_interest_floors', 'stream_receipts',
                               'interest_checkpoints', 'interest_owners', 'consumers')}
        tables['integrity'] = [r[0] for r in db.execute('PRAGMA integrity_check')]
        rows = db.execute('SELECT identity,hash,scope,slot,archive,market_time,first_seen FROM records ORDER BY identity')
        h = __import__('hashlib').sha256()
        count = 0
        for record in rows:
            h.update(canonical(list(record))+b'\n'); count += 1
    row.update(protected=tables, records_digest=h.hexdigest(), record_count=count)
    return row


def restart_witness(path, output, *, native_failure, failure_frames):
    """Only future C calls this after native teardown; zero further input released."""
    from meme_machine import solana_evidence_service as service
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from meme_machine.solana_maintenance_runtime import MaintenanceRuntime
    from meme_machine.solana_evidence_plane import EvidenceUnavailable
    from meme_machine.solana_evidence_runtime import RuntimeEvidence
    import bound_runtime as bound
    path, output = Path(path), Path(output)
    before = snapshot(path)
    original = output/'before-restart-native-state'
    require(not original.exists(), 'restart_preservation_reused')
    shutil.copytree(path.parent, original)
    for item in original.rglob('*'):
        if item.is_file():
            with item.open('rb') as copied:
                os.fsync(copied.fileno())
    for folder in sorted([original]+[p for p in original.rglob('*') if p.is_dir()], reverse=True):
        fsync_dir(folder)
    persist(output/'BEFORE_RESTART_INVENTORY.json', dict(artifacts=inventory(original)))
    old_generation = before['health'].get('storage_maintenance', {}).get('maintenance_arbiter', {}).get('generation')
    require(old_generation, 'native_generation_missing')
    # Reopen the same native state. Its constructor performs the conservative
    # service_restart fence; its native runtime reconstructs the durable ledger.
    state = service.ServiceState(path, AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
    try:
        runtime = MaintenanceRuntime(state)
        after = snapshot(path)
        new_generation = state.fence.session
        stale_refusals = []
        plane = RuntimeEvidence(path, owner='meteora')
        try:
            for scope in ('program:meteora', 'program:pump', 'program:pumpswap'):
                frontier = before['health'].get('finalized_frontier:'+scope, {}).get('slot')
                if type(frontier) is not int:
                    continue
                try:
                    plane.require_usable(scope)
                except EvidenceUnavailable as exc:
                    stale_refusals.append(dict(scope=scope, reason=str(exc)))
        finally:
            plane.close()
    finally:
        state.close()
    after = snapshot(path)
    # No archive/retirement mutation is invoked by this witness. Incomplete
    # attempts receive zero service; committed rows/receipts remain identical.
    return dict(version='v3-actual-native-restart', runtime_path=str(path),
        before=before, after=after, old_generation=old_generation, new_generation=new_generation,
        native_failure=native_failure, native_failure_frames=failure_frames,
        preserved_original_inventory_sha256=__import__('core').file_sha(output/'BEFORE_RESTART_INVENTORY.json'),
        stale_refusals=stale_refusals, source_frames_released_after_restart=0,
        external_stop_is_native_proof=False, real_monotonic_ns=REAL_NS())
