"""Observe exact production frames before local routing, without replacing transport."""
import hashlib,json,struct,time,zlib
from collections import Counter,defaultdict

class TransportMeter:
    def __init__(self,path):
        self.file=path.open('wb');self.compress=zlib.compressobj(6)
        self.active={};self.subscriptions=[];self.delivery=Counter();self.messages=Counter()
        self.duplicates=Counter();self.recent={};self.latencies=defaultdict(list)
        self.timestamps_missing=Counter();self.events=[];self.peak_shards=0;self.control=Counter();self.producer_waits=[]
    def write(self,metadata,raw=b''):
        header=json.dumps(metadata,separators=(',',':')).encode()
        self.file.write(self.compress.compress(struct.pack('!II',len(header),len(raw))+header+raw))
    def __call__(self,kind,value):
        from meme_machine.yellowstone import geyser_pb2 as pb
        at=time.time()
        if kind=='rolling_retry' or kind.startswith('membership_') or kind=='owner_backpressure':
            self.control[kind]+=1
            if kind=='owner_backpressure':self.producer_waits.append(value)
            self.write(dict(kind=kind,at=at,**value));return
        sid=value['stream_id']
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
        if transport=='yellowstone':
            update=pb.SubscribeUpdate.FromString(raw);message=update.WhichOneof('update_oneof');metadata['message']=message
            if update.HasField('created_at'):
                available=update.created_at.seconds+update.created_at.nanos/1e9
                if 0<=seen-available:self.latencies[family+'_delivery'].append(seen-available);metadata['provider_available']=available
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
            v=json.loads(raw);metadata['message']='ack' if 'id' in v else v.get('method')
            if 'params' in v:
                result=v['params']['result'];metadata['slot']=result['context']['slot']
                metadata['signature']=result['value'].get('signature')
        self.write(metadata,raw)
    def summary(self):
        return dict(delivery=[dict(transport=t,family=f,bytes=b,messages=self.messages[t,f],duplicate_bytes=self.duplicates[t,f]) for (t,f),b in self.delivery.items()],
                    control=dict(self.control),producer_waits=self.producer_waits,
                    subscriptions=self.subscriptions,peak_native_streams=self.peak_shards,
                    provider_timestamp_missing=dict(self.timestamps_missing))
    def close(self):
        self.file.write(self.compress.flush());self.file.close()
