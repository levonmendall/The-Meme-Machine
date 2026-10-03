"""Future execution CLI. A preview declaration is rejected before any spawn."""
import argparse
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent/'harness'))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--class', dest='kind', choices=('A','B','C'), required=True)
    p.add_argument('--declaration', required=True)
    p.add_argument('--owner-permit', required=True)
    p.add_argument('--owner-public-key', required=True)
    args = p.parse_args()
    from run import execute
    execute(args.declaration, args.owner_permit, args.owner_public_key, kind=args.kind)


if __name__ == '__main__':
    main()
