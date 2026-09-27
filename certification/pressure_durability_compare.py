"""Offline causal probe of measured durable owner latency; never a certificate.

The failed full certificate spent 37.84 ms per health publication. Each
publication performs six changed outer commits; the paired fast runner spent
2.82 ms. An additional 6 ms per changed commit models that observed difference.
No source frame, archive floor, acceptance bound or production source is changed.
"""
import argparse
import asyncio
from contextlib import nullcontext
import json
from pathlib import Path
from unittest.mock import patch

from certification import run381_pressure
from certification.pressure_diagnostics import SQLTimings
from meme_machine import solana_evidence_service as service

COMMIT_DELAY_SECONDS = .006


def batched_health(original):
    def publish(state, *args):
        with state.writer.transaction():
            return original(state, *args)
    return publish


def legacy_health(state, http, ipc, scheduler):
    # Exact pre-repair publication boundary, for offline counterfactual only.
    state.maintenance_health(http)
    with state.writer.transaction():
        state.fence.health('ipc', ipc)
        state.fence.health('owner_scheduler', scheduler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--variant', choices=('legacy', 'repaired'), required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    original_init = service.ServiceState.__init__
    def legacy_init(state, *args, **kwargs):
        original_init(state, *args, **kwargs)
        state.writer.db.execute('PRAGMA wal_autocheckpoint=1000')
        state.writer.db.execute('PRAGMA cache_size=-2000')
        state.writer.db.execute('PRAGMA temp_store=FILE')
    checkpoint = (patch.object(service.ServiceState, '__init__', legacy_init)
                  if args.variant == 'legacy' else nullcontext())
    publication = (patch.object(service.ServiceState, 'publish_health', legacy_health)
                   if args.variant == 'legacy' else nullcontext())
    timings = SQLTimings(commit_latency_seconds=COMMIT_DELAY_SECONDS)
    with checkpoint, publication, patch.object(run381_pressure, 'SQLTimings', return_value=timings):
        result = asyncio.run(run381_pressure.run(2223, args.output,
            measured_contention=True, diagnostics=True))
    path = Path(args.output) / 'result.json'
    row = json.loads(path.read_text())
    row.update(phase_a_diagnostic_only=True, health_variant=args.variant,
               additional_commit_latency_seconds=COMMIT_DELAY_SECONDS)
    path.write_text(json.dumps(row, sort_keys=True, indent=2) + '\n')
    return result


if __name__ == '__main__':
    raise SystemExit(main())
