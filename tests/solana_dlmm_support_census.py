"""Exact support census for Solana DLMM pools rejected before qualification."""
import base64,json,struct
from collections import Counter
from pathlib import Path
from meme_machine import dlmm,pump
from tests import dlmm_alchemy_provider as provider

ROWS=[["CAcPoFMVZTXYw325GpUxZTL3ZD9QfASCuQSNrzoxCKdm","VRCAT-SOL","token_program"],["BWVTxff57edk4bafm2XZa4RxeM5ayCdncL1ivpprkjnL","WOW-SOL","token_program"],["55EvHE1dURgFbQcQaedL6FJhx2vj6Biu4ajVZC8MbAB2","JubJub-SOL","token_program"],["BdheyKvq8y4wFTKApFBgByCfiaDSJXbevBiEEdVQnao8","wCat-SOL","token_program"],["E3mWM4A6j52u5FStaA5onG5WpAonPbx2Cp2NwK6BfeqA","JubJub-SOL","token_program"],["4YVsPYix3QyW9qRAQ9WKiPW3kDe1upgv6BVr2NUrLp26","BUTT-SOL","token_program"],["HptDrjmMHrszxC9WvypC8RQV6Uv95bsxaLDbGkXvZc4X","ICE-SOL","fee_mode"],["5QpDQ6ddkv1ArytJQ991kh8doeXPrt9hHFWK2HmEToDm","FRIES-SOL","fee_mode"],["95NyuWzMDmWnPgLGBotT1XB2v1fQkqxhCrGLBDfxXfhn","KNOTS-SOL","token_program"],["9aXA6qqqXueA6Eq9WPRgas4wQgjPCEspzutbaS3UZkXT","CLANKER-SOL","fee_mode"],["4c5L2PqNdawj9su86nHamybaesbqZAmzxQXPCVuwrWDg","GB-SOL","token_program"],["8j8B5k7q6wHEyozNdez6e6pjNAV9YfjiuYJAjbDy8Yg1","LOTTO-SOL","fee_mode"],["8BD8x5Ms3f1unL9YiDGG4XQYxEcot1UqCkqkyTjniUNZ","Noiz-SOL","token_program"],["6PXjRGZsHVmCyDeyMgAZFVtsCqZdHa2hNmpfuP5vV8gi","RAYCAT-SOL","token_program"],["Ljw5KjLTTCKcYikBXPv1KB29mnm8hwM33RGmukp23tP","ORE-SOL","mint_authority"],["64JeeFJSB1pVw4fmNTvp4p37SudsqFboCMf8SeEdomzE","GP-SOL","token_program"],["7kVqQQs1JuWXxdbNzCEN5uXeqAuH99bx18FBAZaXL3DP","INU-SOL","token_program"],["FGjzPXTqEFornw3PjCmaNvhHZrZUGSjPBtfPJvJfo4Qi","fone-SOL","token_program"],["AhRRRnULBeKeCCwWi4wBqX5hu8NMJxFtbjpc9XkBKc1e","AGI-SOL","token_program"],["FoyTFL8FxB9X4kvQnHxzyeazXkseSLn1wkP4T2Dsomvt","PURR-SOL","token_program"],["3C6qVymTAwWNKCSspmd1qbUH9avaqhsjgW2yntvEYBXt","STONK-SOL","fee_mode"],["5pjRzUQan6bYynQERLK499fq48LiD5ryZrf9adZX1HQo","Jimothy-SOL","token_program"],["AjAu7XnVFYcf1LMfabkERPNGtd1cce1n4YhAnj9neb6d","RAYCAT-SOL","token_program"],["4YAs6WdHjCLxrnvfFaSXMj12KwLF1ioyXmLZ1ENbBDEB","Noiz-SOL","token_program"],["C3tTW4G8g9VDAxruxNZA517uNeVV3rbzVbWXfSN3sjZf","UBER-SOL","token_program"],["FpP5SnzBnHJ5M9wS7fCuYiiSuXUPLNQKpk7qndeZxKZZ","ALL-SOL","token_program"],["DmLWzsAtNNcWDY9ULaHGbTW2Zh9A5LHWuAF4S8iFeoxd","NEARKAT-SOL","token_program"],["CmcVVxuMMCdsevwThLwU4PdESB5NxiZJU4mGrxB6QDE4","GOOGLx-SOL","token_program"],["5Tgi4nWk5pTVXjkG8GdkqmMUZPz7udLZyaGB2wkRutUc","RUSH-SOL","mint_authority"],["GzaMLXLCkBn23qjbiMws1erULHXbWpJRAfjKy4C1BrbZ","INU-SOL","token_program"],["3Mt1bpU3fnSXyPEm66HKKXyQTpLWrwYziPLqwTqK4ZT7","ORE-SOL","mint_authority"],["FMhuUk4EDLBykp5S6gw14fMbvKsFoFVg5YuuSvMn3fWh","ORE-SOL","mint_authority"],["nBXytBBfKLhj6teXarAv8rk6WNgUFBMyybUFRkuK7ad","KNOTS-SOL","token_program"],["9wbGPPbHa78PeaCyTaDXUEGTJigzv6M6x4dUz2jQH6f","xp-SOL","token_program"],["FR64BDQb1JpNMB1WUsj5eDW5uPbYVk4dtQHFLRBxQvjf","BRRR-SOL","token_program"],["6NxcGCXFT1mYJMcr5uZuBEvLpqJ23Ntp6G3SJSDaMGRR","Buttcoin-SOL","token_program"],["fAeDy2q7ZjZZZFt6Q1FtbHaCU5dtLEPmYcwcwfAexNA","fone-SOL","token_program"],["qhJ7kLjrE68sbDF11CpwMt3P9rqiwZtretM5ZzeAX6o","CATE-SOL","token_program"],["5op83ibUpSRsLdvbbFGksmtFJnWzBQAVDj3NGDoeN71o","ALICE-SOL","token_program"],["b7eB5J3Mb8uA2G6fXe2BXuRsj9REqz9F6NTNDTpvRxy","MANIFEST-SOL","token_program"],["9Ub2zeRCZg7UnTwH6kL9w9bYPpf35CaiJHFhjenVQhMd","xSOL-SOL","mint_authority"]]
OUT=Path("solana-dlmm-support-census.json")

