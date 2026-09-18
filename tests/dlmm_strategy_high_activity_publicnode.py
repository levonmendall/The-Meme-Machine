"""Retired DLMM PublicNode compatibility entrypoint.

DLMM provider authority is now Alchemy Solana Mainnet only. This historical module
is retained so old references fail explicitly instead of silently restoring a
PublicNode route.
"""
from meme_machine.provider import Unavailable


def main():
    raise Unavailable("dlmm_publicnode_route_retired_use_alchemy")


if __name__ == "__main__":
    main()
