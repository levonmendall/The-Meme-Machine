"""Stable bounded subscriptions: candidate arrivals never rebuild position feeds."""
from .solana_evidence_plane import digest

class StableShards:
    def __init__(self,size=48):
        if not 1<=size<=48:raise ValueError('candidate_shard_bound')
        self.size=size;self.groups={};self.next_id=0
    def reconcile(self,rows):
        desired={(r['family'],r['address']):r for r in rows}
        def category(row):return (row['priority']<=1,row['family']=='meteora')
        # Keep occupied slots stable. A change of observation priority alone
        # does not alter the provider subscription, nor its continuity session.
        assigned=set()
        for number,group in list(self.groups.items()):
            kind,keys=group
            keys=[k for k in keys if k in desired and category(desired[k])==kind]
            if keys:self.groups[number]=(kind,keys);assigned.update(keys)
            else:del self.groups[number]
        # A new scope gets a new bounded group. Joining an already running
        # partial group would disconnect its members on every discovery burst.
        # Groups created in this turn can share a subscription; existing ones
        # retain their exact receipt/checkpoint handoff until a member retires.
        fresh=set()
        for key,row in desired.items():
            if key in assigned:continue
            kind=category(row)
            number=next((n for n,(p,keys) in self.groups.items() if n in fresh and p==kind and len(keys)<max(1,self.size-int(kind[1]))),None)
            if number is None:
                number=self.next_id;self.next_id+=1;self.groups[number]=(kind,[]);fresh.add(number)
            self.groups[number][1].append(key);assigned.add(key)
        return {n:dict(rows=[desired[k] for k in keys],identity=digest(sorted((k,desired[k].get('scope')) for k in keys)),position=kind[0])
                for n,(kind,keys) in self.groups.items()}
