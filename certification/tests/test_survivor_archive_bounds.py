"""Verified predecessor archives permit exact bounded hot Survivor history."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from certification.survivor_history import History

SCRIPT=r'''
import hashlib,os,shutil,tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from certification.survivor_history import History
from meme_machine.pumpswap_survivor import reduce_reset_history,evaluate_entry,POLICY_HASH
from tests.test_pumpswap_survivor import facts
with tempfile.TemporaryDirectory() as td:
 root=Path(td);path=root/'history.sqlite'
 history=History(path,policy=POLICY_HASH)
 history.graduate('coin',dict(at=0,identity='authenticated'))
 # The unchanged capacity remains a hard guard, with atomic rollback.
 try:history.append('coin',through=100000,events=[],points=[(t,'100') for t in range(100001)],complete=True)
 except ValueError as exc:assert str(exc)=='survivor_history_point_capacity'
 else:raise AssertionError('point limit relaxed')
 assert history.get('coin')['through']==0 and history.db.execute('SELECT count(*) FROM points').fetchone()[0]==0
 rows=[dict(at=t,price=str(100+t%13),low='95',high='115') for t in range(90001)]
 history.append('coin',through=90000,events=[],points=[(p['at'],{k:v for k,v in p.items() if k!='at'}) for p in rows],complete=True)
 history.close();sizes=[]
 for window in range(3):
  archived=root/('preserved-'+str(window)+'.sqlite');shutil.copyfile(path,archived)
  checksum=hashlib.sha256(archived.read_bytes()).hexdigest()
  authority=dict(state_hash=str(window)*64,history_sha256=checksum,artifact={'digest':'sha256:'+checksum})
  with patch.dict(os.environ,MM_AUTONOMOUS_STATE_RECEIPT='verified-by-campaign-state'):
   history=History(path,policy=POLICY_HASH)
  assert history.compact_archived(authority,reducer=reduce_reset_history)
  assert not history.compact_archived(authority,reducer=reduce_reset_history)
  prefix=history.prefix('coin');points,_=history.facts('coin',history.get('coin')['through'])
  assert len(points)==86402 and points[0]['at']==0
  # Compare the whole original reset scan to prefix + exact retained suffix.
  assert reduce_reset_history(rows)==reduce_reset_history([p for p in points if p['at']>prefix['through']],prefix)
  assert hashlib.sha256(archived.read_bytes()).hexdigest()==checksum
  for at in (1,prefix['through']):
   try:history.append('coin',through=history.get('coin')['through'],events=[],points=[(at,'999')],complete=True)
   except ValueError as exc:assert str(exc)=='survivor_archived_price_rewrite'
   else:raise AssertionError('archived evidence rewritten')
  before=history.get('coin')['through'];fresh=[dict(at=t,price=str(100+t%13),low='95',high='115') for t in range(before+1,before+3601)]
  history.append('coin',through=before+3600,events=[],points=[(p['at'],{k:v for k,v in p.items() if k!='at'}) for p in fresh],complete=True)
  rows.extend(fresh)
  assert history.db.execute('SELECT count(*) FROM points').fetchone()[0]==90002
  assert history.db.execute('PRAGMA integrity_check').fetchone()==('ok',)
  history.close();sizes.append(path.stat().st_size)
 assert sizes[-1]<=sizes[0]+1024*1024,sizes
print('dense original capacity failure, archived exact reset state, unchanged hot bound and restart pass')
'''

class SurvivorArchiveTests(unittest.TestCase):
    def test_dense_native_pump_history_preserves_exact_state_at_unchanged_point_limit(self):
        roots=os.environ.get('MM_TEST_LANE_WORKTREES')
        if not roots:self.skipTest('requires prepared native lanes')
        result=subprocess.run([sys.executable,'-c',SCRIPT],cwd=Path(roots)/'pump',
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2])),
            capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_interrupted_compaction_rolls_back_without_losing_archive_identity(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'history.sqlite';h=History(path,policy='frozen')
            for identity in ('one','two'):
                h.graduate(identity,dict(at=0));h.append(identity,through=100000,events=[],
                    points=[(at,'100') for at in (0,1,2,13600,99999,100000)],complete=True)
            h.close();original=path.read_bytes();checksum=hashlib.sha256(original).hexdigest()
            authority=dict(state_hash='first',history_sha256=checksum)
            calls=[]
            def interrupted(rows,previous):
                calls.append(1)
                if len(calls)==2:raise SystemExit('injected after first candidate prune')
                return {'proof':'first'}
            with patch.dict(os.environ,MM_AUTONOMOUS_STATE_RECEIPT='verified'):
                h=History(path,policy='frozen')
                with self.assertRaises(SystemExit):h.compact_archived(authority,reducer=interrupted)
                self.assertIsNone(h.get_meta('compacted_from_state'))
                self.assertIsNone(h.prefix('one'));h.close()
                self.assertEqual(path.read_bytes(),original)
                h=History(path,policy='frozen')
                self.assertTrue(h.compact_archived(authority));h.close()

    def test_archive_identity_is_required_and_unknown_queries_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'history.sqlite';h=History(path,policy='frozen')
            h.graduate('coin',dict(at=0));h.append('coin',through=100000,events=[],
                points=[(at,'100') for at in (0,1,2,13600,99999,100000)],complete=True);h.close()
            checksum=hashlib.sha256(path.read_bytes()).hexdigest()
            with patch.dict(os.environ,MM_AUTONOMOUS_STATE_RECEIPT='verified'):
                h=History(path,policy='frozen')
            with self.assertRaisesRegex(ValueError,'source_changed'):
                h.compact_archived(dict(state_hash='first',history_sha256='wrong'))
            self.assertTrue(h.compact_archived(dict(state_hash='first',history_sha256=checksum)))
            with self.assertRaisesRegex(ValueError,'archived_history_query'):h.facts('coin',2)
            self.assertEqual([r['at'] for r in h.facts('coin',100000)[0]],[0,13600,99999,100000])
            h.close()

    def test_retired_churn_compacts_only_preserved_expired_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/'history.sqlite';sizes=[]
            h=History(path,policy='frozen')
            held=h.graduate('held',dict(at=0));held['position']='open';h.save(held)
            recent=h.graduate('recent-retirement',dict(at=10**9));h.retire(recent)
            h.close()
            for window in range(24):
                h=History(path,policy='frozen')
                for n in range(200):
                    at=window*3600+n+1;identity=str(at)
                    row=h.graduate(identity,dict(at=at))
                    h.set_meta('archive_prefix:'+identity,dict(reducer_state=None,through=at))
                    h.retire(row,expired_before=at+1)
                floor=h.get_meta('graduation_floor')
                self.assertEqual(len(h.rows(include_retired=True)),202)
                h.close();preserved=root/('preserved-'+str(window)+'.sqlite')
                shutil.copyfile(path,preserved);checksum=hashlib.sha256(preserved.read_bytes()).hexdigest()
                authority=dict(state_hash=str(window),history_sha256=checksum,
                    artifact={'digest':'sha256:'+checksum})
                with patch.dict(os.environ,MM_AUTONOMOUS_STATE_RECEIPT='verified'):
                    h=History(path,policy='frozen')
                self.assertTrue(h.compact_archived(authority))
                self.assertEqual(h.get('held'),held)
                self.assertEqual(len(h.rows(include_retired=True)),2)
                self.assertEqual(h.db.execute("SELECT count(*) FROM meta WHERE key LIKE 'archive_prefix:%'").fetchone()[0],0)
                receipt=h.get_meta('retired_archive')
                self.assertEqual(receipt['total_count'],(window+1)*200)
                self.assertEqual(receipt['authority'],authority)
                with self.assertRaisesRegex(ValueError,'graduation_expired'):
                    h.graduate(str(at),dict(at=at))
                with self.assertRaisesRegex(ValueError,'conflicting_survivor_graduation'):
                    h.graduate('held',dict(at=1))
                # The exact inclusive approved maximum-age boundary is retained.
                if window==23:
                    edge=h.graduate('edge',dict(at=floor))
                    with self.assertRaisesRegex(ValueError,'retirement_age'):h.retire(edge,expired_before=floor)
                self.assertEqual(h.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
                h.close();sizes.append(path.stat().st_size)
                self.assertEqual(hashlib.sha256(preserved.read_bytes()).hexdigest(),checksum)
            self.assertLessEqual(max(sizes[4:])-min(sizes[4:]),8192,sizes)

    def test_retired_prefix_crash_and_unpreserved_mutation_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'history.sqlite';h=History(path,policy='frozen')
            row=h.graduate('expired',dict(at=1));h.retire(row,expired_before=2);h.close()
            original=path.read_bytes();authority=dict(state_hash='first',history_sha256=hashlib.sha256(original).hexdigest())
            with patch.dict(os.environ,MM_AUTONOMOUS_STATE_RECEIPT='verified'):
                h=History(path,policy='frozen')
                original_set=h.set_meta
                def cut(key,value):
                    if key=='retired_archive':raise SystemExit('after deleting expired prefix')
                    return original_set(key,value)
                with patch.object(h,'set_meta',side_effect=cut),self.assertRaises(SystemExit):h.compact_archived(authority)
                self.assertIsNotNone(h.get('expired'));self.assertIsNone(h.get_meta('compacted_from_state'));h.close()
                self.assertEqual(path.read_bytes(),original)
                h=History(path,policy='frozen')
                fresh=h.graduate('new',dict(at=3))
                with self.assertRaisesRegex(ValueError,'source_changed'):h.compact_archived(authority)
                self.assertEqual(h.get('new'),fresh);self.assertIsNotNone(h.get('expired'));h.close()
