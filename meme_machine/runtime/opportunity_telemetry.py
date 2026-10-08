"""Read-only opportunity receipts and outcome evidence; no trading authority.

Only decision-path facts supplied by callers are captured. Missing evidence stays
unknown; this module never obtains a provider quote or changes a qualification.
"""
from fractions import Fraction
import json
from meme_machine.runtime.journal import canonical,digest

SCHEMA='directional-opportunity-telemetry-v1'
WINDOWS=(300,900,3600,21600,86400)
MAX_RECEIPT_BYTES=65536
MAX_JOURNAL_ROWS=4096
MAX_OUTCOME_TARGETS=1024
MAX_RETIRE_SLICE=512

def _prefix(db):
    row=db.execute("SELECT value FROM opportunity_meta_v1 WHERE key='journal_prefix'").fetchone()
    if row is None:return dict(events=0,receipts=0,outcomes=0,final_hash='0'*64,maximum_at=None)
    value=json.loads(row[0]);checksum=value.pop('checksum')
    if checksum!=digest(value):raise ValueError('opportunity_prefix_corruption')
    return value

def retain(db):
    """Fold observations only; callers own the transaction and native lock.

    Compact learning facts survive separately. The prefix preserves raw-ring
    chain identity. An outcome overlapping missing observations stays incomplete.
    """
    if not db.in_transaction:raise ValueError('opportunity_retention_transaction')
    excess=db.execute('SELECT COUNT(*) FROM opportunity_journal_v1').fetchone()[0]-MAX_JOURNAL_ROWS
    if excess>0:
        value=_prefix(db)
        for seq,event_id,kind,asset,at,body,previous,checksum in db.execute(
                'SELECT * FROM opportunity_journal_v1 ORDER BY seq LIMIT ?',(min(excess,MAX_RETIRE_SLICE),)):
            if seq!=value['events']+1 or previous!=value['final_hash'] or checksum!=digest([seq,event_id,kind,asset,at,body,previous]):
                raise ValueError('opportunity_journal_corruption')
            from meme_machine.runtime.learning import opportunity
            opportunity(db,event_id,kind,asset,at,json.loads(body))
            value['events']=seq;value['final_hash']=checksum
            value['receipts']+=kind=='receipt';value['outcomes']+=kind=='outcome'
            value['maximum_at']=at if value['maximum_at'] is None else max(value['maximum_at'],at)
        value['checksum']=digest(value)
        db.execute("INSERT OR REPLACE INTO opportunity_meta_v1 VALUES('journal_prefix',?)",(canonical(value),))
        name='opportunity_journal_no_delete'
        sql=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()[0]
        db.execute('DROP TRIGGER '+name)
        db.execute('DELETE FROM opportunity_journal_v1 WHERE seq<=?',(value['events'],))
        db.execute(sql)
    # Unfinished diagnostic scans cannot accumulate without limit. Their loss
    # is recorded; it grants no strategy/lifecycle permission or outcome claim.
    excess=db.execute('SELECT COUNT(*) FROM opportunity_targets_v1').fetchone()[0]-MAX_OUTCOME_TARGETS
    if excess>0:
        retired=min(excess,MAX_RETIRE_SLICE)
        db.execute('DELETE FROM opportunity_targets_v1 WHERE id IN (SELECT id FROM opportunity_targets_v1 ORDER BY at,id LIMIT ?)',(retired,))
        old=db.execute("SELECT value FROM opportunity_meta_v1 WHERE key='unobserved_retired_targets'").fetchone()
        db.execute("INSERT OR REPLACE INTO opportunity_meta_v1 VALUES('unobserved_retired_targets',?)",(str((int(old[0]) if old else 0)+retired),))
    db.execute("""DELETE FROM opportunity_scans_v1 WHERE id IN (
        SELECT s.id FROM opportunity_scans_v1 s WHERE
        (substr(s.id,1,7)='export:' AND NOT EXISTS(SELECT 1 FROM opportunity_targets_v1 t WHERE t.asset=substr(s.id,8))) OR
        (substr(s.id,1,7)!='export:' AND NOT EXISTS(SELECT 1 FROM opportunity_targets_v1 t WHERE t.id=json_extract(s.id,'$[0]')))
        LIMIT ?)""",(MAX_RETIRE_SLICE,))

