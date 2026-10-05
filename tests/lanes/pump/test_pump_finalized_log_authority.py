"""Captured finalized PumpSwap log authority parity and fail-closed fallback."""
import hashlib
import json
import unittest

from meme_machine.lanes.pump.pump_acceleration_evidence import pumpswap_trade_events
from meme_machine.lanes.pump.pump_acceleration_history import IncrementalPumpSwapHistory
from meme_machine.lanes.pump.solana_evidence_broker import EvidenceBroker

SIGNATURE="2E3Z6Z3vsiVgiGsUCQuZuKCpTYNPz4W2GBppF1Fnn2ndUtRJb9fWRWvVf9E3c58Hxr7hm9pqoiKdSGAtobHjv7NE"
POOL="CBGLkk9F86F9UzJwDD7njtgTeMmhy6Z3MdtnpBQxPiuQ"
SLOT=450070471
OBSERVED_AT=1790263985
BLOCK_TIME=1790263976
IMMUTABLE_TRANSACTION_SHA256="dd5bd6cc3a5b969a4a5b834daf027ac234897085eac0e2d16056786907467a67"
LOGS=[
    "Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA invoke [1]",
    "Program log: Instruction: Buy",
    "Program pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ invoke [2]",
    "Program log: Instruction: GetFeesWithQuoteMint",
    "Program pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ consumed 6079 of 216762 compute units",
    "Program return: pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ FAAAAAAAAAAFAAAAAAAAAFUAAAAAAAAA",
    "Program pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ success",
    "Program TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb invoke [2]",
    "Program log: Instruction: TransferChecked",
    "Program TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb consumed 2562 of 206844 compute units",
    "Program TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA consumed 112 of 201779 compute units",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA consumed 112 of 198907 compute units",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA consumed 112 of 194680 compute units",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke [2]",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA consumed 112 of 188651 compute units",
    "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA success",
    "Program data: Z/RSHyz1d3eoQrVqAAAAAO6adAgAAAAAzGUHAAAAAAAAAAAAAAAAAMxlBwAAAAAAKD9w8zRDAAB95VhiMwAAANz6BgAAAAAAFAAAAAAAAACTAwAAAAAAAAUAAAAAAAAA5QAAAAAAAABv/gYAAAAAAIUOBwAAAAAAphG1vqznPqG6YtdwLHpcqixcBpxVVfD8MYNRG7XdnOO33W0u7YDrYCYY2U2djqB6VOh0fDyABVVPviqAk1A2QZ8iz1rvHV/pdwyH8V8RIE3SjQ6z9HgnAi+jo5nVo1tidsMbqWiot9tAjSa3cnjysaZiV12UvfNCURquQSDTheaDhHQpLmdalLQ27LCpmIlCMoqD3cYjOAKWEmfFzWEXy6JjF6U7oP1oxMlT7DDw4JuOc2h1HLKBVIbK4+mdCvndCwBMJEFh1T8GDN/N1anVS/SHjJyzYqaOg5CqWLoQXtpVAAAAAAAAADEPAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA7pp0CAAAAAADAAAAYnV5AAAAAAAAAAAAAAAAAAAAAIgTAAAAAAAAcgAAAAAAAADIQR4YBAAAAAAAAAAAAAAAAee6gZnzjAMAAAAAAAAAAAAAAAAAAAAAAA==",
    "Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA invoke [2]",
    "Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA consumed 2098 of 180705 compute units",
    "Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA success",
    "Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA consumed 80632 of 256882 compute units",
    "Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA success",
]
EXPECTED=dict(
    pool=POOL,
    wallet="DNjSVAaqk16LmAAVKYRuddx31Bs6VRaVvrxKxZMmHZC4",
    amount=457436,
    tokens=141859566,
    buy=True,
    market_time=1790263976,
    pool_base_reserve=73894701580072,
    pool_quote_reserve=220693325181,
    user_quote_amount=462469,
    slot=SLOT,
)
CORE=tuple(EXPECTED)

class NoRpc:
    def call_many(self,*args,**kwargs):
        raise AssertionError("complete finalized trade log must not request transaction body")

