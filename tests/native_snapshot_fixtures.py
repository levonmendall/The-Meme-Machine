"""Disposable SQLite backups and native count projections for recovery tests."""
from contextlib import closing
from pathlib import Path
import collections,hashlib,json,sqlite3
from meme_machine.runtime.survivor_terminal_archive import metrics

def copy_snapshot(source,target,records):
    with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True)) as original:
        with closing(sqlite3.connect(target)) as copy:
            original.backup(copy)
            assert copy.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    records.append({'source':str(source),'target':str(target),'sha256':hashlib.sha256(Path(target).read_bytes()).hexdigest()})

def native_bytes(db):
    # Separate the economic B-trees from independently bounded observation
    # tables added since the historical fixture's total-file size assertion.
    # Learning has independent row/byte limits and a whole-file plateau test;
    # this measure keeps the original exact economic-prefix size contract.
    return db.execute("SELECT SUM(pgsize) FROM dbstat WHERE name='sqlite_schema' OR name IN (SELECT name FROM sqlite_master WHERE tbl_name NOT LIKE 'opportunity_%' AND tbl_name NOT LIKE 'learning_%')").fetchone()[0]

def native_counts(book):
    anchor=book._archive() or {}
    result=dict(anchor.get('folded',{}).get('metrics',{}))
    actions={identity:collections.Counter(proof['actions']) for identity,proof in anchor.get('journal_proofs',{}).items()}
    for encoded, in book.db.execute('SELECT body FROM journal ORDER BY seq'):
        row=json.loads(encoded);identity=row['position']['id']
        actions.setdefault(identity,collections.Counter())[row['action']]+=1
    for identity,encoded in book.db.execute('SELECT id,body FROM positions'):
        for key,value in metrics({'actions':actions[identity]},json.loads(encoded)).items():
            result[key]=result.get(key,0)+value
    return {key:value for key,value in result.items() if value}
