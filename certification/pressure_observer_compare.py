"""Controlled offline-only comparison of the pressure observer, never a certificate."""
import argparse
import asyncio
import json
from pathlib import Path
from unittest.mock import patch
from certification import run381_pressure


def legacy(db):
    return db.execute('SELECT MIN(COALESCE(market_time,first_seen)) FROM records').fetchone()[0]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--variant',choices=('legacy','indexed'),required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    observer=legacy if args.variant=='legacy' else run381_pressure.oldest_retained_time
    with patch.object(run381_pressure,'oldest_retained_time',observer):
        result=asyncio.run(run381_pressure.run(2223,args.output,measured_contention=True,diagnostics=True))
    path=Path(args.output)/'result.json'
    row=json.loads(path.read_text())
    row['phase_a_diagnostic_only']=True
    row['observer_variant']=args.variant
    row['diagnostic_revision']='stage-level-v2'
    path.write_text(json.dumps(row,sort_keys=True,indent=2)+'\n')
    return result


if __name__=='__main__':raise SystemExit(main())
