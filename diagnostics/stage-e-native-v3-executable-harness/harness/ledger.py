"""Fresh, consumed-on-start campaign ledger. Interrupted slots can never resume."""
import os
from pathlib import Path
import uuid

from core import MODES, REAL_NS, canonical, contract_file, read, require, sha
from preserve import fsync_dir, lock, persist


def trial_matrix(campaign, kind):
    require(kind in ('A', 'B', 'C'), 'ledger_class')
    prefix = 'stage-e-native-v3-' + {'A': 'capacity', 'B': 'observer', 'C': 'stress'}[kind] + '-'
    require(campaign.startswith(prefix), 'fresh_v3_namespace_required')
    seal = contract_file('historical_observer_seal.json')
    modes = MODES if kind == 'B' else ('baseline' if kind == 'A' else 'stress',)
    rows = [dict(sequence=i, trial_id=f'{campaign}-t{i:02d}', mode=mode)
            for i, mode in enumerate(modes, 1)]
    require(not {r['trial_id'] for r in rows}.intersection(seal['all_old_trial_ids_forbidden']), 'v2_trial_reuse')
    return rows


class Ledger:
    def __init__(self, path):
        self.path = Path(path)

    @classmethod
    def create(cls, registry, kind, declaration_sha256, campaign):
        root = Path(registry).resolve()
        root.mkdir(parents=True, exist_ok=True)
        matrix = trial_matrix(campaign, kind)
        # mkdir + immutable identity consumes this namespace even after a crash.
        folder = root / campaign
        folder.mkdir(exist_ok=False)
        fsync_dir(root)
        persist(folder / 'IDENTITY.json', dict(campaign=campaign, kind=kind,
                declaration_sha256=declaration_sha256, trials=matrix,
                history='OBSERVER_V2: INVALID_PAIR', retries=0, replacements=0))
        obj = cls(folder / 'LEDGER.jsonl')
        obj.append('CREATED', None, {})
        return obj

    def events(self):
        if not self.path.exists():
            return []
        data = self.path.read_bytes()
        require(data.endswith(b'\n'), 'torn_ledger_consumed_stop')
        import json
        lines = data.splitlines()
        rows = [json.loads(line) for line in lines]
        identity = read(self.path.parent/'IDENTITY.json')
        require(identity['trials'] == trial_matrix(identity['campaign'],identity['kind']), 'ledger_identity_matrix')
        previous = '0' * 64
        started, completed, terminal, prior_time = [], [], False, None
        for number, row in enumerate(rows, 1):
            raw = dict(row)
            digest = raw.pop('sha256')
            require(type(raw['ordinal']) is int and raw['ordinal'] == number and raw['previous'] == previous
                    and sha(canonical(raw)) == digest, 'ledger_chain')
            require(canonical(row) == lines[number-1], 'noncanonical_or_duplicate_ledger_key')
            require(type(raw['real_monotonic_ns']) is int and raw['real_monotonic_ns'] > 0
                    and (prior_time is None or raw['real_monotonic_ns'] > prior_time), 'ledger_clock')
            require(type(raw['details']) is dict and not terminal, 'ledger_terminal_or_details')
            event, sequence = raw['event'], raw['sequence']
            if event == 'CREATED':
                require(number == 1 and sequence is None, 'ledger_created_order')
            elif event == 'STARTED':
                require(number > 1 and type(sequence) is int and sequence == len(started)+1
                        and len(completed) == len(started) and sequence <= len(identity['trials']), 'ledger_start_order')
                started.append(sequence)
            elif event in ('COMPLETE_VALID','INVALID'):
                require(type(sequence) is int and started and sequence == started[-1]
                        and sequence not in completed, 'ledger_completion_order')
                if event == 'COMPLETE_VALID':
                    completed.append(sequence)
                else:
                    terminal = True
            elif event == 'STOPPED':
                require(number > 1 and sequence is None, 'ledger_stop_order')
                terminal = True
            else:
                raise ValueError('unknown_ledger_event')
            prior_time = raw['real_monotonic_ns']
            previous = digest
        return rows

    def append(self, event, sequence, details):
        with lock(self.path.with_suffix('.lock')):
            rows = self.events()
            identity = read(self.path.parent / 'IDENTITY.json')
            starts = [r['sequence'] for r in rows if r['event'] == 'STARTED']
            done = [r['sequence'] for r in rows if r['event'] == 'COMPLETE_VALID']
            require(not any(r['event'] in ('INVALID', 'STOPPED') for r in rows), 'terminal_campaign_no_reuse')
            if event == 'CREATED':
                require(not rows and sequence is None, 'duplicate_campaign_create')
            elif event == 'STARTED':
                require(type(sequence) is int and sequence == len(starts) + 1 and len(done) == len(starts)
                        and sequence <= len(identity['trials']), 'retry_replacement_or_incomplete_previous')
            elif event in ('COMPLETE_VALID', 'INVALID'):
                require(type(sequence) is int and starts and sequence == starts[-1] and sequence not in done,
                        'unstarted_or_duplicate_completion')
            elif event == 'STOPPED':
                require(sequence is None, 'stop_sequence')
            else:
                raise ValueError('unknown_ledger_event')
            raw = dict(ordinal=len(rows)+1, previous=rows[-1]['sha256'] if rows else '0'*64,
                       event=event, sequence=sequence, real_monotonic_ns=REAL_NS(), details=details)
            row = dict(raw, sha256=sha(canonical(raw)))
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as target:
                target.write(canonical(row) + b'\n')
                target.flush()
                os.fsync(target.fileno())
            fsync_dir(self.path.parent)
            self.events()
            return row


def fresh_campaign(kind):
    return 'stage-e-native-v3-' + {'A': 'capacity', 'B': 'observer', 'C': 'stress'}[kind] + '-' + uuid.uuid4().hex
