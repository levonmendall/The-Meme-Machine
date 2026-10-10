"""Dashboard-only oneshot: local read-only reports, one outbound HTTPS POST."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .snapshots import PHASES, SCHEMA, MAX_BYTES, utc, validate


def read(path, limit=MAX_BYTES):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise ValueError('publisher_input_capacity')
    return json.loads(raw)


def optional(path):
    try:
        return read(path)
    except (OSError, ValueError):
        return {'state': 'UNAVAILABLE'}


def service(unit):
    output = subprocess.check_output(['systemctl', 'show', unit, '-p', 'ActiveState',
        '-p', 'SubState', '-p', 'MainPID', '-p', 'NRestarts'], text=True, timeout=2)
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def acceptance(folder, candidate, epoch, now):
    from meme_machine.operational.observation import numeric
    phases = {}
    for phase in PHASES:
        pointer = Path(folder)/f'latest-{phase}.json'
        row = optional(pointer)
        required = {'CAPACITY': 3600, 'RECOVERY': None, 'AUTONOMY': 129600}[phase]
        fields = ('status', 'start_time', 'end_time', 'elapsed_seconds', 'required_seconds',
                  'observation_samples', 'exit_code', 'full_duration_completed', 'interrupted')
        previous = {k: row[k] for k in fields if k in row}
        previous['commit'] = row.get('identity', {}).get('commit')
        current = row.get('identity', {}).get('commit') == candidate and row.get('epoch_id') == epoch
        result = dict(status='NOT_STARTED', elapsed_seconds=0, required_seconds=required,
                      verified_result=False, service=service(f'meme-machine-acceptance@{phase}.service'))
        if row.get('state') == 'UNAVAILABLE' and pointer.exists():
            result['status'] = 'UNAVAILABLE'
        if current:
            result.update({k: row[k] for k in fields if k in row})
            if row.get('status') in ('STARTING', 'RUNNING'):
                if result['service']['ActiveState'] == 'active':
                    result['elapsed_seconds'] = max(0, now-row.get('start_timestamp', now))
                else:
                    result['status'] = 'INTERRUPTED'
            directory = Path(row.get('directory', ''))
            # Receipts refer only to a direct child of the acceptance directory.
            measurement = optional(directory/'result.json') if directory.parent == Path(folder) else {}
            result['results'] = numeric(measurement)
            result['verified_result'] = (row.get('status') == 'PASS' and row.get('exit_code') == 0
                and row.get('full_duration_completed') is True and measurement.get('passed') is True
                and (required is None or row.get('elapsed_seconds', 0) >= required))
            if result['status'] == 'PASS' and not result['verified_result']:
                result['status'] = 'UNAVAILABLE'
        elif previous.get('status'):
            result['previous_attempt'] = previous
        phases[phase] = result
    return phases


def portfolio_report(root):
    """Use the deployed runtime's validated reporting methods, never a writer."""
    from meme_machine.operational.observation import database, portfolio_summary
    from meme_machine.portfolio_accounting import PortfolioAccounting
    from meme_machine.portfolio_snapshot_transport import build_snapshot
    now = time.time()

    def replay(db):
        reader = object.__new__(PortfolioAccounting)
        reader.db = db
        state = reader._replay()
        export = reader._export(state)
        summary = portfolio_summary(reader, state, utc(now))
        # Marks are valued by the existing pure reader at actual read time.
        balances = dict(export['balances'], equity=summary['marked_equity'],
                        realized_pnl=summary['realized_pnl'], unrealized_pnl=summary['unrealized_pnl'])
        return dict(bundle=build_snapshot(state['receipt'], export),
            observation=dict(summary, state='CURRENT', at=utc(now), balances=balances))

    # Future shared-capital activation already has its own query-only reporter.
    shared = None
    try:
        from meme_machine.shared_capital.runtime import selected
        shared = selected(Path(root)/'portfolio.sqlite')
    except ImportError:
        pass
    if shared:
        from meme_machine.shared_capital.reporting import read_authority, export, summary
        def replay(db):
            reader = read_authority(db)
            projection = export(reader, at=int(now))
            facts = summary(reader, int(now))
            receipt = reader.snapshot(at=int(now))['ledger']['inception']
            return dict(bundle=build_snapshot(receipt, projection),
                observation=dict(facts, state='CURRENT', at=utc(now), balances=projection['balances']))
    result = database(shared or Path(root)/'portfolio.sqlite', replay, seconds=4)
    if result.get('state') == 'CURRENT':
        result.pop('state')
        return result
    # Keep the actual published export with its original expired deadlines.
    try:
        bundle = build_snapshot(read(Path(root)/'inception.json'), read(Path(root)/'portfolio.json'))
    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
        bundle = None
    return dict(bundle=bundle, observation=result)


def collect(root, runtime, candidate, publisher_commit,
            observer='/var/lib/meme-machine-observer/latest.json',
            monitor='/var/lib/meme-machine-monitor/status.json',
            receipts='/var/lib/meme-machine-acceptance'):
    epoch = read(Path(root)/'inception.json')['epoch_id']
    observed = optional(observer)
    watched = optional(monitor)
    deployed = subprocess.check_output(['git', '-C', str(runtime), 'rev-parse', 'HEAD'],
                                       text=True, timeout=2).strip()
    book = portfolio_report(root)
    now = time.time()
    value = dict(schema=SCHEMA, captured_at=utc(now),
        source=dict(candidate_commit=candidate, deployed_commit=deployed,
                    publisher_commit=publisher_commit, epoch_id=epoch),
        service=service('meme-machine-paper.service'), observer=observed, monitor=watched,
        acceptance=acceptance(receipts, candidate, epoch, now), portfolio=book)
    return validate(value, epoch=epoch, candidate=candidate)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def push(value, url, token):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('publisher_https_required')
    if parsed.path != '/api/dashboard/snapshot':
        raise ValueError('publisher_ingestion_path')
    raw = json.dumps(value, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('publisher_snapshot_capacity')
    request = Request(url, data=raw, method='POST', headers={
        'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'})
    # No redirects: the ingestion credential must stay on its configured host.
    with build_opener(NoRedirect).open(request, timeout=8) as response:
        if response.status != 202:
            raise ValueError('publisher_ingestion_rejected')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--print-only', action='store_true')
    args = parser.parse_args()
    try:
        value = collect(os.environ['MM_DASHBOARD_STATE_ROOT'],
                        os.environ.get('MM_DASHBOARD_RUNTIME', '/opt/meme-machine'),
                        os.environ['MM_DASHBOARD_CANDIDATE'], os.environ['MM_DASHBOARD_PUBLISHER_COMMIT'])
        if args.print_only:
            print(json.dumps(value, separators=(',', ':'), allow_nan=False))
        else:
            push(value, os.environ['MM_DASHBOARD_PUSH_URL'], os.environ['MM_DASHBOARD_INGEST_TOKEN'])
            print(json.dumps(dict(status='PUBLISHED', captured_at=value['captured_at'],
                                  deployed_commit=value['source']['deployed_commit'])))
        return 0
    except Exception as error:
        # Error text and request headers can contain credentials. Log type only.
        print(json.dumps(dict(status='UNAVAILABLE', error_type=type(error).__name__)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
