"""Finite phase measurements; read-only and never a capacity admission rule."""
class Trend:
    def __init__(self):
        self.first=None;self.last=None;self.peak_wal=0;self.samples=0

    def add(self,sample):
        self.first=self.first or sample;self.last=sample;self.samples+=1
        self.peak_wal=max(self.peak_wal,sum(size for name,size in sample.get('storage',{}).items() if name.endswith('-wal')))

    def result(self):
        if self.first is None:return None
        start,end=self.first,self.last;seconds=end['timestamp']-start['timestamp']
        before=start.get('storage_totals',{});after=end.get('storage_totals',{})
        growth={key:after.get(key,0)-before.get(key,0) for key in ('state_root_bytes','archive_bytes','learning_store_bytes')}
        rate=None if seconds<=0 else growth['state_root_bytes']*3600/seconds
        disks=end.get('host',{}).get('disks',{});volume=disks[max(disks,key=len)] if disks else {}
        overhead={}
        for name,latest in end.get('host',{}).get('observation_stack',{}).items():
            original=start.get('host',{}).get('observation_stack',{}).get(name,{})
            delta=latest.get('cpu_usage_ns',0)-original.get('cpu_usage_ns',0)
            overhead[name]=dict(cpu_percent_of_host=None if seconds<=0 or delta<0 or latest.get('unavailable') or original.get('unavailable') else
                100*delta/(seconds*10**9*end['host']['cpu_count']),memory_bytes=latest.get('memory_bytes'),
                counter_reset=delta<0)
        return dict(baseline_timestamp=start['timestamp'],ending_timestamp=end['timestamp'],samples=self.samples,
            net_state_root_growth=growth['state_root_bytes'],net_bytes_per_hour=rate,
            peak_wal_bytes=self.peak_wal,archive_growth=growth['archive_bytes'],learning_store_growth=growth['learning_store_bytes'],
            projected_days_to_volume_capacity=volume.get('free_bytes',0)/(rate*24) if rate is not None and rate>0 else None,
            projection_assumption='constant observed net growth; retention can change this rate',
            main_db_growth={name:size-start.get('storage',{}).get(name,0) for name,size in end.get('storage',{}).items()
                            if name.endswith(('.sqlite','.sqlite3'))},
            observation_overhead=overhead,baseline=before,ending=after)
