"""Seven virtual days of the production archive/retention and state-handoff path.

This bounded component soak does not stand in for full lifecycle/provider proof.
"""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import unittest
from unittest.mock import patch

from certification import campaign_state as transfer
from certification.autonomous_window import stage
from meme_machine import solana_evidence_service as service
from meme_machine.solana_evidence_plane import EvidenceReader,EvidenceUnavailable
from meme_machine.solana_provider_config import AlchemyEndpoint
from tests.test_solana_evidence_plane import record,proof


class AutonomousArchiveSoak(unittest.TestCase):
    def test_seven_days_of_restart_repair_archive_retention_and_preserved_handoffs(self):
        from certification.tests.test_campaign_state import CampaignStateTests
        fixture=CampaignStateTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        root=fixture.root;work=fixture.lanes;run=fixture.run
        (run/'solana-evidence-plane.sqlite').unlink()
        parent=None;observations=[];preserved=[];base_fds=len(list(Path('/proc/self/fd').iterdir()))
        base_threads=threading.active_count()
        for hour in range(168):
            now=1_800_000_000+hour*3600;slot=100+hour*2;path=run/'solana-evidence-plane.sqlite'
            with patch.object(service.time,'time',return_value=now):
                state=service.ServiceState(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
                writer=state.writer;writer.clock=lambda:now
                try:
                    if hour:
                        writer.reconnect('pump',slot)
                        reader=EvidenceReader(path)
                        try:self.assertFalse(reader.covered('pump',slot,slot+1,as_of=now))
                        finally:reader.close()
                    old=replace(record(slot=slot,observed=now-300),market_time=now-300)
                    writer.ingest([old],proof=proof(slot,slot,at=now-300,repair=bool(hour)))
                    fresh=replace(record(slot=slot+1,observed=now),market_time=now)
                    writer.ingest([fresh],proof=proof(slot+1,slot+1,at=now))
                    reader=EvidenceReader(path)
                    try:self.assertEqual(len(reader.window('pump',slot,slot+1,as_of=now,address='pool')),2)
                    finally:reader.close()
                    owner='candidate:'+str(hour)
                    writer.interest(owner,'pump',lower_slot=slot+1)
                    writer.release(owner,'pump')
                    state.fence.expire_candidates(now)
                    while True:
                        snapshot=state.archive_plan()
                        if not snapshot:break
                        plan,receipt=writer.prepare_and_write_archive(path,snapshot)
                        state.archive_commit(plan,receipt)
                    state.retention()
                    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM gaps WHERE repaired IS NULL').fetchone()[0],0)
                    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)
                    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NULL').fetchone()[0],0)
                    self.assertLessEqual(writer.db.execute('SELECT COUNT(*) FROM interests').fetchone()[0],3)
                    self.assertEqual(writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
                    with self.assertRaises(EvidenceUnavailable):writer.ingest([record(slot=slot-1,observed=now)])
                    observations.append(dict(hour=hour,hot_bytes=sum(p.stat().st_size for p in
                        (path,Path(str(path)+'-wal')) if p.exists()),archives=len(list(path.with_name(path.name+'.archive').glob('*.gz')))))
                finally:state.close()
            output=root/('window-'+str(hour));runtime=output/'certification-hourly';output.mkdir()
            shutil.copytree(run,runtime)
            terminal=dict(fixture.terminal,phase='hourly')
            (runtime/'result.json').write_text(json.dumps(terminal))
            artifact=stage(work,output,'hourly')
            window=dict(fixture.window,index=hour,workflow_run_id=hour+1)
            if hour:window['parent_state_hash']=parent
            capsule=transfer.seal(output/'capsule',worktrees=work,run=runtime,window=window,
                terminal=terminal,expected_identity=fixture.identity,preserved_artifact=artifact)
            self.assertEqual(capsule['archive_handoff']['transferred_files'],0)
            self.assertEqual(capsule['archive_handoff']['externalized_files'],1)
            cold=artifact/'certification-hourly/solana-evidence-plane.sqlite.archive'
            preserved.extend(p.read_bytes() for p in cold.iterdir())
            next_work=root/'next-lanes';next_run=root/'next-runtime'
            transfer.restore(output/'capsule',worktrees=next_work,run=next_run,expected_identity=fixture.identity,
                expected_state_hash=capsule['state_hash'],campaign_id=window['campaign_id'],
                prior_index=hour,authorization_hash=window['authorization_hash'])
            # Simulate the old worker disappearing. Preserved artifact bytes are
            # retained separately; only restored state becomes the next hot root.
            shutil.rmtree(work);shutil.rmtree(run);shutil.rmtree(output)
            work=root/'active-lanes';run=root/'active-runtime'
            next_work.rename(work);next_run.rename(run);parent=capsule['state_hash']
            self.assertFalse((run/'solana-evidence-plane.sqlite.archive').exists())
            self.assertFalse(list(run.rglob('*.tmp')))
            self.assertLessEqual(len(list(Path('/proc/self/fd').iterdir())),base_fds+2)
            self.assertEqual(threading.active_count(),base_threads)
        self.assertEqual(len(preserved),168)
        self.assertEqual(max(row['archives'] for row in observations),1)
        self.assertLess(max(row['hot_bytes'] for row in observations),2*1024*1024*1024)
        # After warmup, page reuse keeps the actual hot files in the same band.
        sizes=[row['hot_bytes'] for row in observations[4:]]
        self.assertLessEqual(max(sizes)-min(sizes),1024*1024)

        print(json.dumps(dict(scope='seven_day_archive_handoff_component_soak',passed=True,
            virtual_days=7,windows=168,hot_records_per_window=1,local_archive_files_peak=1,
            cold_archive_files_transferred=0,preserved_archive_chunks=len(preserved),
            hot_bytes_min=min(sizes),hot_bytes_max=max(sizes),fd_growth_max=2,thread_growth=0,
            incomplete_gap_before_decision=False,paper_only=True,market_collection=False),sort_keys=True))
