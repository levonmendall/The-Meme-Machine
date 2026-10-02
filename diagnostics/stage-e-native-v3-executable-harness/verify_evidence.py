"""Read-only future raw-evidence verifier. Cannot launch A, B or C."""
import argparse
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'harness'))
from core import canonical
from campaign import verify_campaign


def main():
    p=argparse.ArgumentParser();p.add_argument('--campaign',required=True)
    p.add_argument('--owner-public-key',required=True);p.add_argument('--allocation-public-key',required=True)
    p.add_argument('--preservation-receipt')
    args=p.parse_args()
    print(canonical(verify_campaign(args.campaign,args.owner_public_key,args.allocation_public_key,
                                  preservation_receipt=args.preservation_receipt)).decode())


if __name__=='__main__':main()
