"""Offline wire/lifecycle faults. No production adapter or runtime integration."""
import asyncio
import base64
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational.bounded_provider import Budget, MAX_FRAME
from meme_machine.operational.transport_bridge import (
    BridgeRejected, Delivered, EndpointAlias, MAX_BODY, MAX_REQUEST, Session,
    decode_request, encode_frame, read_request_frame,
)


def reply(frame):
    size, = struct.unpack('!I', frame[:4])
    assert size == len(frame) - 4
    return json.loads(frame[4:])


class Adapter:
    """Trusted parent fixture: real, single Budget; entirely fake physical I/O."""
    def __init__(self, budget):
        self.budget = budget
        self.receipts = {}
        self.calls, self.releases = [], []
        self.entered = asyncio.Event()
        self.gate = asyncio.Event()
        self.gate.set()
        self.cleanup_entered = asyncio.Event()
        self.cleanup_gate = asyncio.Event()
        self.cleanup_gate.set()
        self.failure = None
        self.cleanup_failure = None
        self.payload = b'{"result":42}'
        self.eof = True
        # Fake identity exists only in the trusted fixture; never on the wire.
        self.endpoint = 'https://solana-mainnet.g.alchemy.com/v2/parent-secret'

    async def execute(self, attempt):
        calls = [dict(method=c.method, params=json.loads(c.params_json))
                 for c in attempt.calls]
        endpoint = self.endpoint if attempt.endpoint.family == 'solana' else (
            'https://robinhood-mainnet.g.alchemy.com/v2/parent-secret')
        receipt = self.budget.reserve_http(endpoint, calls)
        self.receipts[attempt.token] = receipt
        self.calls.append(attempt)
        self.entered.set()
        # A persisted reservation exists before even this fake physical boundary.
        state = Budget(self.budget.path).snapshot()
        assert int(state['http_attempts']) == len(self.calls)
        assert int(state['http_reserved']) >= MAX_FRAME
        await self.gate.wait()
        if self.failure:
            raise self.failure
        receipt.http_delivery(len(self.payload))
        receipt.eof = self.eof
        return Delivered(self.payload, self.eof)

    async def release(self, attempt, *, uncertain):
        self.cleanup_entered.set()
        await self.cleanup_gate.wait()
        self.releases.append((attempt.token, uncertain))
        if self.cleanup_failure:
            raise self.cleanup_failure
        receipt = self.receipts.pop(attempt.token, None)
        if receipt:
            # eof belongs to the physical transport, never child acknowledgements.
            assert uncertain is not receipt.eof
            receipt.close()


class TransportBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.budget = Budget.create(Path(self.tmp.name) / 'usage.sqlite', modeled_spend_limit='3')
        self.adapter = Adapter(self.budget)
        methods = {'getSlot', 'getBlockTime'}
        self.alias = EndpointAlias('pump', 'solana', methods)
        methods.add('sendTransaction')
        self.assertNotIn('sendTransaction', self.alias.methods)
        self.session = Session([self.alias], self.adapter)
        async def cleanup():
            await self.session.aclose()
        self.addAsyncCleanup(cleanup)
        self.seq = 0

    def message(self, verb, **fields):
        self.seq += 1
        return dict(session=self.session.session_id, seq=self.seq, verb=verb, **fields)

    def begin(self, **changes):
        message = self.message('begin', alias='pump', batch=False,
                               calls=[dict(method='getSlot', params=[])])
        message.update(changes)
        return message

    def dispatch(self, message):
        return reply(self.session.dispatch(encode_frame(message)))

    async def terminal(self, token):
        # Small bounded yields, never a provider call or throughput benchmark.
        for _ in range(100):
            value = self.dispatch(self.message('poll', token=token))
            if value['status'] != 'running':
                return value
            await asyncio.sleep(.001)
        self.fail('offline adapter did not terminate')

    async def test_batch_is_one_attempt_and_bytes_durable_before_handoff(self):
        message = self.begin(batch=True, calls=[dict(method='getSlot', params=[]),
            dict(method='getBlockTime', params=[123])])
        accepted = self.dispatch(message)
        value = await self.terminal(accepted['token'])
        self.assertEqual(value['status'], 'delivered')
        self.assertEqual(base64.b64decode(value['body_b64']), self.adapter.payload)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertTrue(self.adapter.calls[0].batch)
        self.assertEqual(len(self.adapter.calls[0].calls), 2)
        state = Budget(self.budget.path).snapshot()
        self.assertEqual(state['http_attempts'], '1')
        self.assertEqual(state['rpc_elements'], '2')
        self.assertEqual(state['http_bytes'], str(len(self.adapter.payload)))
        self.assertEqual(state['http_reserved'], '0')
        self.assertEqual(state['http_uncertain_bytes'], '0')
        self.assertNotIn('parent-secret', json.dumps(value))
        self.assertNotIn('endpoint', json.dumps(accepted))
        self.assertEqual(self.adapter.releases, [(accepted['token'], False)])

    async def test_exact_replay_never_repeats_physical_attempt_or_extends_deadline(self):
        message = self.begin()
        frame = encode_frame(message)
        first = self.session.dispatch(frame)
        value = await self.terminal(reply(first)['token'])
        self.assertEqual(value['status'], 'delivered')
        deadline = self.adapter.calls[0].deadline
        self.assertEqual(self.session.dispatch(frame), first)
        await asyncio.sleep(0)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(self.adapter.calls[0].deadline, deadline)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '1')

    async def test_altered_duplicate_closes_and_cleans_uncertain_receipt(self):
        self.adapter.gate.clear()
        message = self.begin()
        self.dispatch(message)
        await self.adapter.entered.wait()
        message['calls'][0]['method'] = 'getBlockTime'
        with self.assertRaisesRegex(BridgeRejected, 'altered_replay'):
            self.dispatch(message)
        await self.session.aclose()
        state = self.budget.snapshot()
        self.assertEqual(state['http_attempts'], '1')
        self.assertEqual(state['http_reserved'], '0')
        self.assertEqual(state['http_uncertain_bytes'], str(MAX_FRAME))

    async def test_exponent_overflow_rejects_and_cleans_actual_inflight_attempt(self):
        self.adapter.gate.clear()
        token = self.dispatch(self.begin())['token']
        await self.adapter.entered.wait()
        message = self.begin(calls=[dict(method='getSlot', params=['EXPONENT'])])
        raw = json.dumps(message).replace('"EXPONENT"', '1e999').encode('ascii')
        with self.assertRaisesRegex(BridgeRejected, '^invalid_json$'):
            self.session.dispatch(struct.pack('!I', len(raw)) + raw)
        self.assertTrue(self.session.closed)
        await self.session.aclose()
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(self.adapter.releases, [(token, True)])
        self.assertEqual(self.session._states[token].status, 'canceled')
        self.assertIsNone(self.session._states[token].body)
        state = Budget(self.budget.path).snapshot()
        self.assertEqual(state['http_attempts'], '1')
        self.assertEqual(state['http_bytes'], '0')
        self.assertEqual(state['http_reserved'], '0')
        self.assertEqual(state['http_uncertain_bytes'], str(MAX_FRAME))

    async def test_cancel_before_execution_still_runs_cleanup_without_reserving(self):
        token = self.dispatch(self.begin())['token']
        self.dispatch(self.message('cancel', token=token))
        value = await self.terminal(token)
        self.assertEqual(value['status'], 'canceled')
        self.assertNotIn('body_b64', value)
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(self.adapter.releases, [(token, True)])
        self.assertEqual(self.budget.snapshot()['http_attempts'], '0')

    async def test_cancel_and_eof_preserve_spent_request_no_replacement_allowance(self):
        self.adapter.gate.clear()
        token = self.dispatch(self.begin())['token']
        await self.adapter.entered.wait()
        self.dispatch(self.message('cancel', token=token))
        self.dispatch(self.message('cancel', token=token))
        await self.session.aclose()
        self.assertEqual(len(self.adapter.releases), 1)
        self.assertEqual(self.budget.snapshot()['http_uncertain_bytes'], str(MAX_FRAME))
        with self.assertRaises(BridgeRejected):
            self.dispatch(self.begin())

    async def test_delivery_not_pollable_until_cleanup_commits(self):
        self.adapter.cleanup_gate.clear()
        token = self.dispatch(self.begin())['token']
        await self.adapter.cleanup_entered.wait()
        value = self.dispatch(self.message('poll', token=token))
        self.assertEqual(value['status'], 'running')
        self.assertNotIn('body_b64', value)
        self.adapter.cleanup_gate.set()
        self.assertEqual((await self.terminal(token))['status'], 'delivered')

    async def test_cancel_during_accepted_cleanup_waits_and_hides_content(self):
        self.adapter.cleanup_gate.clear()
        token = self.dispatch(self.begin())['token']
        await self.adapter.cleanup_entered.wait()
        self.dispatch(self.message('cancel', token=token))
        close = asyncio.create_task(self.session.aclose())
        await asyncio.sleep(0)
        self.assertFalse(close.done())
        self.adapter.cleanup_gate.set()
        await close
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')
        self.assertEqual(self.budget.snapshot()['http_bytes'], str(len(self.adapter.payload)))
        self.assertEqual(self.session._states[token].status, 'canceled')
        self.assertIsNone(self.session._states[token].body)

    async def test_canceling_parent_close_does_not_abandon_cleanup(self):
        self.adapter.cleanup_gate.clear()
        self.dispatch(self.begin())
        await self.adapter.cleanup_entered.wait()
        close = asyncio.create_task(self.session.aclose())
        await asyncio.sleep(0)
        close.cancel()
        await asyncio.sleep(0)
        self.assertFalse(close.done())
        self.adapter.cleanup_gate.set()
        with self.assertRaises(asyncio.CancelledError):
            await close
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')

    async def test_original_deadline_expires_waiting_attempt(self):
        await self.session.aclose()
        self.session = Session([self.alias], self.adapter, attempt_seconds=.01)
        self.adapter.gate.clear()
        token = self.dispatch(self.begin())['token']
        value = await self.terminal(token)
        self.assertEqual(value['status'], 'expired')
        self.assertEqual(self.budget.snapshot()['http_uncertain_bytes'], str(MAX_FRAME))

    async def test_cleanup_after_deadline_preserves_charge_but_cannot_release_content(self):
        await self.session.aclose()
        self.session = Session([self.alias], self.adapter, attempt_seconds=.01)
        self.adapter.cleanup_gate.clear()
        token = self.dispatch(self.begin())['token']
        await self.adapter.cleanup_entered.wait()
        await asyncio.sleep(.02)
        self.adapter.cleanup_gate.set()
        value = await self.terminal(token)
        self.assertEqual(value['status'], 'expired')
        self.assertNotIn('body_b64', value)
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')
        self.assertEqual(self.budget.snapshot()['http_bytes'], str(len(self.adapter.payload)))

    async def test_parallel_aliases_do_not_serialize_on_waiting_transport(self):
        await self.session.aclose()
        pons = EndpointAlias('pons', 'robinhood', frozenset(('eth_chainId',)))
        self.session = Session([self.alias, pons], self.adapter)
        self.adapter.gate.clear()
        self.dispatch(self.begin())
        await self.adapter.entered.wait()
        self.dispatch(self.begin(alias='pons', calls=[dict(method='eth_chainId', params=[])]))
        for _ in range(10):
            if len(self.adapter.calls) == 2:
                break
            await asyncio.sleep(0)
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertIs(self.adapter.budget, self.budget)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '2')
        self.assertEqual({a.endpoint.family for a in self.adapter.calls}, {'solana', 'robinhood'})

    async def test_durable_delivery_write_fault_never_exposes_bytes(self):
        with self.budget.db() as db:
            db.execute("CREATE TRIGGER reject_bytes BEFORE UPDATE OF value ON run "
                "WHEN NEW.key='http_bytes' AND NEW.value!='0' "
                "BEGIN SELECT RAISE(ABORT,'offline durable-write fault'); END")
        token = self.dispatch(self.begin())['token']
        await self.adapter.entered.wait()
        for _ in range(20):
            if self.session.closed:
                break
            await asyncio.sleep(0)
        self.assertTrue(self.session.closed)
        self.assertIsNone(self.session._states[token].body)
        state = Budget(self.budget.path).snapshot()
        self.assertEqual(state['http_bytes'], '0')
        self.assertEqual(state['http_uncertain_bytes'], str(MAX_FRAME))
        self.assertEqual(state['http_reserved'], '0')
        self.assertEqual(len(self.adapter.calls), 1)

    async def test_capacity_exhaustion_cancels_existing_work_without_eviction(self):
        await self.session.aclose()
        self.session = Session([self.alias], self.adapter, max_inflight=1)
        self.adapter.gate.clear()
        original = encode_frame(self.begin())
        first = self.session.dispatch(original)
        await self.adapter.entered.wait()
        with self.assertRaisesRegex(BridgeRejected, 'attempt_capacity'):
            self.dispatch(self.begin())
        await self.session.aclose()
        self.assertEqual(self.session.dispatch(original), first)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(len(self.adapter.releases), 1)

    async def test_reply_retention_bound_closes_instead_of_evicting_replay(self):
        original = encode_frame(self.begin())
        first = self.session.dispatch(original)
        token = reply(first)['token']
        await self.terminal(token)
        with patch('meme_machine.operational.transport_bridge.MAX_RETAINED', 1):
            with self.assertRaisesRegex(BridgeRejected, 'retained_bound'):
                self.dispatch(self.message('poll', token=token))
        self.assertTrue(self.session.closed)
        self.assertEqual(self.session.dispatch(original), first)
        self.assertEqual(len(self.adapter.calls), 1)

    async def test_fault_never_leaks_credentials_or_exposes_response(self):
        self.adapter.failure = RuntimeError('https://secret.invalid/credential sql path')
        self.dispatch(self.begin())
        await self.adapter.entered.wait()
        for _ in range(20):
            if self.session.closed:
                break
            await asyncio.sleep(0)
        self.assertTrue(self.session.closed)
        self.assertTrue(all(s.body is None for s in self.session._states.values()))
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')

    async def test_canceled_cleanup_is_terminal_accounting_failure_not_busy_loop(self):
        async def canceled(*args, **kwargs):
            raise asyncio.CancelledError
        self.adapter.release = canceled
        token = self.dispatch(self.begin())['token']
        for _ in range(20):
            if self.session.closed:
                break
            await asyncio.sleep(0)
        self.assertTrue(self.session.closed)
        self.assertEqual(self.session._states[token].status, 'accounting_failed')
        self.assertIsNone(self.session._states[token].body)

    async def test_cleanup_fault_closes_without_publishing_committed_bytes(self):
        self.adapter.cleanup_failure = RuntimeError('private database path')
        token = self.dispatch(self.begin())['token']
        for _ in range(20):
            if self.session.closed:
                break
            await asyncio.sleep(0)
        self.assertEqual(self.session._states[token].status, 'accounting_failed')
        self.assertIsNone(self.session._states[token].body)

    async def test_oversized_adapter_response_fails_closed(self):
        self.adapter.payload = b'x' * (MAX_BODY + 1)
        token = self.dispatch(self.begin())['token']
        for _ in range(20):
            if self.session.closed:
                break
            await asyncio.sleep(0)
        self.assertTrue(self.session.closed)
        self.assertIsNone(self.session._states[token].body)

    async def test_metered_partial_http_response_cannot_be_misrepresented_as_complete(self):
        self.adapter.eof = False
        token = self.dispatch(self.begin())['token']
        await self.adapter.entered.wait()
        for _ in range(20):
            if self.session.closed:
                break
            await asyncio.sleep(0)
        self.assertTrue(self.session.closed)
        self.assertEqual(self.session._states[token].status, 'failed')
        self.assertIsNone(self.session._states[token].body)
        self.assertEqual(self.adapter.releases, [(token, True)])
        state = self.budget.snapshot()
        self.assertEqual(state['http_bytes'], str(len(self.adapter.payload)))
        self.assertEqual(state['http_uncertain_bytes'], str(MAX_FRAME - len(self.adapter.payload)))
        self.assertEqual(state['http_reserved'], '0')

    async def test_immutable_configuration_and_attempts(self):
        with self.assertRaises(FrozenInstanceError):
            self.alias.name = 'changed'
        token = self.dispatch(self.begin())['token']
        await self.terminal(token)
        with self.assertRaises(FrozenInstanceError):
            self.adapter.calls[0].deadline += 30
        self.assertIsInstance(self.adapter.calls[0].calls[0].params_json, bytes)

    async def test_foreign_token_and_session_are_rejected(self):
        with self.assertRaisesRegex(BridgeRejected, 'foreign_token'):
            self.dispatch(self.message('cancel', token='x' * 43))
        await self.session.aclose()
        self.session = Session([self.alias], self.adapter)
        self.seq = 0
        message = self.begin()
        message['session'] = 'foreign'
        with self.assertRaisesRegex(BridgeRejected, 'session_sequence'):
            self.dispatch(message)
        self.assertEqual(self.adapter.calls, [])

    async def test_strict_fields_methods_and_nested_authority_data(self):
        mutations = [dict(alias='https://secret.invalid'), dict(batch=1),
            dict(deadline=9999999999), dict(priority='held'),
            dict(calls=[dict(method='sendTransaction', params=[])]),
            dict(calls=[dict(method='getSlot', params=[], url='https://evil')]),
            dict(calls=[dict(method='getSlot', params=[{'path':'/srv/state'}])]),
            dict(calls=[dict(method='getSlot', params=[{'allowance':1000000}])]),
            dict(calls=[dict(method='getSlot', params=['https://evil'])])]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                await self.session.aclose()
                self.session = Session([self.alias], self.adapter)
                self.seq = 0
                with self.assertRaises(BridgeRejected):
                    self.dispatch(self.begin(**mutation))
                self.assertTrue(self.session.closed)
        self.assertEqual(self.adapter.calls, [])


class FramingTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_prefix_does_not_read_body(self):
        class Reader:
            calls = []
            async def readexactly(self, count):
                self.calls.append(count)
                return struct.pack('!I', MAX_REQUEST + 1)
        reader = Reader()
        with self.assertRaises(BridgeRejected):
            await read_request_frame(reader)
        self.assertEqual(reader.calls, [4])

    async def test_truncation_coalescing_duplicate_keys_nonfinite_and_deep_json_rejected(self):
        bodies = [b'{"seq":1,"seq":2}', b'{"seq":NaN}', b'[' * 1000 + b']' * 1000,
                  b'{"seq":1,"params":[1e999]}', b'{"seq":1,"params":[1.25]}',
                  b'{"seq":1,"params":[1e-999]}',
                  b'\xff', b'[]']
        for body in bodies:
            with self.subTest(body=body[:30]), self.assertRaises(BridgeRejected):
                decode_request(struct.pack('!I', len(body)) + body)
        frame = encode_frame({'seq':1})
        for invalid in (frame[:-1], frame + frame, struct.pack('!I', 0)):
            with self.assertRaises(BridgeRejected):
                decode_request(invalid)

    async def test_valid_fragmented_reader_and_eof(self):
        reader = asyncio.StreamReader()
        frame = encode_frame({'seq':1})
        pending = asyncio.create_task(read_request_frame(reader))
        reader.feed_data(frame[:3])
        await asyncio.sleep(0)
        self.assertFalse(pending.done())
        reader.feed_data(frame[3:])
        self.assertEqual(await pending, frame)
        reader.feed_eof()
        with self.assertRaises(asyncio.IncompleteReadError):
            await read_request_frame(reader)