def value_at(value,path):
    for part in path.split('.'):
        if not isinstance(value,dict):return None
        value=value.get(part)
    return value

def gate(name,observed,threshold,comparator,category,*,reason=None):
    passed=distance=normalized=None
    if observed is not None and threshold is not None:
        if comparator in ('>=','>','<=','<'):
            left,right=Fraction(str(observed)),Fraction(str(threshold))
            distance=left-right if comparator in ('>=','>') else right-left
            passed={'<':left<right,'<=':left<=right,'>':left>right,'>=':left>=right}[comparator]
            normalized=distance/max(abs(right),1)
        elif comparator=='==':
            passed=observed==threshold;distance=Fraction(1 if passed else -1)
            normalized=distance
        else:raise ValueError('opportunity_gate_comparator')
    return dict(name=name,observed=observed,threshold=threshold,comparator=comparator,
        signed_distance=None if distance is None else str(distance),
        normalized_signed_distance=None if normalized is None else str(normalized),
        category=category,passed=passed,reason=reason)

def measurable_gates(lane,decision):
    vector=decision.get('vector') or {};context=decision.get('context') or {}
    gates=[]
    def add(name,path,threshold,op,category,reason,*,source=None):
        gates.append(gate(name,value_at(vector if source is None else source,path),threshold,op,category,reason=reason))
    if lane=='pons':
        thresholds=vector.get('thresholds') or {}
        rows=(
            ('curve_progress_min','progress_bps','min_curve_progress_bps','>=','alpha','curve_progress'),
            ('curve_progress_max','progress_bps','max_curve_progress_bps','<=','alpha','curve_progress'),
            ('token_age_min','token_age_seconds','min_token_age_seconds','>=','alpha','token_age'),
            ('token_age_max','token_age_seconds','max_token_age_seconds','<=','alpha','token_age'),
            ('state_freshness','decision_state_age_seconds','max_state_age_seconds','<=','evidence','stale_state_after_evidence'),
            ('curve_velocity','trajectory.progress_15s_bps','min_progress_15s_bps','>=','alpha','curve_velocity'),
            ('curve_acceleration','trajectory.accelerating','require_curve_acceleration','==','alpha','curve_deceleration'),
            ('eta_min','trajectory.graduation_eta_seconds','min_graduation_eta_seconds','>=','alpha','graduation_eta'),
            ('eta_max','trajectory.graduation_eta_seconds','max_graduation_eta_seconds','<=','alpha','graduation_eta'),
            ('independent_breadth','demand.independent_groups','min_independent_groups','>=','alpha','independent_breadth'),
            ('buyer_growth','demand.new_independent_groups_15s','min_new_independent_groups_15s','>=','alpha','buyer_growth'),
            ('buy_sell_flow','demand.buy_sell_ratio_bps','min_buy_sell_ratio_bps','>=','alpha','buy_sell_flow'),
            ('flow_acceleration','demand.net_flow_accelerating','require_flow_acceleration','==','alpha','flow_deceleration'),
            ('largest_buyer','demand.largest_buyer_flow_bps','max_largest_buyer_flow_bps','<=','hard_safety','largest_buyer_concentration'),
            ('top3_buyer','demand.top3_buyer_flow_bps','max_top3_buyer_flow_bps','<=','hard_safety','top3_buyer_concentration'),
            ('roundtrip_loss','roundtrip_loss_bps','max_roundtrip_loss_bps','<=','execution','roundtrip_cost'),
            ('stress_loss','proposed_size.execution_capacity.double_loss_bps','max_roundtrip_loss_bps','<=','execution','position_size_zero'),
        )
        for name,path,key,op,category,reason in rows:add(name,path,thresholds.get(key),op,category,reason)
        add('state_freshness_lower','decision_state_age_seconds',0,'>=','evidence','stale_state_after_evidence')
        add('trajectory_complete','trajectory.complete',True,'==','evidence','trajectory_history')
        add('net_demand','demand.current_net_quote',0,'>','alpha','net_demand_nonpositive')
        add('creator_distribution','demand.creator_sell_quote_15s',0,'==','hard_safety','creator_distribution')
        add('snipe_tax','current_snipe_bps',0,'==','hard_safety','snipe_tax_nonzero')
        add('native_quote','pair_token','0x'+'0'*40,'==','hard_safety','non_native_quote_allocation_disabled')
        add('position_size','proposed_size.amount_quote',0,'>','execution','position_size_zero')
        add('graduated','state.graduated',False,'==','hard_safety','already_graduated',source=context)
        add('creator_tax','state.creator_tax_bps',thresholds.get('max_creator_tax_bps'),'<=','hard_safety','creator_tax',source=context)
        if vector.get('creator_history') is not None:
            add('creator_history','creator_history.adverse',False,'==','hard_safety','creator_adverse_history')
    elif lane=='pump':
        policy=decision.get('policy') or {}
        phase=vector.get('phase')
        rows=[
            ('net_demand','net_buy_share_bps','min_net_buy_share_bps','>=','alpha','net_demand'),
        ]
        if phase=='late_curve_acceleration':
            rows+= [
                ('curve_progress_min','curve_progress_bps','min_curve_progress_bps','>=','alpha','curve_not_late'),
                ('curve_progress_max','curve_progress_bps','max_curve_progress_bps','<=','alpha','curve_too_late'),
                ('velocity','curve_velocity_bps_per_s','min_curve_velocity_bps_per_s','>=','alpha','curve_velocity'),
                ('acceleration','curve_acceleration_bps_per_s2','min_curve_acceleration_bps_per_s2','>=','alpha','curve_deceleration'),
                ('breadth','independent_buyer_clusters','min_independent_clusters','>=','alpha','independent_buyers'),
                ('growth','buyer_growth','min_buyer_growth','>=','alpha','buyer_growth'),
                ('repeat_buyers','repeat_buyer_clusters','min_repeat_buyer_clusters','>=','alpha','repeat_buyers'),
                ('repeat_share','repeat_buy_share_bps','min_repeat_buy_share_bps','>=','alpha','repeat_buy_share'),
                ('concentration','concentration_bps','max_concentration_bps','<=','hard_safety','concentration'),
                ('extension','extension_bps','max_extension_bps','<=','alpha','extension'),
                ('execution_loss','immediate_roundtrip_loss_bps','max_immediate_roundtrip_loss_bps','<=','execution','executable_downside'),
            ]
        else:
            rows+= [
                ('breadth','independent_buyer_clusters','min_postgrad_independent_clusters','>=','alpha','independent_buyers'),
                ('concentration','concentration_bps','max_postgrad_concentration_bps','<=','hard_safety','concentration'),
                ('distribution','early_holder_sell_share_bps','max_early_holder_sell_share_bps','<=','hard_safety','early_holder_distribution'),
            ]
            add('graduated','graduated',True,'==','hard_safety','not_graduated')
            if phase=='post_graduation_momentum':
                rows+= [
                    ('age_min','seconds_since_graduation','min_postgrad_age_s','>=','alpha','postgrad_age'),
                    ('age_max','seconds_since_graduation','max_postgrad_entry_age_s','<=','alpha','postgrad_age'),
                    ('growth','buyer_growth','min_postgrad_buyer_growth','>=','alpha','buyer_growth'),
                    ('volume_acceleration','volume_acceleration_bps','min_postgrad_volume_acceleration_bps','>=','alpha','volume_acceleration'),
                ]
                if policy.get('postgrad_price_retention_hard_gate'):
                    rows.append(('price_retention','price_vs_graduation_bps','min_postgrad_price_vs_graduation_bps','>=','alpha','price_retention'))
            elif phase=='pumpswap_second_leg':
                rows+= [
                    ('age','seconds_since_graduation','min_second_leg_age_s','>=','alpha','second_leg_age'),
                    ('consolidation','consolidation_seconds','min_consolidation_s','>=','alpha','consolidation'),
                    ('pullback_min','pullback_depth_bps','min_pullback_depth_bps','>=','alpha','pullback_shape'),
                    ('pullback_max','pullback_depth_bps','max_pullback_depth_bps','<=','alpha','pullback_shape'),
                    ('breakout','breakout_bps','min_breakout_bps','>=','alpha','breakout'),
                    ('growth','buyer_growth','min_second_leg_buyer_growth','>=','alpha','buyer_growth'),
                ]
        for name,path,key,op,category,reason in rows:add(name,path,policy.get(key),op,category,reason)
        add('point_in_time','point_in_time',True,'==','evidence','non_point_in_time_signal')
        add('future_data_used','future_data_used',False,'==','evidence','non_point_in_time_signal')
        add('native_quote','quote_asset','SOL','==','hard_safety','unsupported_quote_asset')
    else:raise ValueError('opportunity_family')
    # These are observations of checks already performed by the decision path.
    # An absent check is unknown, never an assumed pass or an invitation to fetch.
    for category,key in (('hard_safety','lineage_verified'),('evidence','evidence_complete'),
                         ('execution','execution_stress_verified')):
        add(key,key,True,'==',category,key,source=context)
    if context.get('generation_applicable'):
        add('generation_fence','generation_verified',True,'==','evidence','generation_fence',source=context)
    if lane=='pump' and context.get('concentration_measured') is not True:
        gates=[gate(g['name'],None,g['threshold'],g['comparator'],g['category'],reason=g['reason'])
            if g['name']=='concentration' else g for g in gates]
    return gates

