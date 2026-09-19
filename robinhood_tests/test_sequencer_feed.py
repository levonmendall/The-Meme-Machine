import json
import unittest
import zlib

from robinhood_research import BoundaryError
from robinhood_research.sequencer_feed import SequencerFeedState,_WebSocket,feed_url


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

    def test_malformed_feed_frame_is_counted_not_promoted(self):
        state=SequencerFeedState()
        self.assertEqual(state.ingest("not-json"),0)
        self.assertEqual(state.ingest({"version":1}),0)
        summary=state.summary(now=1)
        self.assertEqual(summary["messages"],0)
        self.assertEqual(summary["malformed"],2)


if __name__=="__main__":
    unittest.main()