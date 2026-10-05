"""Reuse finalized observation pages; retain receipt/state authority in the caller.

Uses the already approved public census endpoint and its existing one-request
batch/one-second pacing. It does not retry on another provider. A failed page is
never cached as empty. Cached rows are discovery evidence, never entry authority.
"""
import json
import sqlite3
from pathlib import Path

from . import BoundaryError
from .ramses_capture import BoundedMultiRpc

PAGE_BLOCKS=1000
MAX_CACHE_PAGES=8192
MAX_CACHE_BYTES=64*1024*1024
DEFAULT_CACHE=Path('robinhood-ramses-lifecycle-log-cache.sqlite')


def collect(start,end,address,*,topics=None,max_logs=5000,cache_path=DEFAULT_CACHE,
            reader_factory=BoundedMultiRpc):
    if start>end:return []
    pages=[(first,min(end,first+PAGE_BLOCKS-1))
           for first in range(start,end+1,PAGE_BLOCKS)]
    if len(pages)>MAX_CACHE_PAGES:
        raise BoundaryError('connected_lifecycle_observation_page_capacity')
    cache_path=Path(cache_path)
    from contextlib import closing
    with closing(sqlite3.connect(cache_path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS log_pages (identity TEXT PRIMARY KEY, body TEXT NOT NULL)')
        def key(first,last):
            return json.dumps([str(address).lower(),first,last,topics],sort_keys=True,separators=(',',':'))
        missing=sum(db.execute('SELECT 1 FROM log_pages WHERE identity=?',(key(a,b),)).fetchone() is None for a,b in pages)
        rpc=None
        if missing:
            rpc=reader_factory(None,provider_role='public_observation',
                max_sessions=(missing+1+199)//200,batch_size=1,batch_pause=1,
                rate_retries=0,adaptive_batch_floor=1)
            rpc.verify_chain()
        found=[]
        for first,last in pages:
            identity=key(first,last)
            cached=db.execute('SELECT body FROM log_pages WHERE identity=?',(identity,)).fetchone()
            if cached:
                page=json.loads(cached[0])
            else:
                query=dict(fromBlock=hex(first),toBlock=hex(last),address=address)
                if topics is not None:query['topics']=topics
                page=rpc.batch([('eth_getLogs',[query])],scope='lifecycle_public_census')[0]
                if not isinstance(page,list):raise BoundaryError('connected_lifecycle_log_page_shape')
                if len(page)>max_logs:raise BoundaryError('connected_lifecycle_log_capacity')
                # Refuse out-of-window/foreign rows before persisting observation data.
                if any(str(e.get('address','')).lower()!=str(address).lower() or
                       not first<=int(e['blockNumber'],16)<=last or e.get('removed') is True
                       for e in page):
                    raise BoundaryError('connected_lifecycle_log_page_identity')
                raw=json.dumps(page,sort_keys=True,separators=(',',':'))
                if len(raw)>16*1024*1024:raise BoundaryError('connected_lifecycle_log_page_bytes')
                db.execute('INSERT INTO log_pages VALUES(?,?)',(identity,raw))
                db.commit()
            found.extend(page)
            if len(found)>max_logs:raise BoundaryError('connected_lifecycle_log_capacity')
        count=db.execute('SELECT COUNT(*) FROM log_pages').fetchone()[0]
        if count>MAX_CACHE_PAGES:
            db.execute('DELETE FROM log_pages WHERE rowid IN (SELECT rowid FROM log_pages ORDER BY rowid LIMIT ?)',
                (count-MAX_CACHE_PAGES,))
        while db.execute('SELECT COALESCE(SUM(LENGTH(body)),0) FROM log_pages').fetchone()[0]>MAX_CACHE_BYTES:
            db.execute('DELETE FROM log_pages WHERE rowid IN (SELECT rowid FROM log_pages ORDER BY rowid LIMIT 128)')
        return found
