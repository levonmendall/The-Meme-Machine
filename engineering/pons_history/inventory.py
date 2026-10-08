"""Audit individually selected evidence databases through verified isolated copies.

No provider client, source SQLite connection, money-book copy or collection copy.
The input catalog is a read-only main-file schema screen, not a completeness proof.
Nonempty WALs are copied beside their main files and replayed only in isolation.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from meme_machine.runtime.journal import digest
from meme_machine.lanes.pons.pons_history import PonsHistory
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def audit(catalog, output):
    output.mkdir(parents=True, exist_ok=True)
    sources = []
    copies = {}
    for entry in catalog['files']:
        tables = entry.get('tables', [])
        if not ('pons_graduation_intake' in tables or 'gas_quotes' in tables
                or 'observation_counts' in tables and 'evidence' in tables):
            continue
        source = Path(entry['path'])
        wal = Path(str(source) + '-wal')
        original = dict(main=sha(source), wal=sha(wal) if wal.exists() else None)
        key = digest(original)
        if key not in copies:
            target = output / (key + '.sqlite')
            if target.exists():
                raise ValueError('inventory_output_already_exists')
            shutil.copyfile(source, target)
            if wal.exists():
                shutil.copyfile(wal, Path(str(target) + '-wal'))
            if sha(source) != original['main'] or wal.exists() and sha(wal) != original['wal']:
                raise ValueError('inventory_source_changed_during_copy')
            db = sqlite3.connect(target)
            result = dict(integrity_check=db.execute('PRAGMA integrity_check').fetchone()[0],
                          schema=tables, economic_state_reuse=False)
            if 'pons_graduation_intake' in tables:
                db.close()
                h = PonsHistory(target, policy=POLICY_HASH)
                result['counts'] = {t:h.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]
                                    for t in ('candidates','events','points','pons_graduation_intake')}
                result['meta'] = {k:h.get_meta(k) for k in ('policy','discovery_block',
                    'discovery_block_hash','discovery_bootstrap','graduation_floor')}
                for body, checksum in h.db.execute('SELECT body,hash FROM meta'):
                    h._verified((body,checksum))
                for row in h.rows(include_retired=True):
                    h.facts(row['id'],row.get('through',row['graduation']['at']))
                result.update(replay='PASS', reusable_complete_ranges=[], complete_seed=False,
                              missing='no completed census or candidate histories')
                h.close()
            elif 'gas_quotes' in tables:
                methods = Counter()
                headers = []
                logs = []
                domains = set()
                for domain,key_,body,created in db.execute('SELECT domain,key,body,created FROM evidence'):
                    k,v = json.loads(key_),json.loads(body)
                    methods[k[0]] += 1
                    domains.add(domain)
                    if k[0] == 'eth_getBlockByHash':
                        if v['hash'] != k[1][0]:
                            raise ValueError('inventory_header_key_disagreement')
                        headers.append(dict(block=int(v['number'],16),at=int(v['timestamp'],16),hash=v['hash']))
                    if k[0] == 'eth_getLogs':
                        q = k[1][0]
                        if q.get('blockHash') and any(e['blockHash'] != q['blockHash'] or e.get('removed') for e in v):
                            raise ValueError('inventory_log_key_disagreement')
                        logs.append(dict(query=q,events=len(v),identities=[
                            [e['blockHash'],e['transactionHash'],e['logIndex']] for e in v]))
                result.update(methods=dict(methods),domains=sorted(domains),
                    header_count=len(headers), header_bounds=None if not headers else dict(
                        first=min(h['block'] for h in headers), last=max(h['block'] for h in headers),
                        earliest=min(h['at'] for h in headers), latest=max(h['at'] for h in headers)),
                    log_ranges=logs, reusable_complete_ranges=[], complete_seed=False,
                    missing='isolated immutable facts do not establish a launch/graduation census or economic continuity')
                db.close()
            else:
                result['counts'] = {t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]
                                   for t in ('candidates','observations','evidence','rolling') if t in tables}
                result.update(complete_seed=False,reusable_complete_ranges=[],
                              missing='Current/candidate retention has no independent seven-day graduation census')
                db.close()
            copies[key] = result
        sources.append(dict(path=str(source), bytes=source.stat().st_size,
                            wal_bytes=wal.stat().st_size if wal.exists() else 0,
                            sha256=original, copy_key=key, **copies[key]))
        if sha(source) != original['main'] or wal.exists() and sha(wal) != original['wal']:
            raise ValueError('inventory_original_mutated')
    return dict(schema='pons-history-source-audit-v1', screened_databases=len(catalog['files']),
        audited_sources=len(sources), isolated_distinct_copies=len(copies),
        complete_authenticated_seed_found=False, production_economic_state_mutation=False,
        sources=sources, limitation='off-host snapshot content and unmounted/unavailable artifacts are not independently restored')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--copies',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    result=audit(json.loads(args.catalog.read_text()),args.copies)
    args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='sources'}))


if __name__=='__main__':main()
