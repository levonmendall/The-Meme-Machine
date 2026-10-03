"""Native restart witness on the actual C DB, never a substitute fixture."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3

from core import REAL_NS, canonical, file_sha, relative, require
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


def capture_stale_refusals(plane, scopes, output, *, generation):
    """Bind native observations to a backup of their pinned SQLite read state.

    All scopes share one read transaction and raw backup. The exact timestamp
    comes from RuntimeEvidence's actual predicate result, never a later clock
    read. This runs before native close and cannot release a source frame.
    """
    from meme_machine.solana_evidence_plane import EvidenceUnavailable
    output = Path(output)
    preserved = output/'refusal-native-state'
    require(not preserved.exists(), 'refusal_preservation_reused')
    require(plane.reader is not None, 'refusal_native_reader_missing')
    db = plane.reader.db
    db.execute('BEGIN')
    try:
        health = {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM service_health')}
        phase = health.get('phase')
        actual_generation = health.get('storage_maintenance',{}).get('maintenance_arbiter',{}).get('generation')
        require(phase == 'WARMING' and actual_generation == generation and generation,
                'refusal_restart_lifecycle_or_generation')
        observations = []
        for scope in scopes:
            try:
                plane.require_usable(scope)
            except EvidenceUnavailable as exc:
                observed = plane.health_observations.get(scope)
                require(observed is not None and observed['scope'] == scope and observed['usable'] is False
                        and observed['reason'] == str(exc), 'refusal_native_observation_missing')
                # Freeze each native result before any later observation.
                observations.append(json.loads(canonical(observed)))
            else:
                raise ValueError('restart_stale_authority_was_usable')
        require(observations, 'restart_stale_authority_refusal_missing')
        preserved.mkdir()
        path = preserved/'db'
        with closing(sqlite3.connect(path)) as target:
            db.backup(target)
            # The standalone backup contains committed WAL state. It needs no
            # mutable WAL sidecars when independently opened by the verifier.
            target.execute('PRAGMA journal_mode=DELETE')
    finally:
        db.execute('ROLLBACK')
    path.chmod(0o400)
    with path.open('rb') as copied:
        os.fsync(copied.fileno())
    fsync_dir(preserved)
    digest = file_sha(path)
    refusals = []
    for index, observed in enumerate(observations,1):
        record = dict(version='v3-native-refusal-observation',scope=observed['scope'],reason=observed['reason'],
            observed_at=observed['observed_at'],phase=phase,generation=generation,observation=observed,
            raw_state_path='refusal-native-state/db',raw_state_sha256=digest,raw_state_bytes=path.stat().st_size)
        name = f'refusal-native-state/r{index}.json'
        receipt_sha256 = persist(relative(output,name),record)
        refusals.append(dict(record,receipt_path=name,receipt_sha256=receipt_sha256))
    fsync_dir(output)
    return refusals


def restart_witness(path, output, *, native_failure, failure_frames):
    """Only future C calls this after native teardown; zero further input released."""
    from meme_machine import solana_evidence_service as service
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from meme_machine.solana_maintenance_runtime import MaintenanceRuntime
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
        new_generation = state.fence.session
        plane = RuntimeEvidence(path, owner='meteora')
        try:
            scopes = [scope for scope in ('program:meteora', 'program:pump', 'program:pumpswap')
                      if type(before['health'].get('finalized_frontier:'+scope,{}).get('slot')) is int]
            stale_refusals = capture_stale_refusals(plane,scopes,output,generation=new_generation)
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
