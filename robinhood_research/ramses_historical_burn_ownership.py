"""Resolve Ramses DLMM burn ownership using indexed transaction caller and position terminal identity."""
from __future__ import annotations
from collections import Counter,defaultdict
import json,urllib.request
from pathlib import Path

ENDPOINT="https://gateway.kingdom.dev/robinhood/subgraph/v1/graphql"
CHAIN=4663
LIMIT=1000
OUT=Path("ramses-historical-burn-ownership.json")

def gql(q,v=None):
    req=urllib.request.Request(ENDPOINT,data=json.dumps({"query":q,"variables":v or {}}).encode(),
      headers={"Content-Type":"application/json","Accept":"application/json","User-Agent":"meme-machine-ramses-burn-owner/1"})
    with urllib.request.urlopen(req,timeout=60) as r:p=json.loads(r.read())
    if p.get("errors"):raise RuntimeError("graphql:"+json.dumps(p["errors"],sort_keys=True))
    return p["data"]

def page(root,fields):
    rows=[];off=0
    while True:
      q=f"""query($n:Int!,$o:Int!){{{root}(limit:$n,offset:$o,where:{{chainId:{{_eq:{CHAIN}}}}},order_by:{{id:asc}}){{{fields}}}}}"""
      part=gql(q,{"n":LIMIT,"o":off})[root];rows.extend(part)
      if len(part)<LIMIT:return rows
      off+=LIMIT

def addr(v):return str(v or "").split(":")[-1].lower()
def main():
    burns=page("DLMMBurn","id pool transaction logIndex sender recipient timestamp amountUSD binIds")
    positions=page("DLMMPosition","id owner pool liquidity lastModifiedBlockNumber lastModifiedLogIndex lastModifiedTimestamp")
    owners=defaultdict(set);closed_by_block=defaultdict(list)
    for p in positions:
      pool=addr(p.get("pool"));owner=str(p.get("owner") or "").lower();owners[pool].add(owner)
      if str(p.get("liquidity") or "0")=="0":
        try:block=int(p.get("lastModifiedBlockNumber") or 0);log=int(p.get("lastModifiedLogIndex") or 0)
        except:continue
        closed_by_block[(pool,block)].append((owner,log))

    txids=sorted({str(b.get("transaction") or "") for b in burns if b.get("transaction")})
    txmap={}
    # Hasura's _in path on this index currently returns no Transaction rows even
    # for valid IDs. Use bounded GraphQL aliases with exact equality instead.
    for first in range(0,len(txids),80):
      ids=txids[first:first+80]
      parts=[]
      for n,ident in enumerate(ids):
        safe=ident.replace("\\","\\\\").replace('"','\\"')
        parts.append(
          f'q{n}:Transaction(limit:1,where:{{chainId:{{_eq:{CHAIN}}},id:{{_eq:"{safe}"}}}})'
          '{id from to blockNumber timestamp gasUsed gasPrice}'
        )
      data=gql("query{"+ " ".join(parts) +"}")
      for n,ident in enumerate(ids):
        rows=data.get(f"q{n}") or []
        if len(rows)>1:raise RuntimeError("ramses_burn_transaction_duplicate")
        if rows:txmap[ident]=rows[0]

    resolved=[];reasons=Counter()
    for b in burns:
      pool=addr(b.get("pool"));rec=str(b.get("recipient") or "").lower()
      tx=txmap.get(str(b.get("transaction") or ""));caller=str((tx or {}).get("from") or "").lower()
      owner=None;method=None
      if rec in owners[pool]:
        owner=rec;method="burn_recipient"
      elif caller in owners[pool]:
        owner=caller;method="transaction_from"
      elif tx is not None:
        try:block=int(tx.get("blockNumber") or 0);blog=int(b.get("logIndex") or 0)
        except:block=0;blog=0
        candidates=closed_by_block.get((pool,block),[])
        exact=[o for o,l in candidates if l==blog]
        before=[o for o,l in candidates if l<=blog]
        uniq=set(exact or before or [o for o,_l in candidates])
        if len(uniq)==1:
          owner=next(iter(uniq));method="unique_terminal_position"
      if owner is None:
        reasons["unresolved"]+=1
      else:
        reasons[method]+=1
      resolved.append(dict(
        burn_id=b.get("id"),transaction=b.get("transaction"),pool=pool,
        timestamp=b.get("timestamp"),log_index=b.get("logIndex"),
        event_sender=b.get("sender"),event_recipient=b.get("recipient"),
        transaction_from=caller or None,transaction_block=((tx or {}).get("blockNumber")),
        owner=owner,resolution=method,amount_usd=b.get("amountUSD"),bin_ids=b.get("binIds")
      ))
    out=dict(kind="ramses_dlmm_burn_ownership_resolution_v1",burns=len(burns),
             transactions_found=len(txmap),resolution_counts=dict(reasons),
             resolved=sum(x["owner"] is not None for x in resolved),rows=resolved)
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True))
    print(json.dumps({k:out[k] for k in ("burns","transactions_found","resolved","resolution_counts")},sort_keys=True))
if __name__=="__main__":main()
