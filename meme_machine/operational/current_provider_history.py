"""Read an existing same-path continuous book without opening a runtime writer.

The caller owns the genuine financial replay, source/configuration authentication,
fixed file/inode binding and exclusive writer fence. This helper does not prove
those premises or historical stock continuity. It never creates/reaps/adopts a
book, registers admission, changes readiness, or grants provider/funding work.
"""
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from .bounded_provider import Budget, USAGE_COUNTERS, resource_configuration
from .position_continuation import validate_continuous


def _require(condition, code):
    if not condition:raise ValueError('current_provider_book_'+code)


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
        allow_nan=False).encode()).hexdigest()


def current_provider_book(db, authoritative_state, *, profile, configured_path, expected_path):
    """Bounded observations on the original unprefixed, already selected book.

    ``current_book_verified`` concerns only the supplied current binding and
    original configuration/counter/clock shape. Open transports, failures,
    readiness and reservation facts are returned separately and never promoted
    into permission. In particular a fully consumed but OPEN receipt is OPEN.
    The original restore-cohort fingerprint is neither required nor replaced.
    """
    _require(type(db) is sqlite3.Connection and db.in_transaction
        and db.execute('PRAGMA query_only').fetchone()==(1,),'readonly_snapshot_required')
    target=Path(expected_path)
    _require(target.is_absolute() and '..' not in target.parts
        and target.parts[-2:]==('shared','provider-usage.continuous.sqlite'),'fixed_path')
    _require(type(configured_path) is str and configured_path==str(target),'configured_path')
    previous=authoritative_state.get('runtime_admission') if type(authoritative_state) is dict else None
    _require(type(previous) is dict and previous.get('provider_db')==str(target)
        and previous.get('continuous_provider_db')==str(target),'same_path_binding')
    owner=previous.get('run_id')
    _require(type(owner) is str and 0<len(owner.encode())<=4096,'previous_owner')
    validate_continuous(profile)
    count,maximum=db.execute('SELECT count(*),max(length(CAST(value AS BLOB))) FROM run').fetchone()
    _require(count<=512 and maximum is not None and maximum<=65536,'run_bound')
    count,size=db.execute("SELECT count(*),coalesce(sum(length(CAST(key AS BLOB))+"
        "length(CAST(value AS BLOB))),0) FROM run WHERE typeof(key)<>'text' OR instr(key,'.')=0").fetchone()
    _require(count<=512 and size<=256*1024,'namespace_bound')
    reader=object.__new__(Budget);reader.prefix=''
    usage=reader.read(db)
    _require(all(type(key) is str and type(value) is str for key,value in usage.items()),'run_shape')
    persisted=json.loads(usage['continuous_envelope']);validate_continuous(persisted)
    limits=json.loads(usage['limits'])
    _require(usage.get('operating_mode')=='CONTINUOUS' and persisted==profile
        and limits==profile['limits'] and all(usage[key]=='' for key in
            ('wall_seconds','modeled_spend_limit','reconnect_limit')),'profile')
    reader.continuous=True;reader.envelope=profile
    reader.configuration=resource_configuration(limits,None,None,None,continuous=True)
    _require(reader.verify_configuration(usage)=='','configuration')
    counters={}
    for key in (*USAGE_COUNTERS,'http_reserved','native_reserved'):
        value=usage[key]
        _require(value.isdecimal() and len(value)<=40,'counter_shape')
        number=int(value);_require(number<=2**128,'counter_bound');counters[key]=number
    _require(all(math.isfinite(float(usage[key])) and float(usage[key])>=0
        for key in ('started','started_wall')) and bool(usage.get('boot')),'clock')
    _require({row[1] for row in db.execute('PRAGMA table_info(usage_hours)')}
        ==set(USAGE_COUNTERS)|{'hour'},'usage_schema')
    # Continuous runtime pacing comes from the selected profile. The legacy
    # stored bootstrap pacing key is not an original continuous constructor
    # guard; its equality is an observation, never a new permission predicate.
    try:
        pacing=json.loads(usage['physical_http_start_intervals'])
        pacing_matches=pacing==dict(solana=profile['physical_http_start_interval_seconds'],
            robinhood=profile['robinhood_http_start_interval_seconds'])
    except (KeyError,ValueError,TypeError):pacing_matches=None
    _require(usage['new_risk_ready'] in ('true','false') and
        math.isfinite(float(usage['readiness_at'])) and float(usage['readiness_at'])>=0
        and math.isfinite(float(usage['backoff_until'])) and float(usage['backoff_until'])>=0,'control_shape')
    transports={}
    for table in ('streams','http_receipts'):
        total,invalid,opened=db.execute('SELECT count(*),coalesce(sum(CASE WHEN '
            "typeof(closed)<>'integer' OR closed NOT IN (0,1) OR typeof(remaining)<>'integer' "
            'OR remaining<0 OR (closed=1 AND remaining<>0) THEN 1 ELSE 0 END),0),'
            'coalesce(sum(CASE WHEN closed=0 THEN 1 ELSE 0 END),0) FROM '+table).fetchone()
        _require(invalid==0,'transport_shape')
        transports[table]=dict(rows=total,open_rows=opened)
    return dict(schema='current-provider-book-observation-v1',current_book_verified=True,
        scope='CALLER_AUTHENTICATED_CURRENT_SAME_PATH_BOOK_ONLY',
        ledger_namespace='ORIGINAL_UNPREFIXED_CONTINUOUS',profile_sha256=_digest(profile),
        ledger_snapshot_sha256=_digest(usage),counters=counters,transports=transports,
        stored_bootstrap_pacing_matches_profile=pacing_matches,
        backoff_until=float(usage['backoff_until']),
        ledger_funding_closed=usage['new_risk_ready']=='false',
        ledger_failure_recorded=bool(usage['reason']),
        readiness_owner_matches_previous_run=bool(usage['readiness_owner'])
            and usage['readiness_owner']==owner,
        historical_provider_lineage_verified=False,authoritative_writes=0,provider_requests=0)
