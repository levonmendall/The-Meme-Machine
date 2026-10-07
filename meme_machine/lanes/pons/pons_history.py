"""Pons-owned retention and fair bounded work over incremental Survivor history.

The population has no machine count limit. Transport remains bounded, and a
claimed batch is rotated durably even if its provider attempt fails. The block
checkpoint belongs to the same transaction as the authenticated observations.
"""
from meme_machine.runtime.survivor_history import History
from meme_machine.runtime.journal import canonical, digest
from contextlib import contextmanager
import json


class PonsHistory(History):
    def __init__(self, path, *, policy):
        super().__init__(path, policy=policy, maximum_candidates=None)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS pons_graduation_intake(
                id TEXT PRIMARY KEY, body TEXT NOT NULL, hash TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0, complete INTEGER NOT NULL DEFAULT 0);
        ''')

    @contextmanager
    def transaction(self):
        if not self.db.in_transaction:
            with super().transaction():yield
        else:
            self.db.execute('SAVEPOINT pons_history_append')
            try:
                yield
                self.db.execute('RELEASE pons_history_append')
            except BaseException:
                self.db.execute('ROLLBACK TO pons_history_append')
                self.db.execute('RELEASE pons_history_append')
                raise

    def append(self,identity,*,through,events,points,complete,evidence_checkpoint=None):
        # The frozen Pons policy needs its original graduation anchor and every
        # price in the last 24h. Timestamp keys permit <=86,401 such points;
        # population or an unrelated old prefix cannot exhaust the 100k guard.
        with self.transaction():
            row=self.get(identity)
            if row is None or through<row['through']:raise ValueError('survivor_history_watermark')
            cut=through-86400
            older=self.db.execute('SELECT at,price,hash FROM points WHERE candidate=? AND at<? ORDER BY at',
                (identity,cut)).fetchall()
            if len(older)>2:
                observations=[]
                for at,price,checksum in older:
                    if digest([identity,at,price])!=checksum:raise ValueError('survivor_price_corruption')
                    observations.append(dict(at=at,**json.loads(price)))
                from meme_machine.runtime.learning import survivor
                survivor(self.db,row,((p['at'],p) for p in observations))
                previous=self.get_meta('pons_price_window:'+identity) or dict(count=0,hash=None)
                removed=observations[1:-1]
                self.set_meta('pons_price_window:'+identity,dict(count=previous['count']+len(removed),
                    hash=digest([previous['hash'],removed]),before=cut,
                    authority='canonical_observations_folded_after_strategy_window',
                    original_anchor=observations[0],boundary=observations[-1]))
                self.db.execute('DELETE FROM points WHERE candidate=? AND at>? AND at<?',
                    (identity,older[0][0],older[-1][0]))
            return super().append(identity,through=through,events=events,points=points,
                complete=complete,evidence_checkpoint=evidence_checkpoint)

    def facts(self,identity,now):
        prefix=self.get_meta('pons_price_window:'+identity)
        if prefix and now<prefix['before']:raise ValueError('pons_price_window_past_query')
        return super().facts(identity,now)

    def retain_graduations(self, events, through, *, block_hash=None):
        # Cheap identities and discovery cursor commit together. Authentication
        # may wait; neither count pressure nor a restart can skip a nomination.
        with self.transaction():
            for event in events:
                body = canonical(event)
                self.db.execute('INSERT OR IGNORE INTO pons_graduation_intake(id,body,hash) VALUES(?,?,?)',
                    (digest(event), body, digest(event)))
            self.set_meta('discovery_block', through)
            if block_hash is not None:self.set_meta('discovery_block_hash',block_hash)

    def invalidate_discovery(self):
        # Existing nominees/controllers survive. Only discovery's canonical
        # range proof resets, then the same bounded seven-day bootstrap resumes.
        with self.transaction():
            previous=self.get_meta('discovery_reorgs') or 0
            self.set_meta('discovery_reorgs',previous+1)
            for key in ('discovery_block','discovery_block_hash','discovery_bootstrap'):self.set_meta(key,None)

    def graduation_batch(self, *, limit=1):
        if not 1 <= limit <= 32:
            raise ValueError('pons_graduation_work_bound')
        with self.transaction():
            rows = self.db.execute('SELECT id,body,hash FROM pons_graduation_intake WHERE complete=0 ORDER BY attempt,id LIMIT ?', (limit,)).fetchall()
            sequence = self.get_meta('graduation_attempt_sequence') or 0
            result = []
            for identity, body, checksum in rows:
                event = self._verified((body, checksum))
                sequence += 1
                self.db.execute('UPDATE pons_graduation_intake SET attempt=? WHERE id=?', (sequence, identity))
                result.append((identity, event))
            self.set_meta('graduation_attempt_sequence', sequence)
        return result

    def graduation_complete(self, identity):
        # Authentication/structural disposition is already durable before this
        # acknowledgement. The intake contains pending work, not an ever-growing
        # second copy of completed canonical graduations.
        with self.transaction():
            old=self.db.execute('SELECT body,hash FROM pons_graduation_intake WHERE id=?',(identity,)).fetchone()
            if old is None:return
            self._verified(old)
            previous=self.get_meta('graduation_intake_completed') or dict(count=0,hash=None)
            self.set_meta('graduation_intake_completed',dict(count=previous['count']+1,
                hash=digest([previous['hash'],identity])))
            self.db.execute('DELETE FROM pons_graduation_intake WHERE id=?',(identity,))

    def pending_graduations(self):
        return self.db.execute('SELECT COUNT(*) FROM pons_graduation_intake WHERE complete=0').fetchone()[0]

    @staticmethod
    def _checkpoint(row):
        if row is None:
            return None
        checkpoint = row.get('evidence_checkpoint')
        if checkpoint is not None:
            if (checkpoint.get('schema') != 'pons-block-watermark-v1'
                    or type(checkpoint.get('block')) is not int
                    or not checkpoint.get('block_hash')):
                raise ValueError('pons_history_checkpoint_identity')
            row = dict(row, block=checkpoint['block'], block_hash=checkpoint['block_hash'])
        return row

    def get(self, identity):
        return self._checkpoint(super().get(identity))

    def rows(self, *, include_retired=False):
        rows = [self._checkpoint(row) for row in super().rows(include_retired=include_retired)]
        return sorted(rows, key=lambda r: (r.get('qualification_attempt', 0), r['last_checked'], r['id']))

    def history_batch(self, rows, top, *, limit=64):
        if not 1 <= limit <= 64:
            raise ValueError('pons_history_transport_bound')
        pending = [r for r in rows if r.get('block') is not None and r['block'] < top]
        pending.sort(key=lambda r: (r.get('history_attempt', 0), r['block'], r['id']))
        selected = pending[:limit]
        with self.transaction():
            sequence = self.get_meta('history_attempt_sequence') or 0
            for old in selected:
                sequence += 1
                row = self.get(old['id'])
                row['history_attempt'] = sequence
                self.save(row)
            self.set_meta('history_attempt_sequence', sequence)
        return [self.get(row['id']) for row in selected]

    def qualification_turn(self, rows, now):
        if not rows:
            return None
        chosen = min(rows, key=lambda r: (r.get('qualification_attempt', 0), r['last_checked'], r['id']))
        with self.transaction():
            sequence = (self.get_meta('qualification_attempt_sequence') or 0) + 1
            row = self.get(chosen['id'])
            row.update(qualification_attempt=sequence, last_checked=now)
            self.save(row)
            self.set_meta('qualification_attempt_sequence', sequence)
        return row

    def append_block(self, identity, *, block, header, events, points):
        if (int(header['number'], 16) != block or not header.get('hash')
                or any(e['at'] > int(header['timestamp'], 16) for e in events)):
            raise ValueError('pons_history_block_identity')
        return self.append(identity, through=int(header['timestamp'], 16),
            events=events, points=points, complete=True,
            evidence_checkpoint=dict(schema='pons-block-watermark-v1', block=block, block_hash=header['hash']))

    def reset_after_reorg(self, identity, *, canonical_graduation_hash, anchor_price):
        """Retain identity/controller, rebuild observations from a proven anchor.

        Transport still advances forty blocks per turn. Native basis, HWM,
        reservations and risk journals belong to the book and are never reset.
        """
        with self.transaction():
            row=self.get(identity);graduation=row['graduation']
            if canonical_graduation_hash!=graduation['block_hash']:
                row['complete']=False;row['recovery']='graduation_membership_unavailable'
                self.save(row)
                return False
            previous=self.get_meta('pons_reorg:'+identity) or dict(count=0,hash=None)
            points,events=self.facts(identity,row.get('through',graduation['at']))
            self.set_meta('pons_reorg:'+identity,dict(count=previous['count']+1,
                hash=digest([previous['hash'],row,points,events,self.get_meta('archive_prefix:'+identity)]),
                qualification_authority=False,reason='canonical_watermark_reorg'))
            self.db.execute('DELETE FROM points WHERE candidate=?',(identity,))
            self.db.execute('DELETE FROM events WHERE candidate=?',(identity,))
            self.db.execute('DELETE FROM meta WHERE key=?',('archive_prefix:'+identity,))
            self.db.execute('DELETE FROM meta WHERE key=?',('pons_price_window:'+identity,))
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='learning_facts_v1'").fetchone():
                self.db.execute('DELETE FROM learning_facts_v1 WHERE id=?',('survivor:'+identity,))
            row.update(block=graduation['block'],block_hash=graduation['block_hash'],
                through=graduation['at'],complete=False,recovery='bounded_replay_from_canonical_graduation')
            if row['state']=='retired':row.update(state='graduated',last_checked=0)
            row['evidence_checkpoint']=dict(schema='pons-block-watermark-v1',block=graduation['block'],
                block_hash=graduation['block_hash'])
            self.save(row)
            bar=dict(price=str(anchor_price),low=str(anchor_price),high=str(anchor_price))
            body=[identity,graduation['at'],canonical(bar)]
            self.db.execute('INSERT INTO points VALUES(?,?,?,?)',(*body,digest(body)))
            return True

    def finish_recovery(self, identity, *, block, block_hash):
        with self.transaction():
            row=self.get(identity)
            if (row.get('recovery')!='bounded_replay_from_canonical_graduation'
                    or row['block']!=block or row['block_hash']!=block_hash):return False
            row['complete']=True;row.pop('recovery')
            self.save(row)
            return True

    def replace_orphaned_graduation(self,identity,evidence,*,anchor_price):
        """A newly canonical graduation reactivates a retained orphan identity."""
        with self.transaction():
            row=self.get(identity)
            if row is None or row.get('recovery')!='graduation_membership_unavailable':
                raise ValueError('pons_graduation_replacement_authority')
            previous=self.get_meta('pons_graduation_replacements:'+identity) or dict(count=0,hash=None)
            self.set_meta('pons_graduation_replacements:'+identity,dict(count=previous['count']+1,
                hash=digest([previous['hash'],row['graduation'],evidence]),
                old_graduation=row['graduation'],reason='old_graduation_proven_noncanonical'))
            row['graduation']=evidence;self.save(row)
            self.reset_after_reorg(identity,canonical_graduation_hash=evidence['block_hash'],anchor_price=anchor_price)
            return self.get(identity)
