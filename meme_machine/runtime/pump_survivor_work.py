"""Actual Pump Survivor inventory and request/COMMIT observations.

The existing private Pump owner is the only provenance issuer. Native history
and candidate-decision transactions remain the durability authority. Inventory
is independent of selected requests and grants no source/protection readiness.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import threading

from .economic_cohort import checksum,_hash,MAX_POSITION
from .native_work_cohort import NativeWorkCohorts,MAX_UNITS,MAX_BYTES,project_native_work


class PumpSurvivorWork:
    def __init__(self,owner,history_path,epoch,policy):
        from ..operational.normal_pump_boot import NativePumpOwnerContext,current_pump_owner_context
        if type(owner) is not NativePumpOwnerContext or owner is not current_pump_owner_context():
            raise ValueError('native_survivor_private_owner')
        owner.require_current();self.owner=owner;self.thread=(os.getpid(),threading.get_native_id())
        self.support=owner.boot_support();support=self.support.value()
        if support['association']['epoch_id']!=epoch:raise ValueError('native_survivor_epoch')
        self.description=support['retained_work']['pump_history']
        self.shared_description=support['retained_work']['candidate_history']
        self.path=Path(owner.identity()['root'])/self.description['relative_path']
        self.shared_path=Path(owner.identity()['root'])/self.shared_description['relative_path']
        if Path(history_path).resolve()!=self.path:raise ValueError('native_survivor_path')
        self.binding=dict(owner_pid=self.thread[0],owner_tid=self.thread[1],
            private_owner_sha256=owner.identity_sha256,support_sha256=self.support.identity_sha256,
            epoch_sha256=checksum(epoch),policy_sha256=_hash(policy),regime='pump_survivor')
        self.preparation=NativeWorkCohorts(self.binding,'NATIVE_PREPARATION')
        self.evaluation=NativeWorkCohorts(self.binding,'NATIVE_EVALUATION')
        self.history=None;self.db=None;self.frame=None;self.loss=None
        self.baseline=None;self.latest=None;self.save_count=0;self.save_chain='0'*64
        self.last_save=None;self.last_read=None;self.selected=None;self.requested=None
        self.source=None;self.started=False
        self.turn=None

    def unavailable(self):
        self.loss='NATIVE_BOUNDARY_UNAVAILABLE'
        self.preparation.unavailable();self.evaluation.unavailable()

    def _owned(self,history=None):
        self.owner.require_current()
        if self.thread!=(os.getpid(),threading.get_native_id()):raise ValueError('native_survivor_owner')
        if self.support.identity_sha256!=self.binding['support_sha256']:
            raise ValueError('native_survivor_support')
        if history is not None:
            if history.path.resolve()!=self.path or self.path.is_symlink():raise ValueError('native_survivor_path')
            value=self.path.stat(follow_symlinks=False)
            if (not stat.S_ISREG(value.st_mode) or (value.st_dev,value.st_ino)!=
                    (self.description['device'],self.description['inode'])):raise ValueError('native_survivor_inode')
            if self.history is None:self.history=history;self.db=history.db
            if history is not self.history or history.db is not self.db:raise ValueError('native_survivor_history')

    def _call(self,operation):
        if self.loss:return None
        try:return operation()
        except Exception:self.unavailable();return None

    @staticmethod
    def _metadata(row,sha):
        identity=row['id']
        if type(identity) is not str or not 0<len(identity.encode())<=512:raise ValueError('candidate')
        return dict(candidate_sha256=checksum(identity),body_sha256=_hash(sha),
            last_checked=row['last_checked'],through=row.get('through'),
            retired=row.get('state')=='retired',held=bool(row.get('position')),
            checkpoint_sha256=(None if row.get('evidence_checkpoint') is None
                else checksum(row['evidence_checkpoint'])),decision_id=row.get('decision_id'))

    def transaction_started(self,history):
        def apply():
            self._owned(history)
            if self.frame is not None or not history.db.in_transaction:raise ValueError('transaction')
            self.frame=dict(events=[],bytes=0)
        return self._call(apply)

    def transaction_finished(self,history,committed):
        def apply():
            self._owned(history);frame=self.frame;self.frame=None
            if frame is None or history.db.in_transaction:raise ValueError('transaction')
            if committed:
                for kind,value in frame['events']:self._publish(kind,value)
        return self._call(apply)

    def _event(self,kind,value):
        if self.frame is not None:
            # Fixed small metadata only; no candidate body or history payload.
            size=len(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
            if len(self.frame['events'])>=MAX_UNITS or self.frame['bytes']+size>MAX_BYTES:
                raise ValueError('bound')
            self.frame['events'].append((kind,value));self.frame['bytes']+=size
        else:self._publish(kind,value)

    def _publish(self,kind,value):
        self._owned(self.history)
        if self.history.db.in_transaction:raise ValueError('uncommitted')
        if kind=='inventory':
            if self.baseline is None:self.baseline=dict(value)
            self.latest=dict(value)
        elif kind=='save':
            if self.baseline is None:raise ValueError('mutation_before_inventory')
            chain=checksum([self.save_chain,value]);self._owned(self.history)
            self.last_save=dict(value);self.save_chain=chain;self.save_count+=1
            if self.save_count>MAX_POSITION:raise ValueError('bound')
        else:raise ValueError('event')

    def inventory_started(self,history,include_retired):
        def apply():
            self._owned(history)
            return dict(hash=hashlib.sha256(),ids=set(),bytes=0,rows=0,held=0,retired=0,
                include_retired=include_retired)
        return self._call(apply)

    def inventory_row(self,history,frame,row,sha):
        def apply():
            self._owned()
            if frame is None or frame['rows']>=MAX_UNITS:raise ValueError('bound')
            identity=row['id']
            if type(identity) is not str:raise ValueError('candidate')
            raw=identity.encode()
            if not 0<len(raw)<=512 or frame['bytes']+len(raw)+64>MAX_BYTES:raise ValueError('bound')
            if identity in frame['ids']:raise ValueError('duplicate')
            body=bytes.fromhex(_hash(sha))
            # The original verifier already authenticated every native body.
            # Its SHA binds all row metadata; do not rehash that metadata once
            # per candidate on each existing native inventory traversal.
            frame['hash'].update(len(raw).to_bytes(4,'big')+raw+body)
            frame['ids'].add(identity);frame['bytes']+=len(raw)+64;frame['rows']+=1
            frame['held']+=int(bool(row.get('position')));frame['retired']+=int(row.get('state')=='retired')
        return self._call(apply)

    def inventory_finished(self,history,frame):
        def apply():
            self._owned(history)
            if frame is None:raise ValueError('inventory')
            value={key:frame[key] for key in ('rows','held','retired','include_retired')}
            value['sha256']=frame['hash'].hexdigest()
            self._owned(history);self._event('inventory',value)
        return self._call(apply)

    def read(self,history,row,sha):
        def apply():
            self._owned(history)
            if row is not None and not history.db.in_transaction:self.last_read=self._metadata(row,sha)
        return self._call(apply)

    def saved(self,history,row,sha):
        def apply():
            self._owned(history);value=self._metadata(row,sha)
            value['native_changes']=history.db.total_changes
            self._event('save',value)
        return self._call(apply)

    def select(self,history,row,at,slot):
        def apply():
            self._owned(history);key=checksum(row['id']);saved=self.last_save
            if (saved is None or saved['candidate_sha256']!=key or saved['held'] or saved['retired']
                    or saved['last_checked']!=row['last_checked'] or history.db.in_transaction):
                raise ValueError('selection')
            frontier=checksum([saved,at,slot]);cid=checksum([self.binding,'preparation',frontier])
            pair=(checksum([key,saved['body_sha256'],at,slot]),frontier)
            self.preparation.begin(cid,frontier);self.preparation.expect(cid,(pair,))
            self.preparation.seal_expected(cid,1,checksum((pair,)),checksum(['actual_selected_native_candidate',frontier]))
            self.selected=dict(cid=cid,pair=pair,candidate_sha256=key,frontier=frontier,at=at,slot=slot)
            self.started=True
        return self._call(apply)

    def prepared(self,history,identity,checkpoint):
        def apply():
            self._owned(history);selected=self.selected
            if selected is None or 'prepared_sha256' in selected:return
            key=checksum(identity);target=checksum(checkpoint)
            saved=next((value for value in (self.last_save,self.last_read) if value is not None
                and value['candidate_sha256']==key and value['checkpoint_sha256']==target),None)
            if (key!=selected['candidate_sha256'] or saved is None or history.db.in_transaction
                    or checkpoint['through']!=selected['at'] or checkpoint['consumed_slot']!=selected['slot']):
                raise ValueError('preparation')
            self.preparation.observe(selected['cid'],((*selected['pair'],'HISTORY_COMMITTED',
                saved['body_sha256'],None),))
            selected['prepared_sha256']=saved['body_sha256']
        return self._call(apply)

    def request(self,history,row):
        def apply():
            self._owned(history);selected=self.selected
            if (selected is None or 'prepared_sha256' not in selected
                    or selected['candidate_sha256']!=checksum(row['id'])):raise ValueError('request')
            frontier=checksum([selected['frontier'],selected['prepared_sha256']])
            cid=checksum([self.binding,'qualification',frontier]);pair=(selected['pair'][0],frontier)
            self.evaluation.begin(cid,frontier);self.evaluation.expect(cid,(pair,))
            self.evaluation.seal_expected(cid,1,checksum((pair,)),checksum(['actual_expensive_native_branch',frontier]))
            self.requested=dict(cid=cid,pair=pair,candidate_sha256=selected['candidate_sha256'])
            if self.turn is not None:self.turn['evaluation_requests']=1
        return self._call(apply)

    def evaluated(self,history,row,shared):
        def apply():
            self._owned(history);request=self.requested;saved=self.last_save
            if (request is None or saved is None or saved['candidate_sha256']!=request['candidate_sha256']
                    or saved['candidate_sha256']!=checksum(row['id'])
                    or saved['decision_id']!=row.get('decision_id') or history.db.in_transaction
                    or shared is None or shared.db.in_transaction):raise ValueError('evaluation')
            if shared.path.resolve()!=self.shared_path or self.shared_path.is_symlink():
                raise ValueError('decision_path')
            value=self.shared_path.stat(follow_symlinks=False)
            if (not stat.S_ISREG(value.st_mode) or (value.st_dev,value.st_ino)!=
                    (self.shared_description['device'],self.shared_description['inode'])):
                raise ValueError('decision_inode')
            _hash(row['decision_id'])
            self.evaluation.observe(request['cid'],((*request['pair'],'DECISION_COMMITTED',
                checksum([row['decision_id'],saved['body_sha256']]),None),))
            self.requested=None
        return self._call(apply)

    def attention(self,rows,*,now,minimum_age,maximum_age):
        def apply():
            self._owned()
            if type(rows) is not list or len(rows)>MAX_UNITS:raise ValueError('bound')
            eligible=sum(minimum_age<=now-row['graduation']['at']<=maximum_age for row in rows)
            self.turn=dict(native_nonheld_rows=len(rows),native_selected_rows=1 if rows else 0,
                native_unselected_rows=max(0,len(rows)-1),age_eligible_rows=eligible,
                evaluation_requests=0,eligibility_contract='AGE_ONLY_NOT_ALL_NATIVE_EVIDENCE_GATES')
        return self._call(apply)

    def finish(self):
        def apply():self._owned();self.selected=None;self.requested=None;self.turn=None
        return self._call(apply)

    def snapshot(self):
        def apply():
            self._owned(self.history)
            value=dict(schema='pump-survivor-native-work-v1',state='UNKNOWN' if self.loss else 'MEASURING',
                reason=self.loss,binding_sha256=checksum(self.binding),
                inherited_inventory=self.baseline,latest_native_inventory=self.latest,
                latest_native_attention=self.turn,
                committed_candidate_saves=self.save_count,committed_candidate_save_chain=self.save_chain,
                preparation=project_native_work(self.preparation.snapshot()),
                evaluation=project_native_work(self.evaluation.snapshot()),
                inventory_contract='COMPLETE_ORIGINAL_ROWS_NOT_ONE_REQUEST_PER_ELIGIBLE_CANDIDATE',
                source_membership='SEPARATE_AUTHENTICATED_SOURCE_INTERVAL_AND_INHERITED_UNION',
                queued_postgrad='SEPARATE_NATIVE_CANDIDATE_HISTORY_WORK',protection='SEPARATE_HELD_POPULATION',
                full_market_rate='UNKNOWN_REQUIRES_SOURCE_AND_ALL_NATIVE_ENDPOINTS',
                historical_completion=False,readiness_authority=False,funding_authority=False)
            if len(json.dumps(value,allow_nan=False).encode())>16384:
                for name in ('preparation','evaluation'):
                    stage=value[name]
                    if stage.get('schema')!='native-work-cohort-v1':continue
                    for key in ('active','closed'):
                        stage[key+'_samples_omitted']+=len(stage[key]);stage[key]=[]
            if len(json.dumps(value,allow_nan=False).encode())>16384:raise ValueError('bound')
            self._owned(self.history);return value
        value=self._call(apply)
        return value if value is not None else dict(state='UNKNOWN',reason='NATIVE_BOUNDARY_UNAVAILABLE',funding_authority=False)


def create_survivor_work(history_path,epoch,policy):
    if os.environ.get('MM_ECONOMIC_COHORT_DIAGNOSTICS')!='1':return None
    try:
        from ..operational.normal_pump_boot import current_pump_owner_context
        owner=current_pump_owner_context()
        if owner is None:return None
        return PumpSurvivorWork(owner,history_path,epoch,policy)
    except Exception:return None
