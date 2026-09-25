"""Offline checks against the *composed* provider factories; no live capability probes."""
import argparse,gzip,json,subprocess,sys
from pathlib import Path
from meme_machine.solana_provider_config import public_value
from certification.run import ROOT


def scan_public_artifacts(folder):
    checked=0
    for path in sorted(Path(folder).rglob('*')):
        if not path.is_file() or path.suffix not in ('.json','.jsonl','.log','.gz','.txt'):continue
        opener=gzip.open if path.suffix=='.gz' else open
        with opener(path,'rt',errors='replace') as stream:
            for line in stream:public_value(line)
        checked+=1
    print(json.dumps(dict(credential_scan_passed=True,files_checked=checked)))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worktrees',type=Path);parser.add_argument('--scan',type=Path);args=parser.parse_args()
    if args.scan:return scan_public_artifacts(args.scan)
    modules=('solana_provider_config','solana_evidence_plane','solana_evidence_transport',
             'solana_evidence_service','solana_evidence_runtime','durable_publication')
    for lane in ('pump','meteora'):
        cwd=args.worktrees/lane
        for name in modules:
            rel=Path('meme_machine')/(name+'.py')
            if (ROOT/rel).read_bytes()!=(cwd/rel).read_bytes():
                raise ValueError('shared_provider_module_drift:'+lane+':'+name)
        code='''
import os
from unittest.mock import patch
from meme_machine.solana_read_rpc import new_rpc,ReadOnlyFailoverRPC,Unavailable
endpoint='https://solana-mainnet.g.alchemy.com/v2/offline-fixture'
with patch.dict(os.environ,{'MM_SOLANA_EVIDENCE_PLANE_DB':'offline','MM_ONFINALITY_SOLANA_RPC_URL':'obsolete'},clear=True):
    try:new_rpc()
    except Unavailable:pass
    else:raise AssertionError('missing_canonical_endpoint_accepted')
    rpc=ReadOnlyFailoverRPC(endpoint)
    with patch.object(rpc,'_provider_attempt') as transport:
        for method in ('getSignaturesForAddress','getTransaction','getTransactionsForAddress','getBlock'):
            try:rpc._http({'method':method})
            except Unavailable:pass
            else:raise AssertionError('historical_foreground_transport_allowed')
        transport.assert_not_called()
        rpc._http({'method':'getMultipleAccounts'})
        assert transport.call_count==1
print('composed authority and historical foreground guards passed; provider calls zero')
'''
        subprocess.run([sys.executable,'-c',code],cwd=cwd,check=True)

if __name__=='__main__':main()
