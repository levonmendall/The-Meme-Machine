"""Read-only shared Solana reuse telemetry; raw consumer history remains intact."""
import sqlite3,time
from pathlib import Path
class SolanaReuseView:
    def __init__(self,path):self.path=Path(path);self.at=0;self.value={}
    def snapshot(self):
        if time.monotonic()-self.at<10:return self.value
        if not self.path.exists():return {}
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
        try:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'immutable_transactions','signature_interests','immutable_reuse'}<=tables:return {}
            lanes={}
            for lane in ('pump','meteora'):
                hits=dict(db.execute('SELECT kind,count FROM immutable_reuse WHERE lane=?',(lane,)))
                reads=[dict(method=m,kind=k,count=n) for m,k,n in db.execute('SELECT method,kind,count(*) FROM solana_reuse_events WHERE lane=? GROUP BY method,kind',(lane,))] if 'solana_reuse_events' in tables else []
                lanes[lane]=dict(unique_signatures_requested=db.execute('SELECT count(*) FROM signature_interests WHERE lane=?',(lane,)).fetchone()[0],
                    unique_bodies_hydrated=db.execute('SELECT count(*) FROM immutable_transactions WHERE lane=?',(lane,)).fetchone()[0],
                    reuse=hits,immutable_read_events=reads)
            self.value=dict(lanes=lanes,unique_signatures_observed=db.execute('SELECT count(DISTINCT signature) FROM stream_signature_archive').fetchone()[0],unique_bodies_hydrated=db.execute('SELECT count(*) FROM immutable_transactions').fetchone()[0],
                unique_signatures_requested=db.execute('SELECT count(DISTINCT signature) FROM signature_interests').fetchone()[0],
                interpretation='Hydration attributed to executing lane; cross-lane consumers share the same durable body. Consumer expirations are not unique opportunities.')
            self.at=time.monotonic();return self.value
        finally:db.close()
