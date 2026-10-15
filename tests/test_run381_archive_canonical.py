"""Run 381 archive CPU regression: preserve bytes while avoiding log JSON churn."""
from dataclasses import replace
import gzip,hashlib,json,pickle,tempfile,unittest,zlib
from pathlib import Path
from unittest.mock import patch
from meme_machine import solana_evidence_plane as plane
from meme_machine import solana_evidence_storage as storage
from tests.test_retention_progress import record


class ArchiveCanonicalTests(unittest.TestCase):
 def check_snapshot(self,writer,snapshot):
  ordinary=writer.prepare_archive(snapshot,max_bytes=16*1024*1024)
  expected=writer.write_archive(writer.path,ordinary)
  commit,receipt=writer.prepare_and_write_archive(writer.path,snapshot,max_bytes=16*1024*1024)
  self.assertEqual({k:receipt[k] for k in expected},expected)
  saved=gzip.decompress((Path(str(writer.path)+'.archive')/receipt['name']).read_bytes())
  self.assertEqual(saved,('\n'.join(plane.canonical(r) for r in ordinary)+'\n').encode())
  self.assertEqual([r['body'] for r in commit],[dict(scope=r['body']['scope'],slot=r['body']['slot']) for r in ordinary])

 def test_archival_reuses_authenticated_canonical_logs_without_full_body_decode(self):
  logs=['quoted " slash \\ newline \n unicode \u2603 '+str(i)+'x'*100 for i in range(80)]
  with tempfile.TemporaryDirectory() as td:
   writer=plane.EvidenceWriter(Path(td)/'db',clock=lambda:1000)
   try:
    rows=[replace(record(),identity='canonical:'+str(i),payload={'raw_lineage':{'logs':logs},'meta':{'logMessages':logs}}) for i in range(20)]
    writer.ingest(rows);snapshot=writer.archive_snapshot(1000)
    self.check_snapshot(writer,snapshot)
    with patch.object(plane,'_decode_body',side_effect=AssertionError('archive repeated full JSON decoding')):
     commit,receipt=writer.prepare_and_write_archive(writer.path,snapshot,max_bytes=16*1024*1024)
    self.assertEqual(len(commit),20)
    self.assertEqual(writer.commit_archive(commit,receipt),20)
    self.assertEqual(writer.commit_archive(commit,receipt),0)
   finally:writer.close()

 def test_marker_lookalikes_and_nested_chunks_preserve_exact_archived_bodies(self):
  first=['first'+'x'*600];first_hash=plane.digest(first)
  second=[{'_hot_log_chunk':first_hash},'second'+'y'*600]
  payloads=[{'raw_lineage':{'logs':first},'meta':{'logMessages':second}},
            {'raw_lineage':{'logs':first},'other':{'_hot_log_chunk':first_hash}},
            {'meta':{'logMessages':second},'padding':'z'*3000},
            {'simple':'small legacy unicode \u2603'},
            {'large_unchunked':'x'*3000}]
  with tempfile.TemporaryDirectory() as td:
   writer=plane.EvidenceWriter(Path(td)/'db',clock=lambda:1000)
   try:
    writer.ingest([replace(record(),identity='lookalike:'+str(i),payload=p) for i,p in enumerate(payloads)])
    self.check_snapshot(writer,writer.archive_snapshot(1000))
   finally:writer.close()

 def test_corrupt_or_missing_chunks_and_body_hash_fail_before_publication(self):
  with tempfile.TemporaryDirectory() as td:
   writer=plane.EvidenceWriter(Path(td)/'db',clock=lambda:1000)
   try:
    writer.ingest([replace(record(),payload={'raw_lineage':{'logs':['x'*3000]}})])
    original=writer.archive_snapshot(1000)
    for change in ('missing','corrupt','hash','body_hash'):
     snapshot=pickle.loads(pickle.dumps(original));key=next(iter(snapshot['chunks']))
     if change=='missing':snapshot['chunks'].pop(key)
     elif change=='corrupt':snapshot['chunks'][key]=b'invalid'
     elif change=='hash':snapshot['chunks'][key]=zlib.compress(b'["different"]')
     else:snapshot['rows'][0]['hash']='0'*64
     with self.subTest(change=change),self.assertRaises(plane.EvidenceConflict):
      writer.prepare_and_write_archive(writer.path,snapshot)
     self.assertFalse(Path(str(writer.path)+'.archive').exists())
    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0],1)
   finally:writer.close()

 def test_raw_chunk_cache_and_partial_archive_budget_remain_bounded(self):
  cache={}
  for i in range(6):
   body=replace(record(),payload={'raw_lineage':{'logs':[str(i)+'x'*1_000_000]}}).body()
   encoded,chunks=storage.prepare(body)
   fields,raw=storage.archive_body(encoded,chunks=dict(chunks),raw_chunks=cache)
   self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),plane.digest(body))
   self.assertLessEqual(sum(map(len,cache.values())),4*1024*1024)
  self.assertEqual(len(cache),4)
  with tempfile.TemporaryDirectory() as td:
   writer=plane.EvidenceWriter(Path(td)/'db',clock=lambda:1000)
   try:
    writer.ingest([replace(record(),identity='budget:'+str(i),payload=body['payload']) for i in range(4)])
    snapshot=writer.archive_snapshot(1000)
    plan,receipt=writer.prepare_and_write_archive(writer.path,snapshot,max_bytes=1_100_000)
    self.assertEqual(len(plan),1);self.assertEqual(writer.commit_archive(plan,receipt),1)
    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0],3)
   finally:writer.close()

if __name__=='__main__':unittest.main()
