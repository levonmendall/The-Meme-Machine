"""Source-owned restart inputs, never replay completion or funding authority.

Only an acquired normal source capability enables these rows. Session opening
precedes subscription I/O; prefix updates share the original durable batch.
The read port derives obligations and does not settle the failed generation.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
import threading
import time

from .normal_boot_record import canonical,digest,hex_value,require

PLANES=('control','scout','rolling','candidate')
PROGRAM_SCOPES=('program:meteora','program:pump','program:pumpswap')
MAX_ROWS=100000
MAX_BODY=16384
MAX_INPUT_BYTES=32*1024*1024
HANDLER_SCRATCH_BYTES=4*1024*1024
GENERATION_TABLE='native_source_generations'
SESSION_TABLE='native_source_sessions'
_ISSUER=object()
_SCHEMA=(
    '''CREATE TABLE IF NOT EXISTS native_source_generations(
        id TEXT PRIMARY KEY,identity TEXT NOT NULL,identity_hash TEXT NOT NULL,
        provider_identity TEXT NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS native_source_sessions(
        generation TEXT NOT NULL,id TEXT NOT NULL,session TEXT NOT NULL,
        body TEXT NOT NULL,hash TEXT NOT NULL,PRIMARY KEY(generation,id))''',
    'CREATE INDEX IF NOT EXISTS native_source_session_group ON native_source_sessions(generation,session,id)')


def _bounded(value):
    raw=canonical(value).decode()
    require(len(raw.encode())<=MAX_BODY,'source_registry_body_bound')
    return raw,hashlib.sha256(raw.encode()).hexdigest()


def _read(raw,checksum):
    from .normal_boot_record import _json
    require(type(raw) is str and len(raw.encode())<=MAX_BODY
        and hashlib.sha256(raw.encode()).hexdigest()==checksum,'source_registry_body_hash')
    return _json(raw)


def _number(value):return type(value) is int and 0<=value<2**63


def _prefix():
    return dict(records=0,batches=0,first_sequence=None,last_sequence=None,prefix_sha256='0'*64)


def _validate_prefix(value):
    require(type(value) is dict and set(value)=={'records','batches','first_sequence','last_sequence','prefix_sha256'}
        and _number(value['records']) and _number(value['batches']) and value['batches']<=value['records']
        and all(value[key] is None if value['records']==0 else _number(value[key])
            for key in ('first_sequence','last_sequence'))
        and (value['records']==0 or value['first_sequence']<=value['last_sequence'])
        and (value['batches']==0)==(value['records']==0)
        and (value['records']!=0 or value['prefix_sha256']=='0'*64)
        and hex_value(value['prefix_sha256'],64),'source_registry_economic_shape')


def _validate_frontiers(value):
    require(type(value) is dict and set(value)=={'control_slot','programs','history_outbox_rowid',
        'pending_proof_rowid','observation_id','economic_sequence','program_outbox_sequence'},
        'source_registry_frontier_shape')
    require(all(value[key] is None or _number(value[key]) for key in
        ('control_slot','history_outbox_rowid','pending_proof_rowid','observation_id','economic_sequence')),
        'source_registry_frontier_value')
    require(type(value['program_outbox_sequence']) is dict
        and set(value['program_outbox_sequence'])==set(PROGRAM_SCOPES)
        and all(item is None or _number(item) for item in value['program_outbox_sequence'].values()),
        'source_registry_frontier_program_outbox')
    require(type(value['programs']) is dict and set(value['programs'])=={'pump','pumpswap'},
        'source_registry_frontier_programs')
    for row in value['programs'].values():
        require(row is None or type(row) is list and len(row)==3 and _number(row[0])
            and all(type(item) is str and 0<len(item)<=128 for item in row[1:]),
            'source_registry_frontier_program')


def _validate_generation(value):
    keys={'schema','generation','identity_sha256','started_monotonic','initial_frontiers',
        'sessions','terminal_sha256','planes','economic','active_programs'}
    require(type(value) is dict and set(value) in (keys,keys|{'terminal_frontiers'})
        and value['schema']=='native-source-registry-v1'
        and hex_value(value['generation'],32) and hex_value(value['identity_sha256'],64)
        and _number(value['sessions']) and value['sessions']<=MAX_ROWS,
        'source_registry_generation_shape')
    require(type(value['started_monotonic']) in (int,float) and
        math.isfinite(value['started_monotonic']) and value['started_monotonic']>=0,
        'source_registry_clock')
    require(value['terminal_sha256'] is None or hex_value(value['terminal_sha256'],64),
        'source_registry_terminal_shape')
    require(('terminal_frontiers' in value)==(value['terminal_sha256'] is not None),
        'source_registry_terminal_frontiers')
    _validate_frontiers(value['initial_frontiers'])
    if 'terminal_frontiers' in value:_validate_frontiers(value['terminal_frontiers'])
    require(type(value['planes']) is dict and set(value['planes'])==set(PLANES),
        'source_registry_plane_population')
    for row in value['planes'].values():
        require(type(row) is dict and set(row)=={'batches','frames','last_slot','prefix_sha256'}
            and _number(row['batches']) and _number(row['frames'])
            and row['batches']<=row['frames']<=64*row['batches']
            and (row['last_slot'] is None if row['frames']==0 else
                _number(row['last_slot']) and row['last_slot']>0)
            and hex_value(row['prefix_sha256'],64),'source_registry_plane_shape')
    require(type(value['active_programs']) is list and value['active_programs']==sorted(set(value['active_programs']))
        and all(scope in PROGRAM_SCOPES for scope in value['active_programs']),
        'source_registry_active_programs')
    economic=value['economic'];require(type(economic) is dict and set(economic)=={'all','programs'}
        and type(economic['programs']) is dict and set(economic['programs'])==set(PROGRAM_SCOPES),
        'source_registry_program_population')
    for prefix in (economic['all'],*economic['programs'].values()):_validate_prefix(prefix)
    require(economic['all']['records']==sum(row['records'] for row in economic['programs'].values()),
        'source_registry_program_counts')
    return value


def _validate_session(value):
    require(type(value) is dict and set(value)=={'schema','generation','identity_sha256',
        'stream','session','plane','transport','scopes','lower_slot','filter_sha256',
        'opened_monotonic','stopped','closure'} and value['schema']=='native-source-session-v1'
        and all(hex_value(value[key],32) for key in ('generation','stream','session'))
        and all(hex_value(value[key],64) for key in ('identity_sha256','filter_sha256'))
        and value['plane'] in PLANES and value['transport'] in ('yellowstone','websocket')
        and _number(value['lower_slot']) and value['lower_slot']>0
        and type(value['stopped']) is bool,'source_registry_session_shape')
    require(type(value['opened_monotonic']) in (int,float) and
        math.isfinite(value['opened_monotonic']) and value['opened_monotonic']>=0,
        'source_registry_clock')
    scopes=value['scopes']
    require(type(scopes) is list and 0<len(scopes)<=50 and all(type(scope) is str
        and 0<len(scope.encode())<=256 for scope in scopes)
        and scopes==sorted(set(scopes)),'source_registry_session_scopes')
    closure=value['closure']
    require(closure is None or type(closure) is dict and set(closure)=={'observation_id','kind','sha256'}
        and _number(closure['observation_id']) and closure['observation_id']>0
        and closure['kind'] in ('source_session_drain','control_session_drain')
        and hex_value(closure['sha256'],64) and value['stopped'],
        'source_registry_session_closure')
    return value


def _tail(db,table,column):
    row=db.execute('SELECT '+column+' FROM '+table+' ORDER BY '+column+' DESC LIMIT 1').fetchone()
    return None if row is None else row[0]


def _frontiers(db):
    from meme_machine.solana_selective_runtime import CONTROL
    from meme_machine.solana_rolling_history import program_scope
    row=db.execute('SELECT slot FROM stream_receipts WHERE scope=? AND sealed=1 '
        'ORDER BY slot DESC LIMIT 1',(CONTROL,)).fetchone()
    programs={}
    for family in ('pump','pumpswap'):
        point=db.execute('SELECT slot,hash,session FROM candidate_blocks WHERE scope=?',
            (program_scope(family),)).fetchone()
        programs[family]=None if point is None else list(point)
    return dict(control_slot=None if row is None else row[0],programs=programs,
        history_outbox_rowid=_tail(db,'candidate_history_outbox','rowid'),
        pending_proof_rowid=_tail(db,'candidate_pending_proofs','rowid'),
        observation_id=_tail(db,'acquisition_observations','id'),
        economic_sequence=_tail(db,'candidate_outbox','sequence'),
        program_outbox_sequence={scope:(lambda row:None if row is None else row[0])(
            db.execute('SELECT sequence FROM candidate_outbox WHERE scope=? ORDER BY sequence DESC LIMIT 1',
                (scope,)).fetchone()) for scope in PROGRAM_SCOPES})


class NativeSourceRegistry:
    """The genuine source writer is the only producer of this generation."""
    def __init__(self,state,capability):
        from .normal_source_boot import require_native_generation
        self.capability=require_native_generation(capability)
        self.capability._owner(state)
        self.generation=capability.generation;self.identity=capability.identity_sha256
        self._state=state
        self.owner=(os.getpid(),threading.get_ident())
        from meme_machine.solana_selective_history import FAMILIES
        require(tuple(sorted(FAMILIES.values()))==PROGRAM_SCOPES,'source_registry_program_contract')
        with state.writer.transaction():
            for sql in _SCHEMA:state.writer.db.execute(sql)
            require(state.writer.db.execute('SELECT 1 FROM '+GENERATION_TABLE+' WHERE id=?',
                (self.generation,)).fetchone() is None,'source_registry_generation_exists')
            body=dict(schema='native-source-registry-v1',generation=self.generation,
                identity_sha256=self.identity,started_monotonic=time.monotonic(),
                initial_frontiers=_frontiers(state.writer.db),sessions=0,terminal_sha256=None,
                active_programs=sorted(FAMILIES[family] for family in state.selective.active_families),
                economic=dict(all=_prefix(),programs={scope:_prefix() for scope in PROGRAM_SCOPES}),
                planes={plane:dict(batches=0,frames=0,last_slot=None,prefix_sha256='0'*64)
                    for plane in PLANES})
            raw,checksum=_bounded(body)
            state.writer.db.execute('INSERT INTO '+GENERATION_TABLE+' VALUES(?,?,?,?,?,?)',
                (self.generation,canonical(capability.identity()).decode(),self.identity,
                 state.fence.endpoint_identity,raw,checksum))

    def _owner(self,state):
        self.capability._owner(state)
        require(state is self._state and self.owner==(os.getpid(),threading.get_ident()),
            'source_registry_owner')

    def _generation(self,state):
        self._owner(state)
        row=state.writer.db.execute('SELECT body,hash FROM '+GENERATION_TABLE+' WHERE id=?',
            (self.generation,)).fetchone()
        require(row is not None,'source_registry_generation_missing')
        return _validate_generation(_read(*row))

    def _save_generation(self,state,body):
        raw,checksum=_bounded(body)
        state.writer.db.execute('UPDATE '+GENERATION_TABLE+' SET body=?,hash=? WHERE id=?',
            (raw,checksum,self.generation))

    def open(self,state,*,stream,session,plane,transport,scopes,lower_slot,filter_sha256):
        self._owner(state)
        require(hex_value(stream,32) and hex_value(session,32) and plane in PLANES
            and transport in ('yellowstone','websocket') and hex_value(filter_sha256,64)
            and type(lower_slot) is int and lower_slot>0,'source_registry_session_identity')
        require(type(scopes) in (tuple,list) and 0<len(scopes)<=50 and len(set(scopes))==len(scopes)
            and all(type(scope) is str and 0<len(scope.encode())<=256 for scope in scopes),
            'source_registry_session_scopes')
        with state.writer.transaction():
            body=self._generation(state)
            require(body['terminal_sha256'] is None and body['sessions']<MAX_ROWS,
                'source_registry_session_population_bound')
            value=dict(schema='native-source-session-v1',generation=self.generation,
                identity_sha256=self.identity,stream=stream,session=session,plane=plane,
                transport=transport,scopes=sorted(scopes),lower_slot=lower_slot,
                filter_sha256=filter_sha256,opened_monotonic=time.monotonic(),
                stopped=False,closure=None)
            raw,checksum=_bounded(value)
            state.writer.db.execute('INSERT INTO '+SESSION_TABLE+' VALUES(?,?,?,?,?)',
                (self.generation,stream,session,raw,checksum))
            body['sessions']+=1;self._save_generation(state,body)

    def stopped(self,state,stream):
        self._owner(state)
        with state.writer.transaction():
            row=state.writer.db.execute('SELECT body,hash FROM '+SESSION_TABLE+' WHERE generation=? AND id=?',
                (self.generation,stream)).fetchone()
            require(row is not None,'source_registry_session_missing')
            value=_validate_session(_read(*row));require(value['stopped'] is False,'source_registry_session_already_stopped')
            value['stopped']=True
            raw,checksum=_bounded(value)
            state.writer.db.execute('UPDATE '+SESSION_TABLE+' SET body=?,hash=? WHERE generation=? AND id=?',
                (raw,checksum,self.generation,stream))

    def committed(self,state,plane,slots):
        """Caller must be inside the ORIGINAL enclosing native transaction."""
        self._owner(state)
        require(state.writer.db.in_transaction and plane in PLANES and type(slots) in (list,tuple)
            and 0<len(slots)<=64 and all(type(slot) is int and slot>0 for slot in slots),
            'source_registry_commit_boundary')
        body=self._generation(state);require(body['terminal_sha256'] is None,'source_registry_terminal')
        value=body['planes'][plane]
        value.update(batches=value['batches']+1,frames=value['frames']+len(slots),
            last_slot=max(value['last_slot'] or 0,*slots),
            prefix_sha256=digest([value['prefix_sha256'],plane,slots]))
        self._save_generation(state,body)

    def published(self,history,pending):
        """Use only the original already-inserted outbox sequence population."""
        state=self._state;self._owner(state)
        require(history.writer is state.writer and history.db.in_transaction,
            'source_registry_publication_boundary')
        if not pending:return
        body=self._generation(state);require(body['terminal_sha256'] is None,'source_registry_terminal')
        value=body['economic']
        prefixes={'all':value['all'],**value['programs']}
        hashes={key:prefix['prefix_sha256'] for key,prefix in prefixes.items()}
        first={};last={};count={key:0 for key in prefixes}
        for row in pending:
            require(type(row) in (list,tuple) and len(row)==5 and _number(row[0])
                and type(row[1]) is str and 0<len(row[1].encode())<=512
                and row[2] in PROGRAM_SCOPES
                and _number(row[3]) and type(row[4]) in (int,float) and math.isfinite(row[4]),
                'source_registry_publication_shape')
            encoded=canonical(row)
            for key in ('all',row[2]):
                require(key not in last or row[0]>last[key],'source_registry_publication_order')
                hashes[key]=hashlib.sha256(b'['+canonical(hashes[key])+b','+encoded+b']').hexdigest()
                first.setdefault(key,row[0]);last[key]=row[0];count[key]+=1
        require(count['all']<=MAX_ROWS,'source_registry_publication_frontier')
        for key,prefix in prefixes.items():
            if not count[key]:continue
            require(prefix['last_sequence'] is None or first[key]>prefix['last_sequence'],
                'source_registry_publication_frontier')
            prefix.update(records=prefix['records']+count[key],batches=prefix['batches']+1,
                first_sequence=first[key] if prefix['first_sequence'] is None else prefix['first_sequence'],
                last_sequence=last[key],prefix_sha256=hashes[key])
        self._save_generation(state,body)
        # Descriptive same-transaction publication, not a reader-supplied ACK.
        state.fence._health('source_generation_frontier',dict(schema='normal-source-publication-frontier-v1',
            identity_sha256=self.identity,generation=self.generation,
            active_programs=body['active_programs'],economic=deepcopy(value)))

    def closed(self,state,session,observation):
        """Reference the real original joined teardown receipt, not its text."""
        self._owner(state)
        require(hex_value(session,32) and type(observation) is int and observation>0,
            'source_registry_closure_identity')
        with state.writer.transaction():
            row=state.writer.db.execute('SELECT CASE WHEN octet_length(kind)<=64 THEN kind END,'
                'CASE WHEN octet_length(body)<=? THEN body END '
                'FROM acquisition_observations WHERE id=?',(128*1024,observation)).fetchone()
            require(row is not None and row[0] in ('source_session_drain','control_session_drain')
                and type(row[1]) is str and len(row[1].encode())<=128*1024,
                'source_registry_closure_receipt')
            receipt=json.loads(row[1]);require(receipt.get('session')==session,'source_registry_closure_session')
            # A session spans its native and optional log transport. Closing
            # references the same real receipt only after the original join.
            rows=state.writer.db.execute('SELECT id,body,hash FROM '+SESSION_TABLE+
                ' WHERE generation=? AND session=? ORDER BY id',(self.generation,session))
            selected=[]
            for stream,raw,checksum in rows:
                value=_validate_session(_read(raw,checksum))
                if value['session']==session:selected.append((stream,value))
            require(0<len(selected)<=50,'source_registry_closure_session_missing')
            for stream,value in selected:
                require(value['stopped'] and value['closure'] is None,'source_registry_closure_before_stop')
                value['closure']=dict(observation_id=observation,kind=row[0],
                    sha256=hashlib.sha256(row[1].encode()).hexdigest())
                raw,checksum=_bounded(value)
                state.writer.db.execute('UPDATE '+SESSION_TABLE+' SET body=?,hash=? WHERE generation=? AND id=?',
                    (raw,checksum,self.generation,stream))

    def terminal(self,state,wrapper):
        self._owner(state)
        require(state.writer.db.in_transaction,'source_registry_terminal_boundary')
        body=self._generation(state);require(body['terminal_sha256'] is None,'source_registry_terminal')
        body['terminal_sha256']=hashlib.sha256(canonical(wrapper)).hexdigest()
        body['terminal_frontiers']=_frontiers(state.writer.db)
        self._save_generation(state,body)


class FailedGenerationPlan:
    """A finite read-scope's remaining work; never a completed recovery."""
    def __init__(self,context,value,marker,*,_issuer=None):
        require(_issuer is _ISSUER,'source_registry_plan_issuer')
        self._context=context;self._value=value;self._marker=marker
        self._owner=(os.getpid(),threading.get_ident())

    def value(self):
        require(self._owner==(os.getpid(),threading.get_ident()),'source_registry_plan_owner')
        self._context.verify_boundary()
        with self._context.database(self._context.root/'shared/solana-evidence.sqlite') as db:
            require(_marker(db)==self._marker,'source_registry_plan_generation_changed')
        return deepcopy(self._value)


