"""Retained raw event parity; deliberately NOT a complete-decision parity claim."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.pump_acceleration_evidence import pumpswap_trade_events
from meme_machine.postgrad import PUMPSWAP_PROGRAM
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,FinalizedRecord,digest

FIXTURES=Path(__file__).parent/'fixtures/solana_evidence_plane'

class RetainedRawTests(unittest.TestCase):
    def replay(self,run):
        fixture=json.loads((FIXTURES/f'run-{run}-raw-pump.json').read_text())
        self.assertEqual(fixture['run'],run)
        with tempfile.TemporaryDirectory() as temp,patch('socket.socket.connect',side_effect=AssertionError('network_forbidden')):
            writer=EvidenceWriter(Path(temp)/'evidence.sqlite')
            expected={}
            for receipt in fixture['records']:
                request=receipt['request'];tx=receipt['response']['result']
                self.assertEqual(request['params'][1]['commitment'],'finalized')
                self.assertEqual(receipt['provider']['provider_kind'],'alchemy')
                events=pumpswap_trade_events(tx)
                self.assertEqual(events,receipt['events'])
                records=[]
                for event in events:
                    signature=request['params'][0];identity=f"pump:{event['slot']}:{signature}:{event['index']}"
                    payload=dict(event=event,raw_transaction=tx,physical_request_id=receipt['physical_request_id'])
                    records.append(FinalizedRecord(identity,'pump',event['slot'],signature,
                        PUMPSWAP_PROGRAM,(event['pool'],event['wallet']),event['market_time'],payload,
                        'alchemy_finalized_repair',receipt['provider']['endpoint_identity'],
                        receipt['observed_at_ns']/1e9,event_index=event['index']))
                    expected[identity]=payload
                writer.ingest(records)
            reader=EvidenceReader(writer.path)
            for identity,body,checksum in reader.db.execute('SELECT identity,body,hash FROM records'):
                value=json.loads(body)
                self.assertEqual(value['payload'],expected[identity]);self.assertEqual(digest(value),checksum)
                # Authenticated transaction samples cannot certify an interval census.
                self.assertFalse(reader.covered('pump',value['slot'],value['slot'],as_of=1e12))
            self.assertEqual(reader.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],len(expected))
            reader.close();writer.close()
    def test_run_367_raw_event_parity_without_invented_coverage(self):self.replay(367)
    def test_run_368_raw_event_parity_without_invented_coverage(self):self.replay(368)