def current_receipt(identity,asset,decision_id,status,at,decision):
    vector=decision.get('vector') or {};qualification=decision.get('qualification') or {}
    context=decision.get('context') or {}
    reasons=list(qualification.get('reasons',vector.get('all_rejections',[])))
    if not reasons and decision.get('reason'):reasons=[decision['reason']]
    gates=measurable_gates(identity['lane'],decision)
    known={g['reason'] for g in gates}
    unknown=[r for r in reasons if r not in known]
    aggregates={category:bool([g for g in gates if g['category']==category]) and
        all(g['passed'] is True for g in gates if g['category']==category)
        for category in ('hard_safety','evidence','execution','alpha')}
    failed_alpha=[g for g in gates if g['category']=='alpha' and g['passed'] is False]
    failed_alpha.sort(key=lambda g:(abs(Fraction(g['normalized_signed_distance'])),g['name']))
    marginal=bool(reasons and failed_alpha and not unknown and
        all(aggregates[c] for c in ('hard_safety','evidence','execution')))
    body=dict(schema=SCHEMA,family=identity['lane'],asset_id=asset.removeprefix(identity['lane']+':'),
        opportunity_id=asset,current_decision_id=decision_id,
        native_lifecycle_identity=decision.get('native_identity'),
        current_strategy=qualification.get('strategy_id',vector.get('policy')),
        policy_hash=qualification.get('policy_hash',vector.get('policy_hash')),
        policy_epoch=identity['cohort'],decision_timestamp=int(at),status=status,
        source_cursor=context.get('source_cursor'),freshness_generation=context.get('freshness_generation'),
        rejection_reasons=reasons,gates=gates,aggregate_pass=aggregates,
        unclassified_rejections=unknown,marginal_alpha_reject=marginal,
        ranked_failed_alpha_gates=[g['name'] for g in failed_alpha],
        existing_executable_quote=decision.get('executable_quote'),
        existing_execution_capacity=value_at(vector,'proposed_size.execution_capacity'),
        feature_vector=vector,
        reference_price=context.get('reference_price'),decision_hash=digest(decision),
        qualification_authority=False,order_authority=False)
    if len(canonical(body).encode())>MAX_RECEIPT_BYTES:raise ValueError('opportunity_receipt_bound')
    return body

