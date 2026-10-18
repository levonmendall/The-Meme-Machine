"""Actual Current input traversal and decision publications, without authority.

The original cursor, five-second gates, provider work and FULL decision writer
own every boundary here. A missing hook remains pending; this is neither a
per-trade strategy mandate nor a source/history/protection completion verdict.
"""
import os
import json
from pathlib import Path
import threading
import uuid

from .economic_cohort import checksum, _hash, MAX_POSITION
from .native_work_cohort import NativeWorkCohorts, MAX_ROWS, NATIVE_ORDER, project_native_work


class PumpCurrentWork:
    def __init__(self, history_path, epoch, policy_hash):
        if type(epoch) is not str or not 0<len(epoch.encode())<=256:
            raise ValueError('native_current_epoch')
        self.history_path = str(Path(history_path).resolve())
        self.owner = (os.getpid(), threading.get_native_id())
        instance=os.environ.get('MM_LANE_PROCESS_INSTANCE')
        if (type(instance) is not str or len(instance)!=32
                or any(c not in '0123456789abcdef' for c in instance)):
            instance=uuid.uuid4().hex
        self.binding = dict(owner_pid=self.owner[0], owner_tid=self.owner[1],
            owner_instance=instance, epoch_sha256=checksum(epoch),
            policy_sha256=_hash(policy_hash), regime='pump_current')
        self.inputs = NativeWorkCohorts(self.binding, 'DISCOVERY_INPUT')
        self.evaluations = NativeWorkCohorts(self.binding, 'NATIVE_EVALUATION')
        self.source = None
        self.ordered_windows=False;self.native_cursor=0
        self.started = False
        self.batch = None
        self.requested = None
        self.decision_stages=dict(optimistic_preflight=0,full_point_in_time=0)
        self.input_context=None;self.input_context_unavailable=False
        try:
            from .pump_current_input_prefix import create_input_context
            self.input_context=create_input_context(epoch,instance)
        except Exception:self.input_context_unavailable=True

    def unavailable(self, reason='NATIVE_BOUNDARY_UNAVAILABLE'):
        self.inputs.unavailable(reason); self.evaluations.unavailable(reason)
        context=getattr(self,'input_context',None)
        if context is not None:context.unavailable()

    def _owned(self):
        if self.owner != (os.getpid(), threading.get_native_id()):
            raise ValueError('native_current_owner')

    def source_observation(self, value):
        """Projection of an existing authenticated generation record, not a seal."""
        try:
            self._owned()
            if value is None:
                if self.source is not None:self.unavailable()
                return
            if (type(value) is not dict or set(value) != {'identity_sha256','source_pid',
                    'source_start_ticks','generation','instance_sha256','epoch_sha256'}
                    or any(type(value[k]) is not int or not 0 < value[k] <= MAX_POSITION
                        for k in ('source_pid','source_start_ticks'))
                    or type(value['generation']) is not str or len(value['generation']) != 32
                    or any(c not in '0123456789abcdef' for c in value['generation'])
                    or value['epoch_sha256'] != self.binding['epoch_sha256']):
                raise ValueError('source')
            for key in ('identity_sha256','instance_sha256','epoch_sha256'): _hash(value[key])
            detached = dict(value)
            if self.source is not None:
                if self.source != detached: raise ValueError('changed_source')
                return
            if self.started: raise ValueError('late_source_binding')
            if self.inputs.loss is not None or self.evaluations.loss is not None:return
            self.source = detached
            binding = dict(self.binding, source_identity_sha256=value['identity_sha256'])
            options={}
            if self.input_context is not None:
                self.input_context.bind_source(detached)
                if self.input_context.loss is None and self.input_context.prefixes is not None:
                    binding['private_owner_sha256']=self.input_context.owner.identity_sha256
                    options['native_order']=NATIVE_ORDER
                    self.ordered_windows=True
                    self.input_context.allow_staged_retry=True
            self.inputs = NativeWorkCohorts(binding, 'DISCOVERY_INPUT',**options)
            self.evaluations = NativeWorkCohorts(binding, 'NATIVE_EVALUATION',**options)
        except Exception: self.unavailable()

    def capture_input_prefix(self,reader,first,rows,records,*,as_of):
        if self.input_context is None:return None
        from .stop import requested
        ticket=self.input_context.capture(reader,first,rows,records,as_of=as_of,cancelled=requested.is_set)
        if self.ordered_windows and self.input_context.loss is not None:self.unavailable()
        return ticket

    def retained_input_prefix(self,ticket,history,retained):
        if ticket is not None and self.input_context is not None:
            self.input_context.retained(ticket,history,retained,self.history_path)
            if self.ordered_windows and self.input_context.loss is not None:self.unavailable()

    def input_snapshot_closed(self,ticket,db):
        if self.ordered_windows and ticket is not None:
            self.input_context.snapshot_closed(ticket,db)

    def capture(self, first, rows, records, events):
        """Independent entire original bounded outbox selection, before outcomes."""
        try:
            self._owned()
            if not self.ordered_windows and self.batch is not None and not self.batch['finished']:
                raise ValueError('batch')
            if (type(first) is not int
                    or not 0 <= first <= MAX_POSITION or type(rows) is not list
                    or len(rows) > MAX_ROWS or type(records) is not list or type(events) is not list
                    or len(records) != len(rows) or len(events) != len(rows)):
                raise ValueError('batch')
            if self.ordered_windows and first!=self.native_cursor:raise ValueError('native_cursor')
            if not rows:
                if self.ordered_windows and self.batch is not None and not self.batch['retained']:
                    return None
                self.batch = None; self.requested = None
                return None
            from ..solana_selective_history import SelectiveHistory
            selected = []
            lookup = {}
            previous = first
            for raw, record, event in zip(rows, records, events, strict=True):
                sequence = raw[0]
                if type(sequence) is not int or not previous < sequence <= MAX_POSITION:
                    raise ValueError('sequence')
                previous = sequence
                if record['identity'] != raw[3] or record['scope'] != 'program:pump':
                    raise ValueError('identity')
                economic_hash = SelectiveHistory.content_hash(record)
                key = checksum([record['scope'], record['identity'], economic_hash, sequence])
                value = checksum([record['scope'], record['identity'], economic_hash,
                    sequence, raw[8]])
                selected.append((key, value))
                lookup[id(event)] = dict(pair=(key, value), mint=event.get('mint'),
                    native_filtered=event.get('event_type') in ('create','migration'),
                    outcome=None)
            frontier = checksum([first, previous, selected, self.source])
            cid = (checksum([self.inputs.binding,NATIVE_ORDER,previous,frontier])
                if self.ordered_windows else checksum([self.binding, frontier]))
            self._owned()
            if self.batch is not None and not self.batch['finished']:
                old=self.batch
                if (not self.ordered_windows or old['retained'] or old['cid']!=cid
                        or old['frontier']!=frontier or old['requests'] or old['evaluation_started']
                        or self.inputs.loss is not None or self.evaluations.loss is not None):
                    raise ValueError('batch')
                # Exact uncommitted retry: retain original expected membership
                # and issuance, replacing only ephemeral decoded event handles.
                old['rows']=lookup;return old
            self.started = True
            self._begin(self.inputs,cid,frontier,previous); self.inputs.expect(cid, selected)
            self.inputs.seal_expected(cid, len(selected), checksum(tuple(sorted(selected))),
                checksum(['complete_original_discovery_prefix', first, previous, selected]))
            self.batch = dict(cid=cid, frontier=frontier, rows=lookup, retained=False,native_position=previous,
                requests={}, finished=False, evaluation_started=False)
            self.requested = None
            return self.batch
        except Exception:
            self.unavailable(); return None

    def _begin(self,meter,cid,frontier,position):
        if self.ordered_windows:
            meter.begin(cid,frontier,native_window=(meter.binding,NATIVE_ORDER,position,frontier))
        else:meter.begin(cid,frontier)

    def retained(self, batch, history, retained):
        try:
            self._owned()
            if (batch is not self.batch or history.db.in_transaction
                    or str(history.path.resolve()) != self.history_path
                    or type(retained) is not int or retained!=len(batch['rows'])):
                raise ValueError('publication')
            batch['retained'] = True
            if self.ordered_windows:self.native_cursor=batch['native_position']
            for item in batch['rows'].values():
                if item['native_filtered']:
                    self._input(item, 'NATIVE_FILTERED')
        except Exception: self.unavailable('TRANSACTION_FAILED')

    def _input(self, item, disposition, due=None):
        if not self.batch['retained']: raise ValueError('history_missing')
        self.inputs.observe(self.batch['cid'], ((*item['pair'], disposition, None, due),))
        item['outcome'] = disposition

    def disposition(self, event, disposition, due=None):
        try:
            self._owned(); self.requested = None
            item = self.batch['rows'][id(event)]
            self._input(item, disposition, due)
        except Exception: self.unavailable()

    def request(self, event, at, mode):
        try:
            self._owned()
            if type(at) is not int or not 0 <= at <= MAX_POSITION or type(mode) is not str:
                raise ValueError('request')
            batch = self.batch; item = batch['rows'][id(event)]
            self._input(item, 'REQUESTED')
            if not batch['evaluation_started']:
                self._begin(self.evaluations,batch['cid'],batch['frontier'],batch['native_position'])
                batch['evaluation_started'] = True
            key = checksum([item['pair'], item['mint'], mode, at])
            value = checksum([item['pair'], batch['frontier'], mode, at])
            request = dict(pair=(key,value), mint=item['mint'], mode=mode, completed=None)
            old = batch['requests'].get(key)
            if old is not None:
                if any(old[name]!=request[name] for name in ('pair','mint','mode')):raise ValueError('request')
                request=old
            batch['requests'][key] = request
            self.evaluations.expect(batch['cid'], ((key,value),))
            self.requested = request
        except Exception: self.unavailable()

    def decision(self, history, mint, mode, stage, qualified, identity):
        """Only after original record_decision returned from a real outer COMMIT."""
        try:
            self._owned()
            if (self.requested is None or self.requested['mint'] != mint
                    or self.requested['mode'] != mode or history.db.in_transaction
                    or str(history.path.resolve()) != self.history_path
                    or stage not in ('optimistic_preflight','full_point_in_time')
                    or stage == 'optimistic_preflight' and qualified is not False):
                raise ValueError('decision')
            self.evaluations.observe(self.batch['cid'], ((*self.requested['pair'],
                'DECISION_COMMITTED', _hash(identity), None),))
            if self.evaluations.loss is None and self.requested['completed'] is None:
                self.requested['completed']=identity;self.decision_stages[stage]+=1
        except Exception: self.unavailable('TRANSACTION_FAILED')

    def finish(self):
        try:
            self._owned(); batch = self.batch
            if batch is None or batch['finished']: return
            for item in batch['rows'].values():
                if item['outcome'] is None: self._input(item, 'COVERAGE_UNAVAILABLE')
            if not batch['evaluation_started'] and all(item['outcome'] in
                    ('NATIVE_FILTERED','POLICY_FILTERED','COALESCED_NOT_DUE')
                    for item in batch['rows'].values()):
                # Genuine complete original policy traversal can have zero due
                # requests. Its independent input census must still be whole.
                self._begin(self.evaluations,batch['cid'],batch['frontier'],batch['native_position'])
                batch['evaluation_started']=True
            if batch['evaluation_started']:
                for request in batch['requests'].values():
                    if request['completed'] is None:
                        self.evaluations.observe(batch['cid'],((*request['pair'],'INCOMPLETE',None,None),))
                pairs = tuple(sorted(value['pair'] for value in batch['requests'].values()))
                self.evaluations.seal_expected(batch['cid'], len(pairs), checksum(pairs),
                    checksum(['complete_original_current_due_traversal', batch['frontier'], pairs]))
            batch['finished'] = True; self.requested = None
        except Exception: self.unavailable()

    def snapshot(self):
        try:
            self._owned()
            return project_current_work(dict(schema='pump-current-native-work-v1',
                owner=dict(pid=self.owner[0],native_thread_id=self.owner[1],
                    instance_sha256=checksum(self.binding['owner_instance']),
                    epoch_sha256=self.binding['epoch_sha256'],policy_sha256=self.binding['policy_sha256'],
                    private_owner_binding='UNBOUND_REQUIRES_ACTUAL_SUPERVISOR_CORRELATION'),
                source_identity_sha256=None if self.source is None else self.source['identity_sha256'],
                source_generation_bound=self.source is not None,
                source_record_membership='UNKNOWN_REQUIRES_ACTUAL_PUBLICATION_FRONTIER',
                native_input_prefix=(self.input_context.snapshot() if self.input_context is not None else
                    dict(state='UNKNOWN',reason='INPUT_PREFIX_UNAVAILABLE',funding_authority=False)
                    if self.input_context_unavailable else None),
                discovery=project_native_work(self.inputs.snapshot()),
                evaluation=project_native_work(self.evaluations.snapshot()),
                actual_decision_stages=dict(self.decision_stages),
                evaluation_mode='late_curve_acceleration',
                evaluation_contract='ORIGINAL_OPTIMISTIC_REJECTION_OR_FULL_POINT_IN_TIME_DECISION',
                postgrad='UNEXERCISED', survivor='SEPARATE_NATIVE_OWNER',
                protection='SEPARATE_ACTUAL_HELD_POPULATION',
                full_market_rate='UNKNOWN_REQUIRES_ALL_SOURCE_AND_NATIVE_CONSUMER_STAGES',
                historical_completion=False, readiness_authority=False, funding_authority=False))
        except Exception:
            return dict(state='UNKNOWN', reason='NATIVE_BOUNDARY_UNAVAILABLE', funding_authority=False)


