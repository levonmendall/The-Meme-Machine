"""Exact overlapping address filters for cheap, conservative activity routing.

Status messages contain identity/order/error but no account keys. Complementary
bit filters let a single-address transaction name its candidate cheaply. A
multi-candidate transaction explicitly wakes the compatible superset; it never
becomes an economic event or a completeness proof. Exact economics must still be
hydrated before qualification. Each shard fits the measured 50-filter limit.
"""
import math
from .solana_evidence_plane import EvidenceUnavailable,digest
from .yellowstone import geyser_pb2 as pb

# A 512-address include list delivered an actual finalized status in the final
# bounded diagnostic. Complementary filters therefore retain 1,024 identities
# per shard while each paid filter contains at most 512 addresses.
SHARD_SIZE=1024
LABELS='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWX'

class ActivityRoutes:
    def __init__(self,addresses):
        self.addresses=tuple(sorted(set(addresses)))
        if not 1<=len(self.addresses)<=SHARD_SIZE:
            raise EvidenceUnavailable('activity_shard_shape')
        self.bits=max(1,(len(self.addresses)-1).bit_length())
        self.identity=digest(self.addresses)
        self.groups={LABELS[2*bit+value]:tuple(address for index,address in enumerate(self.addresses)
            if index>>bit&1==value) for bit in range(self.bits) for value in (0,1)}
        # Empty include lists mean ALL transactions, so they must be omitted.
        self.groups={label:group for label,group in self.groups.items() if group}

    def subscription(self,*,from_slot=None):
        request=pb.SubscribeRequest(commitment=pb.FINALIZED)
        if from_slot is not None:
            if type(from_slot) is not int or from_slot<=0:raise EvidenceUnavailable('candidate_replay_floor_required')
            request.from_slot=from_slot
        for label,addresses in self.groups.items():
            f=request.transactions_status[label];f.vote=False;f.failed=False
            f.account_include.extend(addresses)
        return request

    def resolve(self,labels):
        labels=set(labels)
        if not labels or not labels.issubset(self.groups):raise EvidenceUnavailable('activity_filter_identity')
        masks=[]
        for bit in range(self.bits):
            values={value for value in (0,1) if LABELS[2*bit+value] in labels}
            if not values:raise EvidenceUnavailable('activity_filter_identity')
            masks.append(values)
        # Enumerate only durable identities; there is no combinatorial allocation
        # of synthetic candidates and no top-N discard of ambiguous matches.
        matches=tuple(address for index,address in enumerate(self.addresses)
                      if all(index>>bit&1 in masks[bit] for bit in range(self.bits)))
        if not matches:raise EvidenceUnavailable('activity_filter_identity')
        return dict(addresses=matches,exact=len(matches)==1,ambiguous=len(matches)>1,
                    economic_event=False,history_complete=False)

def shards(addresses):
    addresses=sorted(set(addresses))
    return [ActivityRoutes(addresses[n:n+SHARD_SIZE]) for n in range(0,len(addresses),SHARD_SIZE)]