def _marker(db):
    return (db.total_changes,db.execute('PRAGMA data_version').fetchone()[0],
        db.execute('PRAGMA schema_version').fetchone()[0])


def _handlers(db,current,sessions,context):
    """Join the original bounded failed-callback population to its real gaps.

    A returned callback is deliberately absent from HandlerLedger. This join
    cannot infer its economic effects or an unobserved crash tail from counts.
    """
    from meme_machine.solana_source_drain import (HANDLER_RECOVERY_KEY,HandlerLedger,
        CONTROL_RECOVERY_KEY,control_recovery,_health_from_db,_retained_handlers)
    from meme_machine.solana_selective_runtime import CONTROL
    ledger=current['census']['handler_accounting'];rows=ledger['records']
    require(ledger['valid'] and type(rows) is list,'source_registry_handler_population_unknown')
    raw=_health_from_db(db,HANDLER_RECOVERY_KEY,HandlerLedger.maximum_bytes)
    retained=[] if raw is None else _retained_handlers(raw)
    generation=current['identity']['generation'];selected={}
    for row in retained:
        if row.get('run')!=generation:continue
        require(_number(row.get('id')) and row['id'] not in selected,
            'source_registry_handler_duplicate')
        selected[row['id']]=row
    result=[];seen=set();terminal=current['census'].get('terminal') is True
    if not terminal:
        # RUNNING is the initial census, not a live per-callback snapshot. Keep
        # every later retained failure from this run without claiming absence.
        observed={row.get('id') for row in rows if type(row) is dict}
        rows=[*rows,*({key:value for key,value in saved.items() if key not in
            ('run','source_pid','native_thread_id')} for number,saved in selected.items()
            if number not in observed)]
    require(len(rows)<=HandlerLedger.maximum_records,'source_registry_handler_population_unknown')
    for row in rows:
        context.check()
        require(type(row) is dict and _number(row.get('id')) and 0<row['id']
            and (not terminal or row['id']<=ledger['accepted'])
            and row['id'] not in seen and row.get('state') in
            ('ACTIVE','RECOVERABLE','FAILED','INTERRUPTED'),'source_registry_handler_identity')
        seen.add(row['id']);stream=row.get('stream');session=sessions.get(stream)
        require(session is not None and row.get('session')==session['session']
            and row.get('transport')==session['transport'],'source_registry_handler_session')
        # Native accepts the whole subscription, while a parsed log may narrow
        # its callback to the single actual affected scope.
        scopes=session['scopes'];scope_hash=row.get('scope_hash');scope_count=row.get('scope_count')
        scope_binding='ORIGINAL_CALLBACK_SCOPE'
        if scope_count==0 and scope_hash==HandlerLedger.scope_hash(()) and row['state']!='RECOVERABLE':
            # A decode/ack failure can precede scope discovery. The registered
            # subscription bounds potential effects; it proves no actual effect.
            matched=scopes;scope_binding='REGISTERED_MAXIMUM_EFFECT_UNIVERSE'
        elif scope_count==1:
            matched=[scope for scope in scopes if HandlerLedger.scope_hash((scope,))==scope_hash]
            require(len(matched)==1,'source_registry_handler_scope')
        else:
            require(type(scope_count) is int and scope_count==len(scopes)
                and scope_hash==HandlerLedger.scope_hash(scopes),'source_registry_handler_scope')
            matched=scopes
        saved=selected.get(row['id'])
        if saved is not None:
            require(saved.get('source_pid')==ledger['pid'] and saved.get('native_thread_id')==ledger['native_thread_id']
                and {key:value for key,value in saved.items() if key not in
                    ('run','source_pid','native_thread_id')}==row,'source_registry_handler_changed')
        require(not terminal or saved is not None,'source_registry_terminal_handler_missing')
        slot=row.get('slot');recovery=row.get('recovery');verified=None
        if row['state']=='RECOVERABLE':
            require(_number(slot) and slot>0 and type(recovery) is dict,'source_registry_handler_recovery')
            if recovery.get('kind')=='CONTROL_REPLAY':
                expected=control_recovery(_health_from_db(db,CONTROL_RECOVERY_KEY,128*1024))
                require(set(recovery)=={'kind','lower_slot','upper_slot','coverage_after_id'},
                    'source_registry_handler_control')
                retained_control=control_recovery(canonical({key:value for key,value in recovery.items()
                    if key!='kind'}).decode())
                require(matched==[CONTROL] and all(_number(value) for value in retained_control.values())
                    and retained_control['lower_slot']<=slot<=retained_control['upper_slot'],
                    'source_registry_handler_control')
                # Actual later control commits can advance/clear the original
                # acquisition obligation. Keep the old immutable callback range
                # and current obligation separately for real canonical replay.
                verified=dict(**recovery,current_obligation=expected,canonical_revalidation_required=True)
            elif recovery.get('kind')=='CANDIDATE_GAPS':
                ids=recovery.get('gap_ids')
                require(set(recovery)=={'kind','gap_ids'} and type(ids) is list and 0<len(ids)<=48
                    and len(ids)==len(set(ids)) and all(_number(item) and item>0 for item in ids),
                    'source_registry_handler_gaps')
                gaps=[]
                for item in ids:
                    gap=db.execute('SELECT CASE WHEN octet_length(scope)<=256 THEN scope END,'
                        "CASE WHEN typeof(lo)='integer' THEN lo END,CASE WHEN typeof(hi)='integer' THEN hi END,"
                        'hi IS NULL FROM candidate_gaps WHERE id=?',(item,)).fetchone()
                    require(gap is not None and type(gap[0]) is str and gap[0] in matched
                        and _number(gap[1]) and 0<gap[1]<=slot
                        and (gap[3] or _number(gap[2]) and slot<=gap[2]),
                        'source_registry_handler_gap_changed')
                    gaps.append(dict(id=item,scope=gap[0],lower_slot=gap[1],upper_slot=gap[2]))
                require(set(item['scope'] for item in gaps)==set(matched),'source_registry_handler_gap_scope')
                verified=dict(kind='CANDIDATE_GAPS',gaps=gaps)
            else:require(False,'source_registry_handler_recovery_kind')
        result.append(dict(id=row['id'],stream=stream,session=session['session'],
            state=row['state'],slot=slot if _number(slot) and slot>0 else None,
            potential_scopes=matched,scope_binding=scope_binding,
            recovery=verified,original_callback_completion=False,
            state_after_replay='SEPARATE_AUTHENTICATED_RECOVERY_RECEIPT_REQUIRED'))
    require(set(selected)==seen,'source_registry_handler_population_changed')
    return result,0 if raw is None else len(raw.encode())


