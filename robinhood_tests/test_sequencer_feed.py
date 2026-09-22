import json
import unittest
import zlib

from robinhood_research import BoundaryError
from robinhood_research.sequencer_feed import SequencerBlockClock,SequencerFeedState,SequencerTransportError,_WebSocket,feed_url


def row(sequence,*,block=100,timestamp=1000,payload="AA==",signed=True):
    return dict(
        sequenceNumber=sequence,
        message=dict(message=dict(
            header=dict(kind=3,sender="0x0",blockNumber=block,timestamp=timestamp),
            l2Msg=payload,
        )),
        **({"signatureV2":"0x1234"} if signed else {}),
    )


class SequencerFeedTests(unittest.TestCase):
    def test_official_feed_default_and_wss_guard(self):
        self.assertEqual(
            feed_url({}),
            "wss://feed.mainnet.chain.robinhood.com",
        )
        with self.assertRaisesRegex(BoundaryError,"requires_wss"):
            feed_url({"MM_ROBINHOOD_SEQUENCER_FEED_URL":"https://example.invalid"})

    def test_contiguous_signed_messages_are_observation_only(self):
        state=SequencerFeedState()
        envelope=dict(version=1,messages=[
            row(10,block=20,timestamp=900),
            row(11,block=21,timestamp=901),
        ])
        self.assertEqual(state.ingest(envelope,received_at=902),2)
        summary=state.summary(now=903)
        self.assertEqual(summary["authority"],"observation_only")
        self.assertEqual(summary["messages"],2)
        self.assertEqual(summary["signed_messages"],2)
        self.assertEqual(summary["first_sequence"],10)
        self.assertEqual(summary["last_sequence"],11)
        self.assertEqual(summary["gap_events"],0)
        self.assertEqual(summary["latest_header_block_number"],21)
        self.assertEqual(summary["feed_message_age_seconds"],2)

    def test_gap_duplicate_conflict_and_regression_are_visible(self):
        state=SequencerFeedState()
        a=row(100,payload="AA==")
        state.ingest(dict(version=1,messages=[a]),received_at=1000)
        state.ingest(dict(version=1,messages=[row(102,payload="BB==")]),received_at=1001)
        state.ingest(dict(version=1,messages=[row(102,payload="BB==")]),received_at=1002)
        state.ingest(dict(version=1,messages=[row(102,payload="CC==")]),received_at=1003)
        state.ingest(dict(version=1,messages=[row(99,payload="DD==")]),received_at=1004)
        summary=state.summary(now=1005)
        self.assertEqual(summary["gap_events"],1)
        self.assertEqual(summary["missing_sequences"],1)
        self.assertEqual(summary["duplicates"],1)
        self.assertEqual(summary["conflicts"],1)
        self.assertEqual(summary["regressions"],1)

    def test_permessage_deflate_payload_decodes(self):
        raw=json.dumps(dict(version=1,messages=[row(7)])).encode()
        compressor=zlib.compressobj(wbits=-15)
        encoded=compressor.compress(raw)+compressor.flush(zlib.Z_SYNC_FLUSH)
        self.assertTrue(encoded.endswith(b"\x00\x00\xff\xff"))
        wire=encoded[:-4]
        ws=_WebSocket("wss://feed.mainnet.chain.robinhood.com")
        ws.permessage_deflate=True
        ws._inflater=zlib.decompressobj(wbits=-15)
        decoded=ws._inflate_message(wire)
        self.assertEqual(decoded,raw)

    def test_reserved_bits_frame_is_rejected_before_payload_use(self):
        class Socket:
            def __init__(self,raw):
                self.raw=bytearray(raw)
            def recv(self,size):
                out=bytes(self.raw[:size]);del self.raw[:size];return out
        ws=_WebSocket("wss://feed.mainnet.chain.robinhood.com")
        ws.sock=Socket(bytes([0xA1,0x00]))  # FIN + RSV2 + text, empty payload
        with self.assertRaisesRegex(BoundaryError,"reserved_bits"):
            ws.recv_message()

    def test_reserved_bits_closes_session_and_requires_rpc_backfill_recovery(self):
        class Socket:
            def settimeout(self,_):pass
        class Client:
            def __init__(self):
                self.sock=Socket();self.closed=False
            def recv_message(self):
                raise BoundaryError("sequencer_feed_reserved_bits")
            def close(self):
                self.closed=True
        clock=SequencerBlockClock()
        client=Client();clock.client=client;clock.state.last_sequence=100
        with self.assertRaisesRegex(SequencerTransportError,"reserved_bits"):
            clock.wait_for_after(100,timeout=0.1)
        self.assertTrue(client.closed)
        self.assertIsNone(clock.client)
        self.assertEqual(clock.last_transport_boundary,"sequencer_feed_reserved_bits")
        self.assertEqual(clock.transport_failures,1)
        self.assertEqual(clock.state.last_sequence,100)

    def test_startup_sentinel_anchors_to_current_sequence_before_range_cap(self):
        clock=SequencerBlockClock()
        clock.state.last_sequence=67_198_059
        clock.connect=lambda: clock
        self.assertEqual(
            clock.wait_for_range_after(
                -1,timeout=1.0,max_blocks=10,coalesce_seconds=0.75
            ),
            67_198_059,
        )
        self.assertEqual(
            clock.wait_for_range_after(
                67_198_050,timeout=1.0,max_blocks=5,coalesce_seconds=0.75
            ),
            67_198_055,
        )

    def test_discovery_clock_fails_closed_on_gap(self):
        clock=SequencerBlockClock()
        clock.state.last_sequence=100
        clock.state.gap_events=1
        with self.assertRaisesRegex(BoundaryError,"continuity_lost"):
            clock._healthy()

    def test_discovery_clock_status_has_no_evidence_authority(self):
        clock=SequencerBlockClock()
        clock.state.ingest(dict(version=1,messages=[row(10)]),received_at=1001)
        status=clock.status()
        self.assertEqual(status["role"],"pons_discovery_clock")
        self.assertEqual(status["authority"],"observation_only")
        self.assertFalse(status["canonical_evidence"])

    def test_informational_envelope_is_not_a_continuity_failure(self):
        state=SequencerFeedState()
        self.assertEqual(state.ingest({"version":1,"status":"connected"}),0)
        summary=state.summary(now=1)
        self.assertEqual(summary["messages"],0)
        self.assertEqual(summary["malformed"],0)
        self.assertEqual(summary["non_message_envelopes"],1)

    def test_malformed_feed_frame_is_counted_not_promoted(self):
        state=SequencerFeedState()
        self.assertEqual(state.ingest("not-json"),0)
        summary=state.summary(now=1)
        self.assertEqual(summary["messages"],0)
        self.assertEqual(summary["malformed"],1)
        self.assertEqual(summary["non_message_envelopes"],0)


if __name__=="__main__":
    unittest.main()