class BodyRpc:
    def __init__(self): self.calls=0
    def call_many(self,method,params,*args,**kwargs):
        self.calls+=1
        assert method=="getTransaction"
        body=dict(slot=SLOT,blockTime=BLOCK_TIME,
                  meta=dict(err=None,logMessages=list(LOGS)))
        return [dict(body) for _ in params]

def body_events():
    return pumpswap_trade_events(dict(
        slot=SLOT,blockTime=BLOCK_TIME,
        meta=dict(err=None,logMessages=list(LOGS))))

def make_history(payload=None):
    broker=EvidenceBroker(":memory:",clock=lambda:OBSERVED_AT,sleeper=lambda _:None)
    key="pumpswap_pool:"+POOL
    broker.stream_begin(key,OBSERVED_AT-31)
    broker.record_event(
        key,signature=SIGNATURE,address=POOL,slot=SLOT,
        observed_at=OBSERVED_AT,
        payload=dict(err=None,logs=list(LOGS)) if payload is None else payload)
    return broker,IncrementalPumpSwapHistory(
        POOL,OBSERVED_AT-60,broker=broker,stream_key=key)

class FinalizedPumpSwapLogAuthorityTests(unittest.TestCase):
    def test_captured_finalized_log_matches_immutable_body_event_exactly(self):
        events=body_events()
        self.assertEqual(len(events),1)
        for key,value in EXPECTED.items():
            self.assertEqual(events[0][key],value)
        # Provenance: run 36020434038 smoke artifact 10819505196 retained the
        # same finalized logMessages under the pinned immutable transaction hash.
        self.assertEqual(len(IMMUTABLE_TRANSACTION_SHA256),64)

    def test_complete_finalized_target_trade_uses_no_body_hydration(self):
        broker,history=make_history();self.addCleanup(broker.close)
        history._ingest_stream_window(NoRpc(),OBSERVED_AT)
        self.assertIn(SIGNATURE,history.stream_authoritative_signatures)
        self.assertIn(SIGNATURE,history.processed)
        self.assertEqual(history.stream_pending_transactions,0)
        self.assertEqual(history.stream_authoritative_events,1)
        self.assertEqual(history.stream_hydrated_transactions,0)
        self.assertTrue(history.decision_window_status(OBSERVED_AT,30)["complete"])
        events=history.decision_rows(OBSERVED_AT,30)
        self.assertEqual(len(events),1)
        for key,value in EXPECTED.items():
            self.assertEqual(events[0][key],value)
        self.assertEqual(events[0]["evidence_source"],"finalized_pumpswap_program_log")
        self.assertEqual(events[0]["evidence_signature"],SIGNATURE)
        self.assertEqual(len(events[0]["evidence_payload_sha256"]),64)

    def test_truncated_log_falls_back_to_immutable_transaction_body(self):
        payload=dict(err=None,logs=list(LOGS)+["Log truncated"])
        broker,history=make_history(payload);self.addCleanup(broker.close)
        rpc=BodyRpc();history._ingest_stream_window(rpc,OBSERVED_AT)
        self.assertEqual(rpc.calls,1)
        self.assertNotIn(SIGNATURE,history.stream_authoritative_signatures)
        self.assertIn(SIGNATURE,history.processed)
        self.assertGreaterEqual(history.stream_authority_fallbacks,1)
        self.assertEqual(len(history.decision_rows(OBSERVED_AT,30)),1)

    def test_stream_gap_still_blocks_window_even_with_authoritative_log_event(self):
        broker,history=make_history();self.addCleanup(broker.close)
        history._ingest_stream_window(NoRpc(),OBSERVED_AT)
        broker.stream_gap("pumpswap_pool:"+POOL,OBSERVED_AT)
        self.assertFalse(history.decision_window_status(OBSERVED_AT,30)["complete"])

    def test_unknown_pumpswap_program_data_falls_back_instead_of_becoming_negative(self):
        logs=list(LOGS)
        index=next(i for i,row in enumerate(logs) if row.startswith("Program data: "))
        logs[index]="Program data: AAAAAAAA"
        broker,history=make_history(dict(err=None,logs=logs));self.addCleanup(broker.close)
        rpc=BodyRpc();history._ingest_stream_window(rpc,OBSERVED_AT)
        self.assertEqual(rpc.calls,1)
        self.assertGreaterEqual(history.stream_authority_fallbacks,1)

if __name__=="__main__":
    unittest.main()
