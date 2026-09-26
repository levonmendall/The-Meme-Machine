"""Lossless hot representation; no authority, field projection or archive reads.

Long native identities/addresses are dictionary indexed. Repeated authenticated
log arrays share one compressed content-addressed chunk. Public record hashes
and archived bodies still cover the original complete canonical JSON.
"""
import hashlib
import json
import zlib


def install(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS hot_chunks(hash TEXT PRIMARY KEY,body BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS hot_refs(identity TEXT NOT NULL,hash TEXT NOT NULL,
      PRIMARY KEY(identity,hash)) WITHOUT ROWID;
    CREATE INDEX IF NOT EXISTS hot_ref_hash ON hot_refs(hash);
    CREATE TABLE IF NOT EXISTS address_keys(id INTEGER PRIMARY KEY,address TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS address_refs(address_id INTEGER NOT NULL,record_id INTEGER NOT NULL,slot INTEGER NOT NULL,
      PRIMARY KEY(address_id,record_id)) WITHOUT ROWID;
    CREATE INDEX IF NOT EXISTS address_record ON address_refs(record_id);
    ''')
    old=db.execute("SELECT type FROM sqlite_master WHERE name='addresses'").fetchone()
    db.execute('BEGIN IMMEDIATE')
    try:
        if old and old[0]=='table':
            db.execute('INSERT OR IGNORE INTO address_keys(address) SELECT DISTINCT address FROM addresses')
            db.execute('INSERT OR IGNORE INTO address_refs SELECT k.id,r.rowid,a.slot FROM addresses a JOIN address_keys k ON k.address=a.address JOIN records r ON r.identity=a.identity')
            db.execute('DROP TABLE addresses')
        db.execute('CREATE INDEX IF NOT EXISTS address_window ON address_refs(address_id,slot)')
        db.execute('''CREATE VIEW IF NOT EXISTS addresses AS SELECT k.address,r.identity,a.slot
          FROM address_refs a JOIN address_keys k ON k.id=a.address_id JOIN records r ON r.rowid=a.record_id''')
        db.execute('''CREATE TRIGGER IF NOT EXISTS addresses_insert INSTEAD OF INSERT ON addresses BEGIN
          INSERT OR IGNORE INTO address_keys(address) VALUES(NEW.address);
          INSERT OR IGNORE INTO address_refs SELECT k.id,r.rowid,NEW.slot FROM address_keys k,records r
            WHERE k.address=NEW.address AND r.identity=NEW.identity;
          END''')
        db.execute('''CREATE TRIGGER IF NOT EXISTS addresses_delete INSTEAD OF DELETE ON addresses BEGIN
          DELETE FROM address_refs WHERE address_id=(SELECT id FROM address_keys WHERE address=OLD.address)
            AND record_id=(SELECT rowid FROM records WHERE identity=OLD.identity);
          END''')
        db.execute('''CREATE TRIGGER IF NOT EXISTS record_storage_delete BEFORE DELETE ON records BEGIN
          DELETE FROM address_refs WHERE record_id=OLD.rowid;
          DELETE FROM hot_refs WHERE identity=OLD.identity;
          END''')
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK');raise


def _json(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def encode(body,db):
    raw=_json(body)
    if len(raw)<2048:return raw
    # Copy only modified containers; callers retain their immutable original.
    value=dict(body,payload=dict(body['payload']))
    for parent,key in (('raw_lineage','logs'),('meta','logMessages')):
        section=value['payload'].get(parent)
        if not isinstance(section,dict) or not isinstance(section.get(key),list):continue
        logs=_json(section[key]).encode()
        if len(logs)<512:continue
        checksum=hashlib.sha256(logs).hexdigest()
        db.execute('INSERT OR IGNORE INTO hot_chunks VALUES(?,?)',(checksum,zlib.compress(logs,1)))
        db.execute('INSERT OR IGNORE INTO hot_refs VALUES(?,?)',(body['identity'],checksum))
        value['payload'][parent]=dict(section,**{key:{'_hot_log_chunk':checksum}})
    return b'SEP1'+zlib.compress(_json(value).encode(),1)


def _inflate(raw):
    obj=zlib.decompressobj();value=obj.decompress(raw,16*1024*1024+1)
    if len(value)>16*1024*1024 or not obj.eof or obj.unused_data:raise ValueError('hot_chunk_bound_or_corruption')
    return value


def decode(raw,db):
    if isinstance(raw,str):return json.loads(raw) # original stores/small bodies
    if not isinstance(raw,bytes) or not raw.startswith(b'SEP1'):raise ValueError('hot_body_encoding')
    try:value=json.loads(_inflate(raw[4:]))
    except zlib.error as exc:raise ValueError('hot_body_corrupt') from exc
    for parent,key in (('raw_lineage','logs'),('meta','logMessages')):
        section=value['payload'].get(parent)
        ref=section.get(key) if isinstance(section,dict) else None
        if not isinstance(ref,dict) or set(ref)!={'_hot_log_chunk'}:continue
        row=db.execute('SELECT body FROM hot_chunks WHERE hash=?',(ref['_hot_log_chunk'],)).fetchone()
        if row is None:raise ValueError('hot_chunk_missing')
        try:logs=_inflate(row[0])
        except zlib.error as exc:raise ValueError('hot_chunk_corrupt') from exc
        if hashlib.sha256(logs).hexdigest()!=ref['_hot_log_chunk']:raise ValueError('hot_chunk_hash_mismatch')
        section[key]=json.loads(logs)
    return value


def collect(db,limit=1000):
    db.execute('DELETE FROM hot_chunks WHERE hash IN (SELECT hash FROM hot_chunks c WHERE NOT EXISTS(SELECT 1 FROM hot_refs r WHERE r.hash=c.hash) LIMIT ?)',(limit,))
    db.execute('DELETE FROM address_keys WHERE id IN (SELECT id FROM address_keys k WHERE NOT EXISTS(SELECT 1 FROM address_refs r WHERE r.address_id=k.id) LIMIT ?)',(limit,))
