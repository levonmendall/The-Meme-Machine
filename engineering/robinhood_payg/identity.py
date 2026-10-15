"""Read-only app/credential reconciliation. No network and no secret output.

Optional administrative metadata must be an owner-protected local JSON file,
never a checked-in artifact. Masked suffix agreement is explicitly weaker than
a whole-key comparison. App IDs alone do not identify an RPC credential.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
from urllib.parse import urlsplit

APPS={'pons':('v5h0vqr0wpp9zscj','MM_ROBINHOOD_READ_RPC_URL','robinhood-mainnet.g.alchemy.com'),
      'pump':('9bin99s96t7ga5e9','MM_SOLANA_READ_RPC_URL','solana-mainnet.g.alchemy.com')}


def protected(path):
    path=Path(path)
    if path.stat().st_mode&0o077:raise ValueError('protected_file_permissions_required')
    return path.read_text()


def reconcile(env_text,metadata=None):
    env={}
    for line in env_text.splitlines():
        if '=' in line and line.strip() and not line.lstrip().startswith('#'):
            name,value=line.split('=',1);env[name.strip()]=' '.join(shlex.split(value))
    rows=[]
    for family,(app_id,name,host) in APPS.items():
        endpoint=env.get(name,'');p=urlsplit(endpoint);parts=p.path.split('/')
        valid=p.scheme=='https' and p.hostname==host and not any((p.username,p.password,p.query,p.fragment)) \
            and len(parts)==3 and parts[1]=='v2' and bool(parts[2])
        app=(metadata or {}).get(app_id,{})
        key=app.get('masked_api_key',app.get('api_key',app.get('apiKey')))
        agreement=None;basis='not_available_in_this_session'
        if valid and isinstance(key,str) and key:
            if '*' in key:
                suffix=key.rsplit('*',1)[-1]
                if len(suffix)>=4:
                    agreement=parts[2].endswith(suffix);basis='masked_suffix_only'
            else:agreement=parts[2]==key;basis='whole_key_comparison'
        from meme_machine.runtime.robinhood.provider_authority import fingerprint
        rows.append(dict(family=family,app_id=app_id,configuration_valid=bool(valid),
            endpoint_fingerprint=(fingerprint(endpoint) if family=='pons' else
                                  hashlib.sha256(endpoint.encode()).hexdigest()) if valid else None,
            administrative_key_agreement=agreement,comparison_basis=basis,
            owner_confirmed_binding=True,owner_confirmed_payg=True,credential_changed=False))
    return dict(schema='alchemy-app-credential-reconciliation-v1',applications=rows,
        secret_fields_emitted=False,provider_requests=0,
        limitation='owner-confirmed app binding; masked suffix comparison is diagnostic, not whole-key identity')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--app-metadata',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    metadata=json.loads(protected(args.app_metadata)) if args.app_metadata else None
    row=reconcile(protected(args.env_file),metadata)
    raw=json.dumps(row,indent=2)+'\n'
    if args.output:args.output.write_text(raw)
    else:print(raw,end='')
    return 0 if all(r['configuration_valid'] and r['administrative_key_agreement'] is not False
                    for r in row['applications']) else 2


if __name__=='__main__':raise SystemExit(main())
