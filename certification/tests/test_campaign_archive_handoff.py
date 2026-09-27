"""Only live archive references cross windows; all raw evidence stays preserved."""
import json
from pathlib import Path
import sqlite3
import unittest

from certification import campaign_state as state
from certification.autonomous_window import stage
from meme_machine.solana_evidence_plane import EvidenceWriter, EvidenceReader
from tests.test_solana_evidence_plane import record,proof

class CampaignArchiveHandoff(unittest.TestCase):
    def fixture(self):
        from certification.tests.test_campaign_state import CampaignStateTests
        case=CampaignStateTests();case.setUp();self.addCleanup(case.doCleanups)
        path=case.run/'solana-evidence-plane.sqlite';path.unlink()
        writer=EvidenceWriter(path,clock=lambda:1000)
        self.addCleanup(writer.close)
        for slot in (10,20):
            writer.ingest([record(slot=slot)],proof=proof(slot,slot))
            writer.retain(1000)
        writer.ingest([record(slot=30)],proof=proof(30,30))
        writer.archive(1000)
        writer.ingest([record(slot=40)],proof=proof(40,40))
        writer.interest('position:original','pump',lower_slot=40,priority=0,lifecycle='open')
        referenced={name for name, in writer.db.execute('SELECT DISTINCT archive FROM records WHERE archive IS NOT NULL')}
        self.assertEqual(len(referenced),1)
        all_names={p.name for p in path.with_name(path.name+'.archive').iterdir()}
        self.assertEqual(len(all_names),3)
        output=case.root/'output';output.mkdir()
        # Stage the real drained native artifact before filtering continuation state.
        from certification.archive_native import copy_snapshot
        rows=[];copy_snapshot(case.run,output/'certification-hourly',rows)
        self.assertFalse(any(r.get('error_type') for r in rows))
        (output/'certification-hourly/result.json').write_text(json.dumps(case.terminal))
        artifact=stage(case.lanes,output,'hourly')
        return case,writer,artifact,referenced,all_names

    def test_cold_unreferenced_archives_are_not_recopied_into_successor(self):
        case,writer,artifact,referenced,all_names=self.fixture()
        destination=case.root/'bounded-capsule'
        capsule=state.seal(destination,worktrees=case.lanes,run=case.run,
            window=case.window,terminal=case.terminal,expected_identity=case.identity,
            preserved_artifact=artifact)
        names={Path(r['path']).name for r in capsule['files'] if '.archive/' in r['path']}
        self.assertEqual(names,referenced)
        archive=artifact/'certification-hourly/solana-evidence-plane.sqlite.archive'
        self.assertEqual({p.name for p in archive.iterdir()},all_names)
        self.assertEqual(capsule['archive_handoff']['externalized_files'],2)
        state.restore(destination,worktrees=case.root/'fresh-lanes',run=case.root/'fresh-run',
            expected_identity=case.identity,expected_state_hash=capsule['state_hash'],
            campaign_id=case.window['campaign_id'],prior_index=0,authorization_hash=case.window['authorization_hash'])
        with sqlite3.connect(case.root/'fresh-run/solana-evidence-plane.sqlite') as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            self.assertEqual(db.execute("SELECT active FROM interests WHERE owner='position:original'").fetchone(),(1,))
        reader=EvidenceReader(case.root/'fresh-run/solana-evidence-plane.sqlite')
        try:self.assertEqual(reader.window('pump',40,40,as_of=100)[0]['payload'],{'value':1})
        finally:reader.close()

    def test_missing_or_corrupt_preserved_evidence_cannot_be_externalized(self):
        case,writer,artifact,referenced,all_names=self.fixture()
        cold=next(iter(all_names-referenced))
        path=artifact/'certification-hourly/solana-evidence-plane.sqlite.archive'/cold
        path.write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError,'snapshot_hash'):
            state.seal(case.root/'bad-capsule',worktrees=case.lanes,run=case.run,
                window=case.window,terminal=case.terminal,expected_identity=case.identity,
                preserved_artifact=artifact)

    def test_live_archive_missing_or_changed_after_snapshot_fails_closed(self):
        for changed in (False,True):
            with self.subTest(changed=changed):
                case,writer,artifact,referenced,all_names=self.fixture()
                name=next(iter(referenced))
                path=case.run/'solana-evidence-plane.sqlite.archive'/name
                if changed:
                    data=path.read_bytes();path.write_bytes(bytes([data[0]^1])+data[1:])
                else:path.unlink()
                with self.assertRaisesRegex(ValueError,'live_archive'):
                    state.seal(case.root/'bad-live-capsule',worktrees=case.lanes,run=case.run,
                        window=case.window,terminal=case.terminal,expected_identity=case.identity,
                        preserved_artifact=artifact)
