"""Observe exact production frames before local routing, without replacing transport."""
import hashlib,json,struct,time,zlib
import simdjson
from collections import Counter,defaultdict

def websocket_metadata(raw):
    # The observer needs routing fields only. Full native JSON validation and
    # the exact raw archive remain; no log subtree becomes Python strings here.
    from meme_machine.solana_source_intake import _object
    root=_object(simdjson.Parser(16*1024*1024).parse(raw),'source_message_shape')
    metadata=dict(message='ack' if 'id' in root else root.get('method'))
    if 'params' in root:
        params=_object(root['params'],'source_message_shape')
        result=_object(params['result'],'source_message_shape')
        value=_object(result['value'],'source_message_shape')
        metadata.update(slot=result['context']['slot'],signature=value.get('signature'))
    return metadata

class TransportMeter:
    def __init__(self,path):
        self.file=path.open('wb');self.compress=zlib.compressobj(6)
        self.active={};self.subscriptions=[];self.delivery=Counter();self.messages=Counter()
        self.duplicates=Counter();self.recent={};self.latencies=defaultdict(list)
        self.timestamps_missing=Counter();self.events=[];self.peak_shards=0;self.control=Counter();self.producer_waits=[]
        self.native_errors=[]
        self.decode=Counter();self.evidence_timings=[];self.observer_seconds=0
    def write(self,metadata,raw=b''):
        header=json.dumps(metadata,separators=(',',':')).encode()
        self.file.write(self.compress.compress(struct.pack('!II',len(header),len(raw))+header+raw))
    def __call__(self,kind,value):
        from meme_machine.yellowstone import geyser_pb2 as pb
        at=time.time();started=time.monotonic()
        if kind=='decode_timing':
            label=value['transport'];self.decode[label+'.messages']+=1
            self.decode[label+'.bytes']+=value['bytes'];self.decode[label+'.seconds']+=value['seconds']
            return
        if kind in ('evidence_timing','publication_timing'):
            self.evidence_timings.append(dict(kind=kind,**value));self.write(dict(kind=kind,at=at,**value));return
        if kind=='rolling_retry' or kind.startswith('membership_') or kind=='owner_backpressure':
            self.control[kind]+=1
            if kind=='owner_backpressure':self.producer_waits.append(value)
            self.write(dict(kind=kind,at=at,**value));return
        sid=value['stream_id']
        if kind=='native_error':
            subscription=self.active.get(sid,{})
            row=dict(kind=kind,at=at,**value,filters=subscription.get('filters'),
                filter_types=subscription.get('filter_types'),from_slot=subscription.get('from_slot'),
                address_count=len(subscription.get('addresses',[])),active_streams=len(self.active))
            self.native_errors.append(row);self.write(row);return
        if kind=='subscribe':
            r=value['request'];names=('accounts','transactions','transactions_status','blocks','blocks_meta','slots')
            counts={name:len(getattr(r,name)) for name in names}
            addresses=set()
            for name in ('transactions','transactions_status'):
                for f in getattr(r,name).values():addresses.update(f.account_include)
            row=dict(kind=kind,at=at,id=sid,family=value['family'],filters=sum(counts.values()),filter_types=counts,
                     addresses=sorted(addresses),from_slot=r.from_slot if r.HasField('from_slot') else None)
            self.active[sid]=row;self.subscriptions.append(row)
            self.peak_shards=max(self.peak_shards,len(self.active));self.write(row,r.SerializeToString());return
        if kind=='websocket_open':
            row=dict(kind=kind,at=at,id=sid,addresses=value['addresses']);self.subscriptions.append(row);self.write(row);return
        if kind=='unsubscribe':
            self.active.pop(sid,None);self.write(dict(kind=kind,at=at,id=sid));return
        raw=value['raw'];transport=value['transport'];family=value['family'];seen=value['seen']
        self.delivery[(transport,family)]+=len(raw);self.messages[(transport,family)]+=1
        metadata=dict(kind='delivery',id=sid,family=family,transport=transport,seen=seen,bytes=len(raw))
        if 'received_monotonic' in value:metadata['received_monotonic']=value['received_monotonic']
        if transport=='yellowstone':
            update=pb.SubscribeUpdate.FromString(raw);message=update.WhichOneof('update_oneof');metadata['message']=message
            if update.HasField('created_at'):
                available=update.created_at.seconds+update.created_at.nanos/1e9
                if 0<=seen-available:self.latencies[family+'_created_at_age'].append(seen-available)
                metadata['provider_created_at']=available
            else:self.timestamps_missing[family]+=1
            item=getattr(update,message) if message else None
            if hasattr(item,'slot'):metadata['slot']=item.slot
            # Routing labels and delivery clock differ across shards; content does not.
            update.ClearField('filters');update.ClearField('created_at')
            checksum=hashlib.sha256(update.SerializeToString()).digest()
            old=self.recent.get(checksum)
            if old and old[0]!=sid and seen-old[1]<20:
                self.duplicates[(transport,family)]+=len(raw);metadata['cross_shard_duplicate']=True
            else:self.recent[checksum]=(sid,seen)
            if len(self.recent)>50000:self.recent={k:v for k,v in self.recent.items() if seen-v[1]<15}
        else:
            metadata.update(websocket_metadata(raw))
        self.write(metadata,raw)
        self.observer_seconds+=time.monotonic()-started
    def summary(self):
        return dict(delivery=[dict(transport=t,family=f,bytes=b,messages=self.messages[t,f],duplicate_bytes=self.duplicates[t,f]) for (t,f),b in self.delivery.items()],
                    control=dict(self.control),producer_waits=self.producer_waits,
                    subscriptions=self.subscriptions,peak_native_streams=self.peak_shards,
                    provider_timestamp_missing=dict(self.timestamps_missing),native_errors=self.native_errors,
                    native_status_counts=dict(Counter(r['status'] for r in self.native_errors)),
                    local_decode=dict(self.decode),evidence_timings=self.evidence_timings,
                    observer_seconds=self.observer_seconds,
                    timestamp_semantics='created_at is an upstream timestamp, not a certified finality or dispatch clock')
    def close(self):
        self.file.write(self.compress.flush());self.file.close()
