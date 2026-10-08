"""Lossless hot representation; no authority, field projection or archive reads.

Long native identities/addresses are dictionary indexed. Repeated authenticated
log arrays share one compressed content-addressed chunk. Public record hashes
and archived bodies still cover the original complete canonical JSON.
"""
import hashlib
import json
import re
import zlib


def install(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS hot_chunks(hash TEXT PRIMARY KEY,body BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS hot_refs(identity TEXT NOT NULL,hash TEXT NOT NULL,
      PRIMARY KEY(identity,hash)) WITHOUT ROWID;
    CREATE INDEX IF NOT EXISTS hot_ref_hash ON hot_refs(hash);
    CREATE TABLE IF NOT EXISTS address_keys(id INTEGER PRIMARY KEY,address TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS address_refs(address_id INTEGER NOT NULL,record_id INTEGER NOT NULL,slot INTEGER NOT NULL,
      PRIMARY KEY(record_id,address_id)) WITHOUT ROWID;
    ''')
    old=db.execute("SELECT type FROM sqlite_master WHERE name='addresses'").fetchone()
    db.execute('BEGIN IMMEDIATE')
    try:
        # Run 381's 5.6M references made every record deletion fan out over the
        # address-keyed primary tree AND a redundant record index. Cluster the
        # immutable references by record; address_window still serves consumers.
        # Migration is atomic, disk-backed and preserves all integer identities.
        primary={r[1]:r[5] for r in db.execute('PRAGMA table_info(address_refs)')}
        if primary.get('record_id')!=1:
            from .solana_evidence_plane import require_storage
            path=next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main')
            pages=db.execute('PRAGMA page_count').fetchone()[0]*db.execute('PRAGMA page_size').fetchone()[0]
            require_storage(path,required_bytes=2*pages)
            if old and old[0]=='view':db.execute('DROP VIEW addresses')
            db.execute('DROP TRIGGER IF EXISTS record_storage_delete')
            db.execute('''CREATE TABLE ordered_address_refs(address_id INTEGER NOT NULL,
              record_id INTEGER NOT NULL,slot INTEGER NOT NULL,
              PRIMARY KEY(record_id,address_id)) WITHOUT ROWID''')
            db.execute('INSERT INTO ordered_address_refs SELECT * FROM address_refs')
            db.execute('DROP TABLE address_refs')
            db.execute('ALTER TABLE ordered_address_refs RENAME TO address_refs')
        db.execute('DROP INDEX IF EXISTS address_record')
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


def prepare(body,*,canonical_body=None):
    """Pure lossless encoding; SQLite remains owned by the serial commit worker."""
    raw=_json(body) if canonical_body is None else canonical_body
    if len(raw)<2048:return raw,()
    chunks=[]
    # Copy only modified containers; callers retain their immutable original.
    value=dict(body,payload=dict(body['payload']))
    for parent,key in (('raw_lineage','logs'),('meta','logMessages')):
        section=value['payload'].get(parent)
        if not isinstance(section,dict) or not isinstance(section.get(key),list):continue
        logs=_json(section[key]).encode()
        if len(logs)<512:continue
        checksum=hashlib.sha256(logs).hexdigest()
        chunks.append((checksum,zlib.compress(logs,1)))
        value['payload'][parent]=dict(section,**{key:{'_hot_log_chunk':checksum}})
    return b'SEP1'+zlib.compress(_json(value).encode(),1),tuple(chunks)

def publish_addresses(db,identity,slot,addresses,cache):
    """Reuse bounded key lookups within one owner transaction; preserve view semantics."""
    record=db.execute('SELECT rowid FROM records WHERE identity=?',(identity,)).fetchone()
    if record is None:return
    refs=[]
    for address in addresses:
        key=cache.get(address)
        if key is None:
            db.execute('INSERT OR IGNORE INTO address_keys(address) VALUES(?)',(address,))
            key=db.execute('SELECT id FROM address_keys WHERE address=?',(address,)).fetchone()[0]
            if len(cache)<4096:cache[address]=key
        refs.append((key,record[0],slot))
    # The native address_refs triggers still maintain orphan/retention witnesses.
    db.executemany('INSERT OR IGNORE INTO address_refs VALUES(?,?,?)',refs)


def publish(db,identity,encoded,chunks):
    for checksum,body in chunks:
        db.execute('INSERT OR IGNORE INTO hot_chunks VALUES(?,?)',(checksum,body))
        db.execute('INSERT OR IGNORE INTO hot_refs VALUES(?,?)',(identity,checksum))
    return encoded

def encode(body,db,*,canonical_body=None):
    encoded,chunks=prepare(body,canonical_body=canonical_body)
    return publish(db,body['identity'],encoded,chunks)


def _inflate(raw):
    obj=zlib.decompressobj();value=obj.decompress(raw,16*1024*1024+1)
    if len(value)>16*1024*1024 or not obj.eof or obj.unused_data:raise ValueError('hot_chunk_bound_or_corruption')
    return value


def decode(raw,db=None,*,chunks=None,decoded_chunks=None):
    if isinstance(raw,str):return json.loads(raw) # original stores/small bodies
    if not isinstance(raw,bytes) or not raw.startswith(b'SEP1'):raise ValueError('hot_body_encoding')
    try:value=json.loads(_inflate(raw[4:]))
    except zlib.error as exc:raise ValueError('hot_body_corrupt') from exc
    for parent,key in (('raw_lineage','logs'),('meta','logMessages')):
        section=value['payload'].get(parent)
        ref=section.get(key) if isinstance(section,dict) else None
        if not isinstance(ref,dict) or set(ref)!={'_hot_log_chunk'}:continue
        checksum=ref['_hot_log_chunk']
        if decoded_chunks is not None and checksum in decoded_chunks:
            section[key]=decoded_chunks[checksum][1];continue
        row=((chunks[ref['_hot_log_chunk']],) if ref['_hot_log_chunk'] in chunks else None) if chunks is not None else db.execute('SELECT body FROM hot_chunks WHERE hash=?',(ref['_hot_log_chunk'],)).fetchone()
        if row is None:raise ValueError('hot_chunk_missing')
        try:logs=_inflate(row[0])
        except zlib.error as exc:raise ValueError('hot_chunk_corrupt') from exc
        if hashlib.sha256(logs).hexdigest()!=ref['_hot_log_chunk']:raise ValueError('hot_chunk_hash_mismatch')
        section[key]=json.loads(logs)
        # Used only inside one immutable off-owner archive snapshot. Repeated
        # authenticated log chunks need one hash/decode; bound cache by raw bytes.
        if decoded_chunks is not None and sum(v[0] for v in decoded_chunks.values())+len(logs)<=4*1024*1024:
            decoded_chunks[checksum]=(len(logs),section[key])
    return value


def archive_body(raw,*,chunks,raw_chunks):
    """Restore canonical bytes without parsing/serializing repeated log arrays.

    Only the two existing log-reference paths are eligible. Ambiguous marker
    occurrences use the ordinary decoder. The caller must verify the complete
    restored body hash before publication; the hot format/authority is unchanged.
    Returned fields are only the immutable commit-time pin keys.
    """
    if isinstance(raw,str):
        value=json.loads(raw)
        return dict(scope=value['scope'],slot=value['slot']),_json(value)
    if not isinstance(raw,bytes) or not raw.startswith(b'SEP1'):raise ValueError('hot_body_encoding')
    try:encoded=_inflate(raw[4:])
    except zlib.error as exc:raise ValueError('hot_body_corrupt') from exc
    value=json.loads(encoded);references={}
    for parent,key in (('raw_lineage','logs'),('meta','logMessages')):
        section=value['payload'].get(parent)
        ref=section.get(key) if isinstance(section,dict) else None
        if isinstance(ref,dict) and set(ref)=={'_hot_log_chunk'}:
            checksum=ref['_hot_log_chunk']
            references[checksum]=references.get(checksum,0)+1
    for checksum,count in references.items():
        marker=_json({'_hot_log_chunk':checksum}).encode()
        if encoded.count(marker)!=count:
            body=decode(raw,chunks=chunks)
            return dict(scope=body['scope'],slot=body['slot']),_json(body)
    replacements={}
    for checksum in references:
        if checksum in raw_chunks:logs=raw_chunks[checksum]
        else:
            if checksum not in chunks:raise ValueError('hot_chunk_missing')
            try:logs=_inflate(chunks[checksum])
            except zlib.error as exc:raise ValueError('hot_chunk_corrupt') from exc
            if hashlib.sha256(logs).hexdigest()!=checksum:raise ValueError('hot_chunk_hash_mismatch')
            if sum(map(len,raw_chunks.values()))+len(logs)<=4*1024*1024:
                raw_chunks[checksum]=logs
        replacements[_json({'_hot_log_chunk':checksum}).encode()]=logs
    # One pass: content inside an inserted log chunk is never interpreted as
    # another reference, even if a legitimate log contains a marker-shaped value.
    if len(replacements)==1:
        marker,logs=next(iter(replacements.items()));encoded=encoded.replace(marker,logs)
    elif replacements:
        encoded=re.sub(b'|'.join(re.escape(k) for k in replacements),lambda m:replacements[m[0]],encoded)
    return dict(scope=value['scope'],slot=value['slot']),encoded.decode()


def collect(db,limit=1000):
    db.execute('DELETE FROM hot_chunks WHERE hash IN (SELECT hash FROM hot_chunks c WHERE NOT EXISTS(SELECT 1 FROM hot_refs r WHERE r.hash=c.hash) LIMIT ?)',(limit,))
    db.execute('DELETE FROM address_keys WHERE id IN (SELECT id FROM address_keys k WHERE NOT EXISTS(SELECT 1 FROM address_refs r WHERE r.address_id=k.id) LIMIT ?)',(limit,))