EXT_NAMES={
  0:"Uninitialized",1:"TransferFeeConfig",2:"TransferFeeAmount",
  3:"MintCloseAuthority",4:"ConfidentialTransferMint",5:"ConfidentialTransferAccount",
  6:"DefaultAccountState",7:"ImmutableOwner",8:"MemoTransfer",
  9:"NonTransferable",10:"InterestBearingConfig",11:"CpiGuard",
  12:"PermanentDelegate",13:"NonTransferableAccount",14:"TransferHook",
  15:"TransferHookAccount",16:"ConfidentialTransferFeeConfig",
  17:"ConfidentialTransferFeeAmount",18:"MetadataPointer",19:"TokenMetadata",
  20:"GroupPointer",21:"TokenGroup",22:"GroupMemberPointer",23:"TokenGroupMember",
  24:"ConfidentialMintBurn",25:"ScaledUiAmount",26:"Pausable",27:"PausableAccount"
}

def raw(account):
    if not account:return None
    return base64.b64decode(account["data"][0],validate=True)

def tlv(data,kind):
    if len(data)<=165:return []
    if data[165]!=kind:return [dict(error="unexpected_account_type",value=data[165])]
    out=[];offset=166
    while offset<len(data):
        if not any(data[offset:]):break
        if offset+4>len(data):
            out.append(dict(error="truncated_header"));break
        t,n=struct.unpack_from("<HH",data,offset);offset+=4
        if offset+n>len(data):
            out.append(dict(type=t,name=EXT_NAMES.get(t),size=n,error="truncated_value"));break
        out.append(dict(type=t,name=EXT_NAMES.get(t,"unknown"),size=n))
        offset+=n
    return out

def fetch_many(rpc,keys):
    out={}
    for i in range(0,len(keys),100):
        chunk=keys[i:i+100]
        res=rpc.call("getMultipleAccounts",[chunk,dict(encoding="base64",commitment="finalized")],True)
        vals=res.get("value") if isinstance(res,dict) else None
        if not isinstance(vals,list) or len(vals)!=len(chunk):
            raise RuntimeError("support_census_shape")
        out.update(zip(chunk,vals))
    return out