def append(db,event_id,kind,asset,at,body):
    encoded=canonical(body)
    if len(encoded.encode())>MAX_RECEIPT_BYTES:raise ValueError('opportunity_receipt_bound')
    old=db.execute('SELECT kind,asset,at,body FROM opportunity_journal_v1 WHERE id=?',(event_id,)).fetchone()
    if old:
        if old!=(kind,asset,int(at),encoded):raise ValueError('opportunity_journal_conflict')
        return False
    from meme_machine.runtime.learning import opportunity
    opportunity(db,event_id,kind,asset,int(at),body)
    last=db.execute('SELECT seq,hash FROM opportunity_journal_v1 ORDER BY seq DESC LIMIT 1').fetchone()
    seq,previous=(last[0]+1,last[1]) if last else (1,'0'*64)
    checksum=digest([seq,event_id,kind,asset,int(at),encoded,previous])
    db.execute('INSERT INTO opportunity_journal_v1 VALUES(?,?,?,?,?,?,?,?)',
        (seq,event_id,kind,asset,int(at),encoded,previous,checksum))
    retain(db)
    return True

def install(db,identity):
    """Caller owns one transaction: additive DDL and legacy transfer are atomic."""
    db.execute('CREATE TABLE IF NOT EXISTS opportunity_journal_v1(seq INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,asset TEXT NOT NULL,at INTEGER NOT NULL,body TEXT NOT NULL,previous TEXT NOT NULL,hash TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS opportunity_journal_asset ON opportunity_journal_v1(asset,kind,at)')
    db.execute('CREATE INDEX IF NOT EXISTS opportunity_journal_scan ON opportunity_journal_v1(asset,at,seq)')
    db.execute('CREATE TABLE IF NOT EXISTS opportunity_targets_v1(id TEXT PRIMARY KEY,asset TEXT NOT NULL,at INTEGER NOT NULL,reference TEXT,next_window INTEGER NOT NULL,next_at INTEGER NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS opportunity_due ON opportunity_targets_v1(next_at,id)')
    db.execute('CREATE TABLE IF NOT EXISTS opportunity_scans_v1(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS opportunity_meta_v1(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    from meme_machine.runtime.learning import install as install_learning, opportunity
    install_learning(db)
    if not db.execute("SELECT 1 FROM opportunity_meta_v1 WHERE key='learning_backfilled'").fetchone():
        for event_id,kind,asset,at,body in db.execute('SELECT id,kind,asset,at,body FROM opportunity_journal_v1 WHERE kind!=\'price\' ORDER BY seq').fetchall():
            opportunity(db,event_id,kind,asset,at,json.loads(body))
        db.execute("INSERT INTO opportunity_meta_v1 VALUES('learning_backfilled','1')")
    for action in ('UPDATE','DELETE'):
        name='opportunity_journal_no_'+action.lower()
        sql="CREATE TRIGGER "+name+" BEFORE "+action+" ON opportunity_journal_v1 BEGIN SELECT RAISE(ABORT,'append_only_opportunity'); END"
        prior=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(name,)).fetchone()
        if prior:
            if prior[0]!=sql:raise ValueError('opportunity_trigger_drift')
        else:db.execute(sql)
    ready=db.execute("SELECT value FROM opportunity_meta_v1 WHERE key='schema'").fetchone()
    if ready:
        if ready[0]!=SCHEMA:raise ValueError('opportunity_schema_drift')
        retain(db)
        return
    for event_id,asset,at,raw in db.execute('SELECT id,asset,at,body FROM opportunity_receipts ORDER BY at,id').fetchall():
        row=json.loads(raw)
        record(db,identity,event_id,asset,row['identity'],row['regime'],row['status'],at,row.get('decision'))
    for asset,raw in db.execute('SELECT asset,body FROM opportunity_links ORDER BY asset').fetchall():
        link=json.loads(raw)
        for regime in ('current','survivor'):
            row=link.get(regime) or {}
            if row.get('identity') is not None:
                record(db,identity,'legacy-link:'+digest([asset,regime,row]),asset,row['identity'],
                    regime,row['status'],row['at'],None,outcome=row.get('outcome'))
    db.execute("INSERT INTO opportunity_meta_v1 VALUES('schema',?)",(SCHEMA,))

