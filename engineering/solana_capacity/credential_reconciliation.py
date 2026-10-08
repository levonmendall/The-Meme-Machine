"""Read-only, secret-free reconciliation with the owner's verified app IDs.

Only the specified Pump/Pons environment fields are read. Never emit a key,
URL path, masked suffix or raw exception. No provider or administration API call.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit

APP_IDS = {'pump': '9bin99s96t7ga5e9', 'pons': 'v5h0vqr0wpp9zscj'}
VARIABLES = {'pump': 'MM_SOLANA_READ_RPC_URL', 'pons': 'MM_ROBINHOOD_READ_RPC_URL'}
HOSTS = {'pump': 'solana-mainnet.g.alchemy.com', 'pons': 'robinhood-mainnet.g.alchemy.com'}


def reconcile(path, suffixes=None):
    suffixes = suffixes or {}
    allowed = {*VARIABLES.values(), 'MM_SOLANA_YELLOWSTONE_TOKEN'}
    values = {}
    for line in Path(path).read_text().splitlines():
        if '=' not in line or line.lstrip().startswith('#'):
            continue
        key, value = line.removeprefix('export ').split('=', 1)
        if key in allowed:
            parsed = shlex.split(value, comments=True)
            if parsed:
                values[key] = parsed[0]
    roles, keys = {}, {}
    for role, variable in VARIABLES.items():
        raw = values.get(variable, '')
        parsed = urlsplit(raw)
        key = parsed.path.removeprefix('/v2/') if parsed.path.startswith('/v2/') else ''
        shape = bool(parsed.scheme=='https' and parsed.netloc in (HOSTS[role], HOSTS[role]+':443') and
                     re.fullmatch('[A-Za-z0-9_-]{8,128}', key) and
                     not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)
        keys[role] = key
        suffix = suffixes.get(APP_IDS[role])
        if suffix is not None and (not isinstance(suffix, str) or len(suffix)!=4):
            raise ValueError('four_character_admin_suffix_required')
        roles[role] = dict(app_id=APP_IDS[role], app_id_source='OWNER_VERIFIED_ADMINISTRATIVE_UPDATE',
                           variable=variable, endpoint_role_matches=shape,
                           endpoint_identity_sha256=hashlib.sha256(('https://'+HOSTS[role]+parsed.path).encode()).hexdigest() if shape else None,
                           credential_configured=bool(key),
                           admin_suffix_match=(bool(shape and key.endswith(suffix)) if suffix is not None else None),
                           app_binding=('INVALID_ENDPOINT_ROLE' if not shape else 'MASKED_SUFFIX_MATCH' if suffix is not None and key.endswith(suffix)
                                        else 'MASKED_SUFFIX_MISMATCH' if suffix is not None
                                        else 'AWAITING_ADMIN_MASK_COMPARISON'))
    native = values.get('MM_SOLANA_YELLOWSTONE_TOKEN') or keys['pump']
    return dict(schema='alchemy-droplet-credential-reconciliation-v1', roles=roles,
                native_pump_token_matches_configured_pump_key=bool(native and native==keys['pump']),
                pump_and_pons_keys_distinct=bool(keys['pump'] and keys['pons'] and keys['pump']!=keys['pons']),
                raw_secrets_published=False, credential_changes=0, market_provider_calls=0,
                limitation='A masked-suffix match is an administrative association, not disclosure or cryptographic verification of a full remote key.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--admin-suffixes', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        suffixes = json.loads(args.admin_suffixes.read_text()) if args.admin_suffixes else None
        result = reconcile(args.env_file, suffixes)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        # Parsing/URL exceptions can include a credential. Only a fixed reason.
        print(json.dumps(dict(error='credential_reconciliation_unavailable', secrets_printed=False)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
