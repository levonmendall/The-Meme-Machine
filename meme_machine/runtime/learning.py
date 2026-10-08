"""Bounded derived learning facts. No provider, strategy or economic authority.

The native writer owns the connection/transaction. Facts commit before the
corresponding raw history is folded. Native active evidence and economic
anchors live outside these disposable analysis tables.
"""
import json
import zlib
from fractions import Fraction
from meme_machine.runtime.journal import canonical, digest

MAX_ROWS = 8192
MAX_BYTES = 64 * 1024 * 1024
MAX_FACT_BYTES = 256 * 1024
TAIL_MULTIPLES = (5, 10, 25, 50)
RAW_KEYS=frozenset(('raw','raw_payload','raw_transaction','transactions','blocks',
    'logs','instructions','account_data','snapshot','full_snapshot','reconstruction'))


def compact(value):
    """Strip named raw reconstruction bodies, preserving derived input facts."""
    if isinstance(value,dict):
        return {k:(v if k in ('feature_vector','features','qualification','vector','gates') else compact(v))
                for k,v in value.items() if k not in RAW_KEYS or
                k in ('blocks','transactions') and type(v) in (int,float)}
    if isinstance(value,(list,tuple)):return [compact(v) for v in value]
    return value


def install(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='learning_usage_update'").fetchone():
        return
    db.execute('''CREATE TABLE IF NOT EXISTS learning_facts_v1(
        id TEXT PRIMARY KEY, asset TEXT NOT NULL, regime TEXT NOT NULL,
        at REAL NOT NULL, priority INTEGER NOT NULL, bytes INTEGER NOT NULL,
        body BLOB NOT NULL, checksum TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS learning_eviction_v1 ON learning_facts_v1(priority,at,id)')
    db.execute('CREATE INDEX IF NOT EXISTS learning_asset_v1 ON learning_facts_v1(asset,at)')
    db.execute('''CREATE TABLE IF NOT EXISTS learning_rollup_v1(
        bucket TEXT PRIMARY KEY, records INTEGER NOT NULL, bytes INTEGER NOT NULL)''')
    db.execute('CREATE TABLE IF NOT EXISTS learning_usage_v1(id INTEGER PRIMARY KEY CHECK(id=1),records INTEGER NOT NULL,bytes INTEGER NOT NULL)')
    if not db.execute('SELECT 1 FROM learning_usage_v1 WHERE id=1').fetchone():
        db.execute('INSERT INTO learning_usage_v1 SELECT 1,COUNT(*),COALESCE(SUM(bytes),0) FROM learning_facts_v1')
    for action, change in (
            ('INSERT', 'records=records+1,bytes=bytes+NEW.bytes'),
            ('DELETE', 'records=records-1,bytes=bytes-OLD.bytes'),
            ('UPDATE', 'bytes=bytes+NEW.bytes-OLD.bytes')):
        db.execute('CREATE TRIGGER IF NOT EXISTS learning_usage_'+action.lower()+
                   ' AFTER '+action+' ON learning_facts_v1 BEGIN UPDATE learning_usage_v1 SET '+change+' WHERE id=1; END')


def tail(maximum_multiple):
    """Observed underlying price multiple, never a claim of portfolio return."""
    multiple = None if maximum_multiple is None else Fraction(str(maximum_multiple))
    return {str(n)+'x': None if multiple is None else multiple >= n for n in TAIL_MULTIPLES}


def save(db, identity, asset, regime, at, facts, *, priority=1,
         max_rows=MAX_ROWS, max_bytes=MAX_BYTES):
    if not db.in_transaction:
        raise ValueError('learning_transaction_required')
    if max_rows < 1 or max_bytes < 1:
        raise ValueError('learning_retention_bound')
    install(db)
    value = dict(schema='compact-learning-v1', asset=str(asset), regime=str(regime),
                 observed_at=at, facts=compact(facts), qualification_authority=False,
                 economic_authority=False)
    encoded = canonical(value).encode()
    if len(encoded) > MAX_FACT_BYTES:
        # Compaction must preserve the source if complete facts cannot fit.
        raise ValueError('learning_fact_bound')
    body = zlib.compress(encoded, 6)
    if len(body) > max_bytes:
        raise ValueError('learning_store_fact_bound')
    checksum = digest(value)
    old = db.execute('SELECT checksum,priority FROM learning_facts_v1 WHERE id=?', (identity,)).fetchone()
    if old and old[0] == checksum:
        return False
    db.execute('''INSERT INTO learning_facts_v1 VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET asset=excluded.asset,regime=excluded.regime,
        at=excluded.at,priority=excluded.priority,bytes=excluded.bytes,body=excluded.body,checksum=excluded.checksum''',
               (identity, str(asset), str(regime), at, max(priority, old[1] if old else 0),
                len(body), body, checksum))
    count, size = db.execute('SELECT records,bytes FROM learning_usage_v1 WHERE id=1').fetchone()
    while count > max_rows or size > max_bytes:
        rows = db.execute('SELECT id,priority,bytes FROM learning_facts_v1 ORDER BY priority,at,id LIMIT 128').fetchall()
        for key, importance, length in rows:
            if count <= max_rows and size <= max_bytes:
                break
            # Four fixed statistical buckets; asset IDs cannot grow this table.
            bucket = str(min(3, max(0, importance)))
            db.execute('''INSERT INTO learning_rollup_v1 VALUES(?,1,?)
                ON CONFLICT(bucket) DO UPDATE SET records=records+1,bytes=bytes+excluded.bytes''', (bucket, length))
            db.execute('DELETE FROM learning_facts_v1 WHERE id=?', (key,))
            count -= 1; size -= length
    return True


def get(db, identity):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='learning_facts_v1'").fetchone():
        return None
    row = db.execute('SELECT body,checksum FROM learning_facts_v1 WHERE id=?', (identity,)).fetchone()
    if row is None:
        return None
    raw = zlib.decompress(row[0])
    if len(raw) > MAX_FACT_BYTES:
        raise ValueError('learning_fact_bound')
    value = json.loads(raw)
    if digest(value) != row[1]:
        raise ValueError('learning_fact_corruption')
    return value


def opportunity(db, event_id, kind, asset, at, body):
    """Keep receipt inputs, progression and outcomes after the raw ring retires."""
    if kind not in ('receipt', 'outcome', 'link'):
        return
    install(db)
    regime = body.get('regime', 'current')
    priority = 1
    facts = dict(body)
    if kind == 'receipt':
        priority = 0 if body.get('rejection_reasons') else 1
    elif kind == 'outcome':
        bps = body.get('maximum_favorable_excursion_bps')
        multiple = None if bps is None else Fraction(bps, 10000) + 1
        facts['underlying_winner_multiple'] = None if multiple is None else str(multiple)
        facts['right_tail'] = tail(multiple)
        reference = body.get('reference_price')
        observed_maximum = body.get('observed_maximum_price')
        observed_multiple = (None if reference is None or observed_maximum is None
                             else Fraction(str(observed_maximum))/Fraction(str(reference)))
        facts['observed_winner_multiple_lower_bound'] = None if observed_multiple is None else str(observed_multiple)
        facts['observed_right_tail'] = tail(observed_multiple)
        priority = 3 if multiple is not None and multiple >= 5 else 1
        if observed_multiple is not None and observed_multiple >= 5:
            priority = 3
        if priority == 3:
            receipt = get(db, body['receipt_id'])
            if receipt is not None:
                # Preserve the rejection features beside the later winner.
                facts['evaluated_opportunity'] = receipt['facts']
                db.execute('UPDATE learning_facts_v1 SET priority=3 WHERE id=?', (body['receipt_id'],))
    save(db, event_id, asset, regime, at, facts, priority=priority)


MATERIAL_STAGES = frozenset(('economic_vector','evaluated','rejected','qualified',
    'entry_reserved','entry_filled','entry_cancelled','deployed','unwind','settled',
    'terminal','trigger_terminal'))


def pipeline(db, row):
    seq, lane, policy, candidate, stage, reason, classification, at, _, details = row
    if stage not in MATERIAL_STAGES:
        return
    facts = dict(strategy_policy_version=policy, stage=stage, rejection_reason=reason,
                 classification=classification, inputs_and_outcome=json.loads(details))
    save(db, 'pipeline:'+str(seq), candidate, lane, at, facts,
         priority=0 if stage=='rejected' else 1)


def pipeline_install(db):
    install(db)
    db.execute('CREATE TABLE IF NOT EXISTS learning_pipeline_v1(id INTEGER PRIMARY KEY CHECK(id=1))')
    if not db.execute('SELECT 1 FROM learning_pipeline_v1').fetchone():
        for row in db.execute('SELECT * FROM progress ORDER BY sequence').fetchall():
            pipeline(db, row)
        db.execute('INSERT INTO learning_pipeline_v1 VALUES(1)')


def survivor(db, row, points=()):
    install(db)
    key='survivor:'+row['id']
    old=get(db,key)
    facts={} if old is None else old['facts']
    for at,price in points:
        bar=price if isinstance(price,dict) else dict(price=str(price),low=str(price),high=str(price))
        last=Fraction(str(bar['price']));low=Fraction(str(bar.get('low',last)));high=Fraction(str(bar.get('high',last)))
        if not 0<low<=last<=high:raise ValueError('learning_price_invalid')
        if 'reference_price' not in facts:
            facts.update(reference_price=str(last),first_observation_at=at,
                         minimum_price=str(low),maximum_price=str(high))
        facts['minimum_price']=str(min(Fraction(facts['minimum_price']),low))
        facts['maximum_price']=str(max(Fraction(facts['maximum_price']),high))
        if at>=facts.get('last_observation_at',at):
            facts.update(last_price=str(last),last_observation_at=at)
    facts['candidate_state']=row
    facts['outcome_observability']='OBSERVED_PRICE_LOWER_BOUND'
    multiple=None if 'reference_price' not in facts else Fraction(facts['maximum_price'])/Fraction(facts['reference_price'])
    material = row.get('state') in ('qualified','rejected','filled','settled','closed') or any(
        row.get(key) for key in ('features','feature_vector','qualification','decision',
                                'rejection','rejection_reasons','last_decision','reason'))
    if multiple is None and not material:
        # An identity and observation timestamp without prices, a material
        # evaluation or an economic outcome cannot answer a learning question.
        # Its authoritative graduation/retirement fence remains in native state.
        return
    facts['underlying_winner_multiple_lower_bound']=None if multiple is None else str(multiple)
    facts['right_tail']=tail(multiple)
    if multiple is not None:
        facts['maximum_favorable_excursion_bps']=str((multiple-1)*10000)
        facts['maximum_adverse_excursion_bps']=str((Fraction(facts['minimum_price'])/Fraction(facts['reference_price'])-1)*10000)
        facts['holding_observation_seconds']=facts['last_observation_at']-facts['first_observation_at']
    policy=db.execute("SELECT body FROM meta WHERE key='policy'").fetchone()
    facts['strategy_policy_version']=None if policy is None else json.loads(policy[0])
    save(db,key,row['id'],'survivor',row.get('through',row.get('last_checked',0)),facts,
         priority=3 if multiple is not None and multiple>=5 else 1)


def lifecycle(db, identity, regime, at, position, events=()):
    """Terminal facts and exact action summaries, not full market payloads."""
    install(db)
    prior=get(db,'lifecycle:'+identity)
    actions={} if prior is None else {digest(e):e for e in prior['facts'].get('economic_actions',[])}
    marks={} if prior is None else dict(prior['facts'].get('mark_extrema',{}))
    for event in events:
        action = event.get('action', event.get('kind',event.get('event')))
        if action in ('mark','monitor','marked'):
            source=event.get('position') or event
            for key in ('price','entry_price','executable_value','executable_quote','mark_value','mark','net_pnl','peak_quote_value'):
                value=source.get(key)
                if type(value) not in (int,float,str):continue
                try:number=Fraction(str(value))
                except (ValueError,ZeroDivisionError):continue
                old=marks.get(key)
                marks[key]=dict(minimum=str(number if old is None else min(number,Fraction(old['minimum']))),
                    maximum=str(number if old is None else max(number,Fraction(old['maximum']))),last=str(number))
        elif action is not None and action not in ('unresolved','health','observation'):
            # Native economic action fields are already compact; exclude raw
            # provider/evidence bodies, preserving decision vectors and prices.
            value={k:v for k,v in event.items() if k not in ('evidence','raw','transactions','blocks')}
            evidence=event.get('evidence') or {}
            value['decision_and_execution_facts']={k:evidence[k] for k in
                ('qualification','features','decision','execution_capacity','cost','reason','request') if k in evidence}
            actions[digest(value)]=value
    facts = dict(native_lifecycle_id=identity, terminal_position=position,
                 economic_actions=list(actions.values()),mark_extrema=marks,
                 outcome_observability='NATIVE_PERSISTED_FACTS')
    save(db, 'lifecycle:'+identity, position.get('candidate', position.get('market', identity)),
         regime, at, facts, priority=2)