def record(db,identity,event_id,asset,native_id,regime,status,at,decision,*,outcome=None):
    link=dict(schema=SCHEMA,family=identity['lane'],asset_id=asset,regime=regime,
        native_id=native_id,status=status,at=int(at),outcome=outcome,qualification_authority=False,order_authority=False)
    append(db,'link:'+event_id,'link',asset,at,link)
    if regime!='current' or decision is None:return
    body=current_receipt(identity,asset,native_id,status,at,decision)
    added=append(db,'receipt:'+event_id,'receipt',asset,at,body)
    context=decision.get('context') or {}
    if body['reference_price'] is not None and context.get('lineage_verified') is True and context.get('evidence_complete') is True:
        price=str(Fraction(str(body['reference_price'])))
        proof=digest([asset,identity['cohort'],at,context.get('source_cursor'),price])
        append(db,'decision-price:'+event_id,'price',asset,at,
            dict(schema=SCHEMA,price=price,low=price,high=price,source_hash=proof,
                qualification_authority=False,order_authority=False))
    vector=decision.get('vector') or {};q=decision.get('qualification') or {}
    rejected=bool(body['rejection_reasons'] or status in ('rejected','cancelled','timeout','no_fill') or
        q.get('qualified') is False or vector.get('current_threshold_pass') is False)
    if added and rejected:
        reference=body['reference_price']
        if reference is not None and Fraction(str(reference))<=0:raise ValueError('opportunity_reference_price')
        db.execute('INSERT INTO opportunity_targets_v1 VALUES(?,?,?,?,?,?)',
            ('receipt:'+event_id,asset,int(at),None if reference is None else str(reference),0,int(at)+WINDOWS[0]))
        retain(db)

