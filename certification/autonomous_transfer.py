"""Bounded transport of an existing verified capsule, never new state authority.

Raw native evidence stays in its immutable predecessor artifact. Transfer only
its already-sealed successor capsule and review, in <=256-MiB pieces, through
existing digest-verified <=512-MiB downloads. The aggregate 8-GiB/50,000-file
extraction bounds remain unchanged. No historical archive is made HOT again.
"""
import hashlib
import io
import json
from pathlib import Path
import os
import stat
import tempfile
import zipfile

from certification import autonomous_control as control, campaign_state
from certification.journal import digest
from certification.position_continuation import _atomic

PART_BYTES=256*1024**2
TOTAL_BYTES=8*1024**3
MAX_PARTS=32
MAX_FILES=50000
SCHEMA='autonomous-capsule-transfer-v1'


def part_name(name,index):
    if type(index) is not int or not 0<=index<MAX_PARTS:raise ValueError('autonomous_transfer_part_index')
    return name+'-part-'+str(index).zfill(2)


class _Parts(io.RawIOBase):
    def __init__(self,root):
        super().__init__();self.root=Path(root);self.position=0;self.file=None;self.rows=[]
    def writable(self):return True
    def seekable(self):return False
    def tell(self):return self.position
    def _close_part(self):
        if self.file is None:return
        self.file.flush();os.fsync(self.file.fileno());self.file.close();self.file=None
        self.rows[-1]['sha256']=self.hasher.hexdigest()
    def write(self,raw):
        if self.position+len(raw)>TOTAL_BYTES:raise ValueError('autonomous_transfer_total_bound')
        view=memoryview(raw);length=len(view)
        while view:
            if self.file is None or self.rows[-1]['bytes']==PART_BYTES:
                self._close_part();index=len(self.rows)
                if index>=MAX_PARTS:raise ValueError('autonomous_transfer_part_bound')
                folder=self.root/str(index).zfill(2);folder.mkdir(parents=True)
                self.file=(folder/'payload').open('xb');self.hasher=hashlib.sha256()
                self.rows.append(dict(index=index,bytes=0))
            block=view[:PART_BYTES-self.rows[-1]['bytes']]
            self.file.write(block);self.hasher.update(block)
            self.rows[-1]['bytes']+=len(block);self.position+=len(block);view=view[len(block):]
        return length
    def flush(self):
        if self.file:self.file.flush()
    def close(self):
        self._close_part();super().close()


