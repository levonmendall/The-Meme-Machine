"""Probe and export Ramses Robinhood DLMM indexed historical tables.

Public indexed data is used for discovery/cross-check only. Exact strategy outcomes
still require authenticated chain replay.
"""
from __future__ import annotations
import json, urllib.request
from pathlib import Path

ENDPOINT="https://gateway.kingdom.dev/robinhood/subgraph/v1/graphql"
OUT=Path("ramses-historical-subgraph-schema.json")
SAMPLE=Path("ramses-historical-subgraph-sample.json")

def gql(query,variables=None):
    body=json.dumps({"query":query,"variables":variables or {}}).encode()
    req=urllib.request.Request(ENDPOINT,data=body,headers={
        "Content-Type":"application/json",
        "Accept":"application/json",
        "User-Agent":"meme-machine-ramses-historical/1",
    })
    with urllib.request.urlopen(req,timeout=60) as r:
        payload=json.loads(r.read())
    if payload.get("errors"):
        raise RuntimeError("graphql:"+json.dumps(payload["errors"],sort_keys=True))
    return payload["data"]

def type_fields(name):
    q="""query($name:String!){__type(name:$name){name fields{name type{kind name ofType{kind name}}}}}"""
    row=gql(q,{"name":name}).get("__type")
    if not row: raise RuntimeError("missing_type:"+name)
    return row

def scalar_fields(type_row):
    allowed={"String","Int","Float","Boolean","ID","numeric","bigint","timestamptz","jsonb"}
    out=[]
    for f in type_row.get("fields") or []:
        t=f["type"];name=t.get("name") or (t.get("ofType") or {}).get("name")
        kind=t.get("kind") or (t.get("ofType") or {}).get("kind")
        if kind=="SCALAR" or name in allowed:
            out.append(f["name"])
    return out

def sample(root,fields):
    q="query($limit:Int!){%s(limit:$limit,order_by:{id:asc}){%s}}"%(root," ".join(fields))
    return gql(q,{"limit":3}).get(root,[])

def main():
    names=["DLMMSwap","DLMMFeeEvent","DLMMPool","DLMMProtocolDayData"]
    schema={n:type_fields(n) for n in names}
    OUT.write_text(json.dumps(schema,indent=2,sort_keys=True))
    samples={}
    for n in names:
        fields=scalar_fields(schema[n])
        # id may not exist on rollups; if order_by is rejected, fall back to unordered.
        try:samples[n]={"fields":fields,"rows":sample(n,fields)}
        except RuntimeError:
            q="query($limit:Int!){%s(limit:$limit){%s}}"%(n," ".join(fields))
            samples[n]={"fields":fields,"rows":gql(q,{"limit":3}).get(n,[])}
    SAMPLE.write_text(json.dumps(samples,indent=2,sort_keys=True))
    print(json.dumps({n:samples[n]["fields"] for n in names},sort_keys=True))

if __name__=="__main__":main()