def verify(db):
    prefix=_prefix(db)
    previous=prefix['final_hash'];count=prefix['events'];receipts=prefix['receipts'];outcomes=prefix['outcomes']
    for seq,event_id,kind,asset,at,body,prior,checksum in db.execute('SELECT * FROM opportunity_journal_v1 ORDER BY seq'):
        if seq!=count+1 or prior!=previous or checksum!=digest([seq,event_id,kind,asset,at,body,prior]):
            raise ValueError('opportunity_journal_corruption')
        count+=1;previous=checksum;receipts+=kind=='receipt';outcomes+=kind=='outcome'
    return dict(verified=True,events=count,receipts=receipts,outcomes=outcomes,final_hash=previous)

def observe_prices(db,lane,asset,points,*,source_hash):
    if len(points)>512:raise ValueError('opportunity_price_batch_bound')
    for point in points:
        at=int(point['at']);price=Fraction(str(point['price']))
        low=Fraction(str(point.get('low',price)));high=Fraction(str(point.get('high',price)))
        if lane=='pons':price/=10**18;low/=10**18;high/=10**18
        if not 0<low<=price<=high:raise ValueError('opportunity_price_range')
        body=dict(schema=SCHEMA,price=str(price),low=str(low),high=str(high),
            source_hash=source_hash,qualification_authority=False,order_authority=False)
        append(db,'price:'+digest([lane,asset,at,body]),'price',asset,at,body)