def pack(output,destination,claim,native):
    from certification.autonomous_window import verify_snapshot,read
    output=Path(output);destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=False)
    capsule=read(output/'capsule/campaign-state.json');window=claim['window']
    campaign_state.verify(output/'capsule',expected_identity=claim['identity'],
        expected_state_hash=capsule['state_hash'],campaign_id=claim['campaign_id'],
        prior_index=window['index'],authorization_hash=claim['authorization_hash'])
    review=read(output/'window-review.json')
    if (review.get('passed') is not True or review.get('identity')!=claim['identity']
            or review.get('state_hash')!=capsule['state_hash']):
        raise ValueError('autonomous_transfer_unreviewed')
    snapshot=verify_snapshot(output/'artifact')
    name=control.artifact_name(claim,window['workflow_run_id'])
    if native['name']!=name+'-native' or native['workflow_run_id']!=window['workflow_run_id']:
        raise ValueError('autonomous_transfer_native_identity')
    names=['window-review.json','smoke-continuation-state.json']
    names+=['position-after.json'] if window['mode']=='position' else ['artifact/assurance/market-assurance.json']
    names += [str(path.relative_to(output)) for path in sorted((output/'capsule').rglob('*')) if path.is_file()]
    if len(names)>MAX_FILES:raise ValueError('autonomous_transfer_file_bound')
    files=[]
    with _Parts(destination/'parts') as writer:
        with zipfile.ZipFile(writer,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
            for name in names:
                source=output/name
                if source.is_symlink() or not source.is_file():raise ValueError('autonomous_transfer_source_file')
                archive.write(source,name)
                files.append(name)
        size=writer.position
    result=dict(schema=SCHEMA,identity=claim['identity'],campaign_id=claim['campaign_id'],
        workflow_run_id=window['workflow_run_id'],index=window['index'],
        state_hash=capsule['state_hash'],review_hash=digest(review),
        native_artifact=native,native_snapshot_hash=digest(snapshot),
        bytes=size,parts=writer.rows,files=files,entry_authority=False)
    _atomic(destination/'pending.json',result)
    return result


def seal(api,destination,name):
    destination=Path(destination);body=json.loads((destination/'pending.json').read_text())
    run_id=body['workflow_run_id']
    native=body['native_artifact']
    if control._artifact_metadata(api,run_id,native['name'])!=native:
        raise ValueError('autonomous_transfer_native_drift')
    for part in body['parts']:
        part['artifact']=control._artifact_metadata(api,run_id,part_name(name,part['index']))
    index=destination/'index';index.mkdir()
    _atomic(index/'transfer.json',body)
    return body


def validate(body,reference):
    parts=body.get('parts',[])
    if (body.get('schema')!=SCHEMA or body.get('entry_authority') is not False
            or body.get('workflow_run_id')!=reference['workflow_run_id']
            or not 1<=len(parts)<=MAX_PARTS
            or type(body.get('bytes')) is not int or not 0<body['bytes']<=TOTAL_BYTES):
        raise ValueError('autonomous_transfer_manifest')
    if len(body.get('files',[]))>MAX_FILES or len(set(body['files']))!=len(body['files']):
        raise ValueError('autonomous_transfer_manifest_files')
    for index,part in enumerate(parts):
        if (part.get('index')!=index or type(part.get('bytes')) is not int
                or not 0<part['bytes']<=PART_BYTES
                or (index<len(parts)-1 and part['bytes']!=PART_BYTES)
                or part['artifact']['name']!=part_name(reference['name'],index)
                or part['artifact']['workflow_run_id']!=reference['workflow_run_id']):
            raise ValueError('autonomous_transfer_part_identity')
    if sum(p['bytes'] for p in parts)!=body['bytes']:raise ValueError('autonomous_transfer_total')
    native=body['native_artifact']
    if (native['name']!=reference['name']+'-native'
            or native['workflow_run_id']!=reference['workflow_run_id']):
        raise ValueError('autonomous_transfer_native_identity')


class _Reader(io.RawIOBase):
    """Seek a bounded capsule ZIP with only one 256-MiB part cached on disk."""
    def __init__(self,api,body,directory):
        super().__init__();self.api=api;self.body=body;self.position=0
        self.cached=None;self.loaded=set();self.file=tempfile.TemporaryFile(dir=directory)
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        value=offset+(self.position if whence==1 else self.body['bytes'] if whence==2 else 0)
        if whence not in (0,1,2) or not 0<=value<=self.body['bytes']:
            raise ValueError('autonomous_transfer_seek')
        self.position=value;return value
    def _load(self,index):
        if self.cached==index:return
        part=self.body['parts'][index];ref=part['artifact']
        archive,item=self.api.artifact(ref['workflow_run_id'],ref['name'])
        self.cached=None;self.file.seek(0);self.file.truncate()
        with archive:
            if item['id']!=ref['id'] or item['digest']!=ref['digest']:
                raise ValueError('autonomous_transfer_part_artifact')
            infos=archive.infolist()
            if (len(infos)!=1 or infos[0].filename!='payload'
                    or infos[0].file_size!=part['bytes'] or stat.S_ISLNK(infos[0].external_attr>>16)):
                raise ValueError('autonomous_transfer_part_member')
            hasher=hashlib.sha256();size=0
            with archive.open(infos[0]) as stream:
                while block:=stream.read(1024*1024):
                    size+=len(block)
                    if size>part['bytes']:raise ValueError('autonomous_transfer_part_size')
                    hasher.update(block);self.file.write(block)
            if size!=part['bytes'] or hasher.hexdigest()!=part['sha256']:
                raise ValueError('autonomous_transfer_part_hash')
        self.cached=index;self.loaded.add(index)
    def read(self,size=-1):
        size=self.body['bytes']-self.position if size<0 else min(size,self.body['bytes']-self.position)
        if size>512*1024**2:raise ValueError('autonomous_transfer_read_bound')
        result=bytearray()
        while size:
            index,offset=divmod(self.position,PART_BYTES);self._load(index)
            count=min(size,self.body['parts'][index]['bytes']-offset)
            self.file.seek(offset);block=self.file.read(count)
            if len(block)!=count:raise ValueError('autonomous_transfer_cache_short')
            result.extend(block);self.position+=count;size-=count
        return bytes(result)
    def close(self):
        self.file.close();super().close()


def extract(api,body,reference,destination,extract_checked):
    validate(body,reference)
    native=body['native_artifact']
    if control._artifact_metadata(api,native['workflow_run_id'],native['name'])!=native:
        raise ValueError('autonomous_transfer_native_drift')
    destination=Path(destination)
    with _Reader(api,body,destination.parent) as reader:
        with zipfile.ZipFile(reader) as archive:
            if archive.namelist()!=body['files']:raise ValueError('autonomous_transfer_file_inventory')
            extract_checked(archive,destination)
        if reader.loaded!=set(range(len(body['parts']))):
            raise ValueError('autonomous_transfer_unread_part')
    capsule=json.loads((destination/'capsule/campaign-state.json').read_text())
    review=json.loads((destination/'window-review.json').read_text())
    if capsule['state_hash']!=body['state_hash'] or digest(review)!=body['review_hash']:
        raise ValueError('autonomous_transfer_proof_hash')
    _atomic(destination/'transfer-proof.json',body)
    return destination
