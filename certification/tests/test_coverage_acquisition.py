"""Integration evidence exposes source timeliness and pending consumer work."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from certification.market_assurance import meteora_source_coverage

class SourceEvidenceTests(unittest.TestCase):
    def test_late_page_never_expands_timely_union_and_backlog_stays_visible(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);native=root/'native';runtime=root/'runtime';source=root/'source'
            native.mkdir();(runtime/'meteora').mkdir(parents=True);(source/'tests').mkdir(parents=True)
            (source/'tests/solana_dlmm_independent_v1.py').write_text("DISCOVERY_SORTS=('a','b','c')\nDISCOVERY_PAGES_PER_SORT=2\nDISCOVERY_PAGE_SIZE=1\n")
            db=sqlite3.connect(native/'solana-dlmm-independent-v1-live.pipeline.sqlite')
            db.execute('CREATE TABLE progress(candidate,stage)')
            db.executemany('INSERT INTO progress VALUES(?,?)',[(str(i),'discovered') for i in range(6)])
            db.commit();db.close()
            db=sqlite3.connect(runtime/'meteora/telemetry.sqlite')
            db.execute('CREATE TABLE events(seq INTEGER PRIMARY KEY,at_ns,kind,body)')
            def event(sort,page,pool,at):
                body=dict(path='/pools',parameters=dict(sort_by=sort,page=page),response=dict(data=[dict(
                    address=pool,token_x={'address':'So11111111111111111111111111111111111111112'},token_y={'address':'token'})]))
                db.execute('INSERT INTO events(at_ns,kind,body) VALUES(?,?,?)',(at*10**9,'public_http_evidence',json.dumps(body)))
            for i,(sort,page) in enumerate((s,p) for s in ('a','b','c') for p in (1,2)):event(sort,page,str(i),10)
            event('a',1,'late-only-pool',20);db.commit();db.close()
            (native/'solana-dlmm-independent-v1-live.json').write_text(json.dumps(dict(
                discovery_acquisition=dict(observation_deadline_at=15,pending=4,first_seen=6,
                    oldest_pending_wait_seconds=5,segment_status_counts={'acquired':6,'late_response':1}))))
            report=meteora_source_coverage(runtime,native,source)
            self.assertTrue(report['census_complete'])
            self.assertEqual(report['acquired_source_pages'],6)
            self.assertEqual(report['structurally_eligible_acquired_union_count'],6)
            self.assertEqual(report['pending_discovered_candidates'],4)
            self.assertEqual(len(report['late_responses_excluded']),1)
            self.assertIsNone(report['full_strategy_target_universe_count'])

if __name__=='__main__':unittest.main()