def enrich(db,*,now,limit=8,event_budget=512,ready_assets=None):
    """Incremental persisted-evidence scan; no provider or economic side effects."""
    if not 1<=limit<=32 or not 1<=event_budget<=512:raise ValueError('opportunity_enrichment_batch')
    due=db.execute('SELECT id,asset,at,reference,next_window,next_at FROM opportunity_targets_v1 WHERE next_at<=? ORDER BY next_at,id LIMIT ?',(int(now),limit)).fetchall()
    completed=processed=0
    for target,asset,start,reference,index,end in due:
        if processed>=event_budget:break
        if ready_assets is not None and asset not in ready_assets:continue
        scan_id=canonical([target,index])
        old=db.execute('SELECT body FROM opportunity_scans_v1 WHERE id=?',(scan_id,)).fetchone()
        scan=json.loads(old[0]) if old else dict(cursor=0,cursor_at=start-1,source_watermark=db.execute('SELECT COALESCE(MAX(seq),0) FROM opportunity_journal_v1').fetchone()[0],maximum=None,minimum=None,last=None,
            last_at=None,observed=0,survivor_candidate=False,survivor_qualified=False,
            survivor_filled=False,survivor_terminal=None)
        prefix=_prefix(db)
        if prefix['maximum_at'] is not None and prefix['maximum_at']>=start:
            scan['retention_incomplete']=True
        allowance=min(64,event_budget-processed)
        rows=db.execute("SELECT seq,kind,at,body,id,previous,hash FROM opportunity_journal_v1 WHERE asset=? AND kind IN ('price','link') AND at BETWEEN ? AND ? AND (at,seq)>(?,?) AND seq<=? ORDER BY at,seq LIMIT ?",
            (asset,start,end,scan['cursor_at'],scan['cursor'],scan['source_watermark'],allowance)).fetchall()
        for seq,kind,at,encoded,event_id,previous,checksum in rows:
            if checksum!=digest([seq,event_id,kind,asset,at,encoded,previous]):
                raise ValueError('opportunity_journal_corruption')
            data=json.loads(encoded);scan['cursor']=seq;scan['cursor_at']=at;processed+=1
            if kind=='price':
                low=Fraction(data['low']);high=Fraction(data['high'])
                scan['maximum']=str(high if scan['maximum'] is None else max(Fraction(scan['maximum']),high))
                scan['minimum']=str(low if scan['minimum'] is None else min(Fraction(scan['minimum']),low))
                if scan['last_at'] is None or at>=scan['last_at']:
                    scan['last']=data['price'];scan['last_at']=at
                scan['observed']+=1
            elif data['regime']=='survivor':
                scan['survivor_candidate']=True
                scan['survivor_qualified']|=data['status']=='qualified'
                scan['survivor_filled']|=data['status']=='filled'
                if data['status'] in ('settled','cancelled') and data.get('outcome') is not None:scan['survivor_terminal']=data['outcome']
        if len(rows)==allowance:
            db.execute('INSERT OR REPLACE INTO opportunity_scans_v1 VALUES(?,?)',(scan_id,canonical(scan)))
            continue
        def outcome_return(value):
            return None if scan.get('retention_incomplete') or value is None or reference is None else int((Fraction(value)/Fraction(reference)-1)*10000)
        body=dict(schema=SCHEMA,receipt_id=target,window_seconds=WINDOWS[index],window_end=end,
            evaluated_at=int(now),source_journal_watermark=scan['source_watermark'],maximum_favorable_excursion_bps=outcome_return(scan['maximum']),
            maximum_adverse_excursion_bps=outcome_return(scan['minimum']),
            terminal_or_last_observable_return_bps=outcome_return(scan['last']),
            last_observation_at=scan['last_at'],observed_samples=scan['observed'],
            observed_maximum_price=scan['maximum'],observed_minimum_price=scan['minimum'],
            reference_price=reference,
            evidence_retention_complete=not scan.get('retention_incomplete',False),
            observability='RETAINED_EVIDENCE_INCOMPLETE' if scan.get('retention_incomplete') else 'OBSERVED' if scan['observed'] and reference is not None else
                ('REFERENCE_UNAVAILABLE' if reference is None else 'NO_PERSISTED_OBSERVATIONS'),
            survivor_candidate_created=None if scan.get('retention_incomplete') else scan['survivor_candidate'],
            survivor_qualified=None if scan.get('retention_incomplete') else scan['survivor_qualified'],
            survivor_fill_committed=None if scan.get('retention_incomplete') else scan['survivor_filled'],
            survivor_terminal_outcome=None if scan.get('retention_incomplete') else scan['survivor_terminal'],
            qualification_authority=False,order_authority=False)
        append(db,'outcome:'+target+':'+str(WINDOWS[index]),'outcome',asset,end,body)
        db.execute('DELETE FROM opportunity_scans_v1 WHERE id=?',(scan_id,))
        if index+1==len(WINDOWS):db.execute('DELETE FROM opportunity_targets_v1 WHERE id=?',(target,))
        else:db.execute('UPDATE opportunity_targets_v1 SET next_window=?,next_at=? WHERE id=?',
            (index+1,start+WINDOWS[index+1],target))
        completed+=1
    retain(db)
    return dict(completed_windows=completed,processed_events=processed)


