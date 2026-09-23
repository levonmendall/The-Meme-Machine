"""Fail closed if the retired Solana provider can re-enter active runtime/config."""
from __future__ import annotations
import argparse
from pathlib import Path

ACTIVE_SUFFIXES={".py",".pyw",".yml",".yaml",".json",".toml",".ini",".cfg",".sh"}
SKIP_PARTS={".git","__pycache__",".pytest_cache",".mypy_cache",".ruff_cache"}
NEEDLE="on"+"finality"

def scan(root):
    root=Path(root)
    bad=[]
    if not root.exists():
        return bad
    paths=[root] if root.is_file() else root.rglob("*")
    for path in paths:
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.suffix.lower() not in ACTIVE_SUFFIXES:
            continue
        try:
            text=path.read_text(errors="strict")
        except (UnicodeDecodeError,OSError):
            continue
        if NEEDLE in text.lower():
            bad.append(str(path))
    return bad

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",action="append",required=True)
    args=p.parse_args()
    bad=sorted({x for root in args.root for x in scan(root)})
    if bad:
        raise SystemExit("retired_provider_reference:"+",".join(bad))
    print("no_retired_provider_references")

if __name__=="__main__":
    main()