def pool_row(address,account):
    d=raw(account)
    if d is None or len(d)!=904 or d[:8]!=pump.discriminator("LbPair"):
        return dict(pool=address,error="pool_shape")
    vals=struct.unpack_from("<HHHHIIiiHBBB",d,8)
    return dict(
      pool=address,pair_type=d[75],activation_type=d[86],
      function_type=vals[-2],collect_fee_mode=vals[-1],
      token_x=pump.b58(d[88:120]),token_y=pump.b58(d[120:152]),
      vault_x=pump.b58(d[152:184]),vault_y=pump.b58(d[184:216]),
      token_x_program_flag=d[880],token_y_program_flag=d[881],
      reserved_nonzero=[i+882 for i,b in enumerate(d[882:904]) if b],
    )

def mint_row(key,account):
    d=raw(account);owner=None if not account else account.get("owner")
    if d is None:return dict(mint=key,missing=True)
    return dict(
      mint=key,owner=owner,length=len(d),
      initialized=(None if len(d)<=45 else bool(d[45])),
      decimals=(None if len(d)<=44 else d[44]),
      mint_authority_option=(None if len(d)<4 else int.from_bytes(d[:4],"little")),
      freeze_authority_option=(None if len(d)<50 else int.from_bytes(d[46:50],"little")),
      extensions=(tlv(d,1) if owner==pump.TOKEN_2022 else []),
    )

def vault_row(key,account):
    d=raw(account);owner=None if not account else account.get("owner")
    if d is None:return dict(vault=key,missing=True)
    return dict(
      vault=key,owner=owner,length=len(d),
      delegate_option=(None if len(d)<76 else int.from_bytes(d[72:76],"little")),
      state=(None if len(d)<=108 else d[108]),
      close_authority_option=(None if len(d)<133 else int.from_bytes(d[129:133],"little")),
      extensions=(tlv(d,2) if owner==pump.TOKEN_2022 else []),
    )

def main():
    pacer=provider.AlchemyPacer();rpc=provider.new_rpc(limit=240,pacer=pacer)
    pool_accounts=fetch_many(rpc,[x[0] for x in ROWS])
    pools=[]
    keys=[]
    meta={x[0]:(x[1],x[2]) for x in ROWS}
    for address in [x[0] for x in ROWS]:
        p=pool_row(address,pool_accounts.get(address))
        p["name"],p["prior_reason"]=meta[address]
        pools.append(p)
        for k in ("token_x","token_y","vault_x","vault_y"):
            if isinstance(p.get(k),str):keys.append(p[k])
    accounts=fetch_many(rpc,sorted(set(keys)))
    for p in pools:
        p["mints"]=[mint_row(p[k],accounts.get(p[k])) for k in ("token_x","token_y")]
        p["vaults"]=[vault_row(p[k],accounts.get(p[k])) for k in ("vault_x","vault_y")]
    summary=dict(
      pool_count=len(pools),
      flags=Counter((p.get("token_x_program_flag"),p.get("token_y_program_flag")) for p in pools),
      fee_modes=Counter((p.get("function_type"),p.get("collect_fee_mode")) for p in pools),
      mint_owners=Counter(m.get("owner") for p in pools for m in p["mints"]),
      mint_extensions=Counter(e.get("name") for p in pools for m in p["mints"] for e in m.get("extensions",[])),
      vault_extensions=Counter(e.get("name") for p in pools for v in p["vaults"] for e in v.get("extensions",[])),
      authority_shapes=Counter((m.get("mint_authority_option"),m.get("freeze_authority_option")) for p in pools for m in p["mints"]),
    )
    summary={
      k:({str(key):value for key,value in v.items()} if isinstance(v,Counter) else v)
      for k,v in summary.items()
    }
    report=dict(kind="solana_dlmm_support_census_v1",summary=summary,pools=pools,rpc=dict(calls=rpc.calls,http_requests=rpc.http_requests,failures=rpc.failures,retries=rpc.retries))
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(summary,sort_keys=True,default=str))

if __name__=="__main__":main()
