"""Read-only, digest-pinned inventory of retained historical paper evidence.

This does not reconstruct runner state, certify accounting, or assert that the
latest running campaign is flat. Only copies of archived databases are opened.
"""
import argparse
import collections
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import urllib.error
import urllib.request
import zipfile

from certification.inspect_artifact import NoRedirect


SAFE_KEYS = frozenset(('status', 'phase', 'lane', 'paper_only', 'integration_sha',
    'strategy_domain', 'strategy_version', 'policy_hash', 'cash', 'available',
    'reserved', 'basis', 'realized', 'unrealized', 'equity', 'open', 'settled',
    'unresolved', 'open_positions', 'unresolved_positions', 'active', 'positions',
    'position_count', 'tokens', 'amount', 'cost', 'pnl', 'accounting_reconciled',
    'replay_verified', 'verified', 'initial', 'paper_capital', 'final_hash',
    'source_sha', 'passed', 'success', 'total_positions', 'reserves',
    'starting_capital', 'net_result_quote', 'quote_asset', 'terminal'))


def scalars(body):
    return {k: v for k, v in body.items() if k in SAFE_KEYS
            and (v is None or type(v) in (str, int, float, bool))
            and not (isinstance(v, str) and (len(v) > 200 or '://' in v))}


def inspect_archive(data, artifact_id, expected):
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError('historical_artifact_digest_mismatch')
    result = dict(artifact_id=artifact_id, sha256=actual,
        scope='one_historical_artifact_only_not_current_running_state',
        accounting_recovery_certified=False, databases=[], reports=[])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        for info in archive.infolist():
            if info.filename.endswith(('.sqlite', '.sqlite3', '.db')):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / 'copy.sqlite'
                    path.write_bytes(archive.read(info))
                    for suffix in ('-wal', '-shm'):
                        if info.filename + suffix in names:
                            Path(str(path)+suffix).write_bytes(archive.read(info.filename+suffix))
                    db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
                    row = dict(file=info.filename,
                        quick_check=[r[0] for r in db.execute('PRAGMA quick_check')], tables={})
                    for table, in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                        if not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*', table):
                            continue
                        columns = [r[1] for r in db.execute(f'PRAGMA table_info({table})')]
                        summary = dict(rows=db.execute(f'SELECT count(*) FROM {table}').fetchone()[0])
                        if 'status' in columns:
                            summary['status_counts'] = dict(db.execute(f'SELECT status,count(*) FROM {table} GROUP BY status'))
                        # Do not emit raw evidence, endpoints, or arbitrary bodies.
                        # Projection tables only; journal rows are not positions.
                        if table in ('positions', 'pons_selective_paper', 'ramses_strategy_position') and 'body' in columns:
                            states = collections.Counter()
                            projections = []
                            for raw, in db.execute(f'SELECT body FROM {table}'):
                                body = json.loads(raw)
                                states[str(body.get('status', body.get('phase', 'unknown')))] += 1
                                projections.append(scalars(body))
                            summary.update(projection_states=dict(states), projections=projections)
                        row['tables'][table] = summary
                    db.close()
                    result['databases'].append(row)
            elif info.filename.endswith(('/result.json', '/status.json')):
                body = json.loads(archive.read(info))
                if not isinstance(body, dict):
                    continue
                row = dict(file=info.filename, summary=scalars(body))
                for key in ('lanes', 'accounting', 'accounting_replay', 'gates'):
                    value = body.get(key)
                    if isinstance(value, dict):
                        row[key] = {k: scalars(v) if isinstance(v, dict) else v
                            for k, v in value.items() if isinstance(v, dict) or type(v) in (int, bool)}
                result['reports'].append(row)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--artifact-id', type=int, required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    url = f'https://api.github.com/repos/levonmendall/The-Meme-Machine/actions/artifacts/{args.artifact_id}/zip'
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer '+os.environ['GITHUB_TOKEN'],
        'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise RuntimeError(f'historical_artifact_http_{exc.code}') from None
        # Do not forward the GitHub token to signed artifact storage.
        with urllib.request.urlopen(exc.headers['Location'], timeout=60) as response:
            data = response.read()
    result = inspect_archive(data, args.artifact_id, args.sha256)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    print('HISTORICAL_INVENTORY '+json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
