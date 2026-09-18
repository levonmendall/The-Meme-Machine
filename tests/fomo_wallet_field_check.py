import json,os,urllib.parse,urllib.request
key=os.environ["FOMOAPI_KEY"]
req=urllib.request.Request("https://api.fomoapi.io/v2/leaderboard/30d?limit=5",headers={"Authorization":"Bearer "+key,"Accept":"application/json"})
with urllib.request.urlopen(req,timeout=20) as r:b=json.loads(r.read())
row=next(x for x in b.get("traders",[]) if x.get("handle")=="unipcs")
print(json.dumps({"handle":"unipcs","wallets":row.get("wallets"),"shrine_resolved":"2heJbC32Tpfcb3nbUb5ER61K11FGZVfVGtVnDm6LDogF","matches":((row.get("wallets") or {}).get("solana")=="2heJbC32Tpfcb3nbUb5ER61K11FGZVfVGtVnDm6LDogF")},indent=2))
