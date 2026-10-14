"""Small identical temporary SQL workload; not a market-capacity benchmark.

Run only in an admitted offline scratch scope under coordinated host testing.
The caller owns containment and result publication. This module opens no
network, providers or authoritative state and has no command-line launcher.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from meme_machine.runtime.sqlite_failure import connect


def compare(directory,*,transactions=128,rows_per_transaction=32):
    directory=Path(directory)
    if not 1<=transactions<=256 or not 1<=rows_per_transaction<=64:
        raise ValueError('sqlite_recorder_offline_comparison_bound')
    result={}
    for variant in ('native','instrumented'):
        path=directory/(variant+'.sqlite')
        if path.exists():raise ValueError('sqlite_recorder_fixture_must_be_new')
        factory=sqlite3.connect if variant=='native' else lambda path,**kwargs:connect(
            path,diagnostic_role='offline_overhead',**kwargs)
        with closing(factory(path,isolation_level=None,timeout=0)) as db:
            db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE records(identity INTEGER PRIMARY KEY,value TEXT)')
            statements=[0]
            def count(_sql):statements[0]+=1
            db.set_trace_callback(count)
            wall=time.monotonic();cpu=time.process_time()
            for batch in range(transactions):
                db.execute('BEGIN IMMEDIATE')
                db.executemany('INSERT INTO records VALUES(?,?)',[
                    (batch*rows_per_transaction+i,'authenticated-fixture-'+str(i))
                    for i in range(rows_per_transaction)])
                db.execute('SELECT value FROM records WHERE identity=?',(batch*rows_per_transaction,)).fetchone()
                db.execute('COMMIT')
            elapsed=time.monotonic()-wall;cpu_elapsed=time.process_time()-cpu
            db.set_trace_callback(None)
            rows=db.execute('SELECT identity,value FROM records ORDER BY identity').fetchall()
            result[variant]=dict(wall_seconds=elapsed,cpu_seconds=cpu_elapsed,sql_statements=statements[0],
                rows=len(rows),ordered_output_sha256=hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest())
    result['scope']='synthetic identical SQL workload; no whole-machine or market-throughput claim'
    result['equivalent']=(result['native']['ordered_output_sha256']==result['instrumented']['ordered_output_sha256'] and
        result['native']['sql_statements']==result['instrumented']['sql_statements'])
    return result