def derive_failed_generation_plan(read_context):
    """No opens, providers, historical rewrites, ACKs or completion flags."""
    from meme_machine.runtime.native_restore_context import require_read_context
    from .normal_source_boot import KEY,validate_current_generation,_authenticate_prior_provenance
    from .normal_boot import _source_inputs
    from meme_machine.solana_source_drain import _health_from_db,SOURCE_DRAIN_BYTES
    context=require_read_context(read_context);context.verify_boundary()
    with context.database(context.root/'shared/solana-evidence.sqlite') as db:
        before=_marker(db);raw=_health_from_db(db,KEY,SOURCE_DRAIN_BYTES)
        require(raw is not None,'source_registry_current_missing')
        current=validate_current_generation(raw);identity=current['identity'];census=current['census']
        require(identity['root']==str(context.root),'source_registry_root')
        source_inputs,historical=_source_inputs(db)
        require(identity['source_inputs']['source_drain']==source_inputs['source_drain'] and
            identity['unknown_historical_handlers']==historical['pending_handlers'],
            'source_registry_historical_boundary')
        _authenticate_prior_provenance(current)
        require(census['state'] in ('RUNNING','DRAINING','RECOVERY_REQUIRED'),
            'source_registry_failed_generation_required')
        row=db.execute('SELECT CASE WHEN octet_length(identity)<=? THEN identity END,'
            'CASE WHEN octet_length(identity_hash)<=64 THEN identity_hash END,'
            'CASE WHEN octet_length(provider_identity)<=64 THEN provider_identity END,'
            'CASE WHEN octet_length(body)<=? THEN body END,CASE WHEN octet_length(hash)<=64 THEN hash END '
            'FROM '+GENERATION_TABLE+
            ' WHERE id=?',(MAX_BODY,MAX_BODY,identity['generation'])).fetchone()
        require(row is not None and type(row[0]) is str and type(row[3]) is str and json.loads(row[0])==identity
            and row[1]==current['identity_sha256'] and row[2]==current['provider_identity'],
            'source_registry_producer_binding')
        generation=_validate_generation(_read(row[3],row[4]))
        # Reserve the original <=64 callbacks, <=48 gaps each and <=256B scope
        # columns before reading their fixed-size joins. This is an encoded
        # input budget, not a claim about Python container/RSS overhead.
        size=HANDLER_SCRATCH_BYTES+len(raw.encode())+len(row[0].encode())+len(row[3].encode())+192
        require(generation['generation']==identity['generation'] and
            generation['identity_sha256']==current['identity_sha256'],'source_registry_generation_binding')
        terminal=generation['terminal_sha256']
        require(terminal is None and census.get('terminal') is not True or
            terminal==hashlib.sha256(raw.encode()).hexdigest(),'source_registry_terminal_hash')
        obligations=[];count=0;planes=set();sessions={}
        # EOF, not a sampled/latest ring, authenticates population absence.
        for stream,group,body,checksum in db.execute('SELECT CASE WHEN octet_length(id)<=32 THEN id END,'
                'CASE WHEN octet_length(session)<=32 THEN session END,'
                'CASE WHEN octet_length(body)<=? THEN body END,'
                'CASE WHEN octet_length(hash)<=64 THEN hash END FROM '+SESSION_TABLE+
                ' WHERE generation=? ORDER BY id',(MAX_BODY,identity['generation'])):
            context.check();count+=1
            require(type(stream) is str and type(group) is str and type(body) is str,
                'source_registry_input_bound')
            size+=len(body.encode())+128
            require(count<=MAX_ROWS and size<=MAX_INPUT_BYTES,'source_registry_input_bound')
            session=_validate_session(_read(body,checksum));planes.add(session['plane'])
            require(session['generation']==identity['generation'] and session['stream']==stream
                and session['session']==group and session['identity_sha256']==current['identity_sha256'],
                'source_registry_session_binding')
            sessions[stream]=session
            upper=None;closure=session['closure']
            if closure is not None:
                observed=db.execute('SELECT CASE WHEN octet_length(kind)<=64 THEN kind END,'
                    'CASE WHEN octet_length(body)<=? THEN body END '
                    'FROM acquisition_observations WHERE id=?',
                    (SOURCE_DRAIN_BYTES,closure['observation_id'])).fetchone()
                require(observed is not None and type(observed[1]) is str
                    and len(observed[1].encode())<=SOURCE_DRAIN_BYTES
                    and observed[0]==closure['kind'] and hashlib.sha256(observed[1].encode()).hexdigest()==closure['sha256'],
                    'source_registry_closure_changed')
                size+=len(observed[1].encode())+len(observed[0].encode())
                require(size<=MAX_INPUT_BYTES,'source_registry_input_bound')
                receipt=json.loads(observed[1]);require(receipt.get('session')==session['session'],
                    'source_registry_closure_session')
                values=[receipt.get(key) for key in ('completed','oldest_slot','early_log_max_slot')]
                upper=max((value for value in values if type(value) is int and value>0),default=None)
                if upper is not None and upper<session['lower_slot']:upper=None
            obligations.append(dict(stream=stream,session=session['session'],plane=session['plane'],
                scopes=session['scopes'],lower_slot=session['lower_slot'],retained_upper_slot=upper,
                fresh_authenticated_upper_required=upper is None,
                historical_account_reconstruction_unproved=session['plane']=='scout',
                closure=deepcopy(closure),state='REPLAY_AND_ORIGINAL_DELIVERY_PROOF_REQUIRED'))
        require(count==generation['sessions'],'source_registry_population_changed')
        require(all(row['frames']==0 or plane in planes for plane,row in generation['planes'].items()),
            'source_registry_committed_plane_without_session')
        handlers,handler_bytes=_handlers(db,current,sessions,context)
        require(size+handler_bytes<=MAX_INPUT_BYTES,'source_registry_input_bound')
        by_stream={row['stream']:row for row in obligations}
        for handler in handlers:
            row=by_stream[handler['stream']]
            if handler['slot'] is not None:
                row['lower_slot']=min(row['lower_slot'],handler['slot'])
                row['retained_upper_slot']=max(row['retained_upper_slot'] or 0,handler['slot'])
            # Stopping a socket or seeing one failed slot never proves the last
            # possible accepted slot. A fresh genuine upper remains necessary.
        queues=census.get('queues');terminal_bound=census.get('terminal') is True
        if terminal_bound:
            require(type(queues) is dict and set(queues)==set(PLANES),'source_registry_queue_population')
            for plane,row in queues.items():
                require(type(row) is dict and set(row)=={'accepted','committed','pending'}
                    and all(_number(value) for value in row.values())
                    and row['accepted']-row['committed']==row['pending']
                    and row['committed']<=generation['planes'][plane]['frames']<=row['accepted'],
                    'source_registry_queue_accounting')
                require(row['accepted']==0 or plane in planes,'source_registry_queue_without_session')
        for row in obligations:
            row['fresh_authenticated_upper_required']=True
            row['quiescent_final_frontier_verified']=False
        require(before==_marker(db),'source_registry_plan_generation_changed')
        value=dict(schema='failed-native-source-plan-v1',generation=identity['generation'],
            identity_sha256=current['identity_sha256'],failed_raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            producer_identity_sha256=digest(identity),registry_sha256=digest(generation),
            sessions=obligations,handlers=handlers,original_failure_state=census['state'],
            terminal_census_retained=terminal_bound,
            queue_accounting='ORIGINAL_TERMINAL_COUNTS' if terminal_bound else 'UNKNOWN_CRASH_TAIL',
            handler_population='ORIGINAL_TERMINAL_CENSUS' if terminal_bound else 'UNKNOWN_CRASH_TAIL',
            original_unexpected_cancellation=census.get('unexpected_cancellation',False),
            original_unknown_historical_handlers=historical['pending_handlers'],
            initial_frontiers=generation['initial_frontiers'],retained_frontiers=generation.get('terminal_frontiers'),
            history_delivery_required=True,proof_publication_required=True,
            downstream_economic_witness_required=True,recovery_complete=False,
            historical_handler_disposition_verified=False,funding_authority=False,safe_for_normal=False)
    context.verify_boundary()
    return FailedGenerationPlan(context,value,before,_issuer=_ISSUER)
