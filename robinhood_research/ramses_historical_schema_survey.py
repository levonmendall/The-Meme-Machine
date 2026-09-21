"""Survey the public Ramses/Robinhood GraphQL schema for DLMM research tables.

Research/discovery only. No strategy policy or allocation authority.
"""
from __future__ import annotations
import json, urllib.request
from pathlib import Path

ENDPOINT="https://gateway.kingdom.dev/robinhood/subgraph/v1/graphql"
OUT=Path("ramses-historical-schema-survey.json")

def gql(query):
    body=json.dumps({"query":query}).encode()
    req=urllib.request.Request(ENDPOINT,data=body,headers={
        "Content-Type":"application/json","Accept":"application/json",
        "User-Agent":"meme-machine-ramses-schema-survey/1",
    })
    with urllib.request.urlopen(req,timeout=60) as r:
        payload=json.loads(r.read())
    if payload.get("errors"):
        raise RuntimeError("graphql:"+json.dumps(payload["errors"],sort_keys=True))
    return payload["data"]

def main():
    q="""query{
      __schema{
        types{
          name kind
          fields{
            name
            type{kind name ofType{kind name ofType{kind name}}}
          }
        }
      }
    }"""
    rows=gql(q)["__schema"]["types"]
    keep={}
    needles=("dlmm","liquidity","position","bin","pool","fee","swap")
    for row in rows:
        name=str(row.get("name") or "")
        low=name.lower()
        if not any(n in low for n in needles):
            continue
        if name.startswith("__"):
            continue
        keep[name]=row
    OUT.write_text(json.dumps(keep,indent=2,sort_keys=True))
    print(json.dumps({"types":sorted(keep),"count":len(keep)},sort_keys=True))

if __name__=="__main__":
    main()
