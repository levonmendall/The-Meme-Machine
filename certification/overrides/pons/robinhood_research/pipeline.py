"""Append-only lane-local opportunity evidence; no strategy or allocation authority."""
import json
import sqlite3
import threading
import time
from collections import defaultdict

class Pipeline:
    def __init__(self,path,lane,policy_hash):
        self.lane=lane;self.policy_hash=policy_hash;self.lock=threading.RLock()
        self.db=sqlite3.connect(str(path),check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS progress(
            sequence INTEGER PRIMARY KEY, lane TEXT NOT NULL, policy_hash TEXT NOT NULL,
            candidate TEXT NOT NULL, stage TEXT NOT NULL, reason TEXT, classification TEXT,
            at REAL NOT NULL, monotonic REAL NOT NULL, details TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS progress_no_update BEFORE UPDATE ON progress
            BEGIN SELECT RAISE(ABORT,'append_only'); END;
            CREATE TRIGGER IF NOT EXISTS progress_no_delete BEFORE DELETE ON progress
            BEGIN SELECT RAISE(ABORT,'append_only'); END;''')
        foreign=self.db.execute('SELECT 1 FROM progress WHERE lane!=? OR policy_hash!=? LIMIT 1',(lane,policy_hash)).fetchone()
        if foreign:raise ValueError('foreign_pipeline_namespace')
        self.stages=defaultdict(set);self.classes=defaultdict(set);self.reasons=defaultdict(set)
        self.last=None;self.write_seconds=0.;self.records=0
        for c,s,r,k,at,mono in self.db.execute('SELECT candidate,stage,reason,classification,at,monotonic FROM progress ORDER BY sequence'):
            self._index(c,s,r,k,at,mono)

    def _index(self,c,s,r,k,at,mono):
        self.records+=1
        self.stages[s].add(c)
        if k:self.classes[k].add(c)
        if r:self.reasons[r].add(c)
        self.last=dict(candidate=c,stage=s,at=at,monotonic=mono)

    def record(self,candidate,stage,reason=None,classification=None,**details):
        c=str(candidate);at=time.time();mono=time.monotonic()
        with self.lock,self.db:
            self.db.execute('INSERT INTO progress(lane,policy_hash,candidate,stage,reason,classification,at,monotonic,details) VALUES(?,?,?,?,?,?,?,?,?)',
                (self.lane,self.policy_hash,c,stage,reason,classification,at,mono,json.dumps(details,sort_keys=True)))
            self._index(c,stage,reason,classification,at,mono)
        self.write_seconds+=time.monotonic()-mono

    def snapshot(self):
        with self.lock:
            stages=('discovered','prospect_screened','screened','admitted','evidence_requested','evidence_complete',
                    'trigger_observed','trigger_authenticated','fresh_state','warmup_started','warmup_complete',
                    'reconstruction_started','reconstruction_complete','prospective_range','economic_vector',
                    'trigger_terminal','evaluated','rejected','qualified','entry_reserved','entry_filled','entry_cancelled',
                    'deployed','forward_observation','unwind','settled','terminal')
            classes=('capacity_censored','provider_failed','stale_before_evidence','stale_during_evidence',
                     'stale_after_complete_evidence','reconstruction_incomplete','strategy_rejection',
                     'no_authentic_activity','local_budget_exhausted','consumer_deadline')
            return dict(schema='lane-opportunity-coverage-v1',lane=self.lane,
                identity_scope='native_candidate_identity; stages and classes overlap; never sum as losses',
                raw_records=self.records,
                authenticated_triggers=len(self.stages['trigger_started']),
                terminally_classified_triggers=len(self.stages['trigger_terminal']),
                unresolved_triggers=len(self.stages['trigger_started']-self.stages['trigger_terminal']),
                stale_stage_counts={s:len(self.reasons[s]) for s in ('stale_on_arrival','stale_in_queue','stale_during_evidence','stale_after_complete_evidence')},
                stages={s:len(self.stages[s]) for s in stages},
                unique_classes={k:len(self.classes[k]) for k in classes},
                unique_terminal_reasons={k:len(v) for k,v in self.reasons.items()},last_transition=self.last)

    def close(self):self.db.close()

def censor_class(reason):
    r=str(reason).lower()
    if 'stale_on_arrival' in r or 'stale_in_queue' in r:return 'stale_before_evidence'
    if 'stale_after_complete' in r:return 'stale_after_complete_evidence'
    if 'stale' in r:return 'stale_during_evidence'
    if 'budget' in r:return 'local_budget_exhausted'
    if 'capacity' in r or 'queue_deadline' in r:return 'capacity_censored'
    if 'deadline' in r:return 'consumer_deadline'
    if 'provider' in r or 'null_gettransaction' in r:return 'provider_failed'
    if 'trigger_timeout' in r or 'zero_warmup' in r:return 'no_authentic_activity'
    return 'reconstruction_incomplete'
