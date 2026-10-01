"""Verify that synthetic source clocks change no non-clock economic or lineage bytes."""
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    from tests.evidence_fixture_clock import event_clock_offset, rebase_event_clocks
    from tests.test_run380_production_pressure import Wire
    from meme_machine.solana_program_decoders import pump_events, pumpswap_trade_events
    wire = Wire()
    at = 1790860000
    before = json.loads(wire.template)
    after = json.loads(rebase_event_clocks(wire.template, wire.event_clocks, at))
    expected = deepcopy(before)
    transactions = expected['params']['result']['value']['block']['transactions']
    original = before['params']['result']['value']['block']['transactions']
    changed_logs = events = 0
    for old_tx, tx in zip(original, transactions):
        logs = tx['meta'].get('logMessages') or []
        for index, line in enumerate(logs):
            if not line.startswith('Program data: '):
                continue
            raw = base64.b64decode(line[14:], validate=True)
            offset = event_clock_offset(raw)
            if offset is None:
                continue
            translated = raw[:offset] + struct.pack('<q', at) + raw[offset+8:]
            assert translated[:offset] == raw[:offset]
            assert translated[offset+8:] == raw[offset+8:]
            logs[index] = 'Program data: ' + base64.b64encode(translated).decode()
            changed_logs += 1
    assert after == expected, 'fixture_non_clock_bytes_changed'
    for old_tx, new_tx in zip(original, after['params']['result']['value']['block']['transactions']):
        old_tx = dict(old_tx, slot=1000)
        new_tx = dict(new_tx, slot=1000)
        old_events = pump_events(old_tx) + pumpswap_trade_events(old_tx)
        new_events = pump_events(new_tx) + pumpswap_trade_events(new_tx)
        assert new_events == [dict(event, market_time=at) for event in old_events], 'fixture_economic_decoder_parity'
        events += len(old_events)
    assert events > 0
    fixture = ROOT/'certification/tests/fixtures/run380-production-templates.json.gz'
    result = {
        'transactions': len(original), 'translated_log_timestamps': changed_logs,
        'decoded_events': events, 'all_other_bytes_unchanged': True,
        'native_decoder_economic_parity': True,
        'retained_gzip_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
        'fixed_frame_cadence': .27, 'frames': wire.frames,
        'clock_assigned_before_receive_backpressure': True,
    }
    Path(os.environ['LANE_C_EVIDENCE'], 'fixture-clock-probe.json').write_text(json.dumps(result, indent=2)+'\n')
    print('LANE_C_FIXTURE_CLOCK_PROBE '+json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