def create_current_work(history, epoch, policy_hash):
    if os.environ.get('MM_ECONOMIC_COHORT_DIAGNOSTICS') != '1': return None
    try:
        if history is None: return None
        return PumpCurrentWork(history.path, epoch, policy_hash)
    except Exception: return None


def source_generation_projection(value):
    """Use only the original already-read current-generation health wrapper.

    This shape/hash validator does not acquire a boot capability or certify the
    mutable census. The supervisor must independently join the immutable digest
    to its real launch/source/owner population before any normal composite.
    """
    if value is None: return None
    try:
        from ..operational.normal_source_boot import validate_current_generation
        current = validate_current_generation(json.dumps(value, sort_keys=True, separators=(',',':')))
        identity = current['identity']; launch = identity['launch']
        return dict(identity_sha256=current['identity_sha256'],
            source_pid=identity['source']['pid'], source_start_ticks=int(identity['source']['start_ticks']),
            generation=identity['generation'], instance_sha256=checksum(launch['instance']),
            epoch_sha256=checksum(launch['epoch_id']))
    except Exception: return dict(state='UNKNOWN')


def project_current_work(value):
    """Retain fixed clocks/counts/hashes in the original diagnostic transport."""
    try:
        if type(value) is not dict or value.get('schema')!='pump-current-native-work-v1':
            raise ValueError('schema')
        source=value['source_identity_sha256'];bound=value['source_generation_bound']
        if type(bound) is not bool or (source is None)!= (not bound):raise ValueError('source')
        if source is not None:_hash(source)
        raw_owner=value['owner']
        if type(raw_owner) is not dict:raise ValueError('owner')
        owner={key:raw_owner[key] for key in ('pid','native_thread_id')}
        if any(type(number) is not int or not 0<number<=MAX_POSITION for number in owner.values()):
            raise ValueError('owner')
        owner.update({key:_hash(raw_owner[key]) for key in ('instance_sha256','epoch_sha256','policy_sha256')})
        owner['private_owner_binding']='UNBOUND_REQUIRES_ACTUAL_SUPERVISOR_CORRELATION'
        stages=value['actual_decision_stages']
        if (type(stages) is not dict or set(stages)!={'optimistic_preflight','full_point_in_time'}
                or any(type(number) is not int or not 0<=number<=MAX_POSITION for number in stages.values())):
            raise ValueError('stages')
        result=dict(schema='pump-current-native-work-v1',owner=owner,
            source_identity_sha256=source,source_generation_bound=bound,
            source_record_membership='UNKNOWN_REQUIRES_ACTUAL_PUBLICATION_FRONTIER',
            discovery=project_native_work(value['discovery']),evaluation=project_native_work(value['evaluation']),
            actual_decision_stages=dict(stages),
            evaluation_mode='late_curve_acceleration',
            evaluation_contract='ORIGINAL_OPTIMISTIC_REJECTION_OR_FULL_POINT_IN_TIME_DECISION',
            postgrad='UNEXERCISED',survivor='SEPARATE_NATIVE_OWNER',
            protection='SEPARATE_ACTUAL_HELD_POPULATION',
            full_market_rate='UNKNOWN_REQUIRES_ALL_SOURCE_AND_NATIVE_CONSUMER_STAGES',
            historical_completion=False,readiness_authority=False,funding_authority=False)
        from .pump_current_input_prefix import project_input_context
        result['native_input_prefix']=project_input_context(value.get('native_input_prefix'))
        # Source/native census details remain represented by complete counts and
        # digests if optional common samples no longer fit the original envelope.
        if len(json.dumps(result,allow_nan=False).encode())>16384:
            for name in ('discovery','evaluation'):
                stage=result[name]
                if stage.get('schema')!='native-work-cohort-v1':continue
                for key in ('active','closed'):
                    stage[key+'_samples_omitted']+=len(stage[key]);stage[key]=[]
        if len(json.dumps(result,allow_nan=False).encode())>16384:raise ValueError('bound')
        return result
    except Exception:return dict(state='UNKNOWN',reason='PROJECTION_UNAVAILABLE',funding_authority=False)