def enrich_service(service,*,now):
    """Consume verified, persisted observations on the service's owner thread."""
    sleeve=getattr(service,'sleeve',None);history=getattr(service,'history',None)
    if sleeve is None or history is None or not sleeve.opportunity_ready:
        return dict(status='UNAVAILABLE',qualification_authority=False,order_authority=False)
    with sleeve.transaction():
        assets=sleeve.db.execute(
            'SELECT asset,MIN(at),MAX(next_at) FROM opportunity_targets_v1 WHERE next_at<=? GROUP BY asset ORDER BY MIN(next_at),asset LIMIT 8',
            (int(now),)).fetchall()
        ready=set();exported=0
        for asset,start,end in assets:
            candidate=asset.removeprefix(sleeve.identity['lane']+':')
            row=history.get(candidate)
            if row is None or row.get('state')=='retired':
                ready.add(asset);continue
            graduation=row['graduation']
            record(sleeve.db,sleeve.identity,'graduation:'+digest([asset,graduation]),asset,
                candidate,'survivor','graduated',graduation['at'],None)
            if not row.get('through') or row['through']<end:continue
            key='export:'+asset
            saved=sleeve.db.execute('SELECT body FROM opportunity_scans_v1 WHERE id=?',(key,)).fetchone()
            cursor=json.loads(saved[0]) if saved else dict(start=start,through=start-1)
            if start<cursor['start']:cursor=dict(start=start,through=start-1)
            points=history.db.execute(
                'SELECT at,price,hash FROM points WHERE candidate=? AND at>? AND at<=? ORDER BY at LIMIT 32',
                (candidate,cursor['through'],end)).fetchall()
            for at,encoded,checksum in points:
                if checksum!=digest([candidate,at,encoded]):raise ValueError('opportunity_source_corruption')
                observe_prices(sleeve.db,sleeve.identity['lane'],asset,
                    [dict(at=at,**json.loads(encoded))],source_hash=checksum)
                cursor['through']=at;exported+=1
            sleeve.db.execute('INSERT OR REPLACE INTO opportunity_scans_v1 VALUES(?,?)',(key,canonical(cursor)))
            if len(points)<32:ready.add(asset)
        result=enrich(sleeve.db,now=now,ready_assets=ready)
    return dict(result,status='OBSERVATION_ONLY',exported_prices=exported,
        qualification_authority=False,order_authority=False)


def pump_context(signal,snapshot,stage):
    """Capture existing snapshot provenance only; never hydrate extra evidence."""
    try:
        from meme_machine.lanes.pump import pump
        snapshot=snapshot or {}
        context=dict(source_cursor={k:snapshot[k] for k in
            ('slot','market_time','available_time','block_time','block_hash') if k in snapshot},
            freshness_generation=snapshot.get('generation'),
            lineage_verified=bool(snapshot.get('mint')==signal.mint and signal.point_in_time),
            evidence_complete=bool(stage=='full_point_in_time' and signal.point_in_time and not signal.future_data_used),
            concentration_measured=stage=='full_point_in_time')
        if snapshot.get('state'):
            reserve=snapshot['state'];price=Fraction(int(reserve['quote_reserve']),int(reserve['base_reserve']))
        else:
            curve=pump.curve(snapshot['accounts'][0]);price=Fraction(curve.sol,curve.token)
        if price>0:context['reference_price']=str(price)
        return context
    except Exception as error:
        return dict(capture_error='existing_context_unavailable:'+type(error).__name__,
            concentration_measured=stage=='full_point_in_time')

def pons_context(evaluation):
    """Candidate authentication has already completed before this observation."""
    try:
        from dataclasses import asdict,is_dataclass
        candidate=evaluation['candidate'];state=candidate['state']
        values=asdict(state) if is_dataclass(state) else dict(state)
        vector=evaluation['vector'];capacity=value_at(vector,'proposed_size.execution_capacity') or {}
        stamp=candidate.get('stamp')
        stamp=asdict(stamp) if is_dataclass(stamp) else stamp
        context=dict(state=values,source_cursor=dict(block=evaluation['source_block'],
            transaction=evaluation['source_transaction'],log_index=evaluation['source_log_index'],
            stamp=stamp),freshness_generation=(evaluation.get('evidence_context') or {}).get('generation'),
            lineage_verified=bool(candidate.get('auth') and candidate['token']==evaluation['token']),
            evidence_complete=vector.get('complete') is True,
            execution_stress_verified=capacity.get('double_loss_bps') is not None)
        price=Fraction(int(values['quote_reserve']),int(values['token_reserve']))
        if price>0:context['reference_price']=str(price)
        return context
    except Exception as error:
        return dict(capture_error='existing_context_unavailable:'+type(error).__name__)
