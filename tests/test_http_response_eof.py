"""Real HTTPResponse EOF with original durable Budget and parent transport."""
import asyncio
import http.client
import io
import json
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

from meme_machine.operational.bounded_provider import Budget,DeliveredResponse,MAX_FRAME
from meme_machine.operational.parent_transport import ParentHTTP,SourceBinding,ParentTransportFailure
from meme_machine.operational.transport_bridge import EndpointAlias,ParentAttempt,ReadCall
from meme_machine.runtime.governor import Governor

SOL='https://solana-mainnet.g.alchemy.com/v2/offline-eof-secret'
BODY=b'{"jsonrpc":"2.0","id":1,"result":123}'


class OfflineSocket:
    """Native parser and SocketIO with a deterministic offline byte source."""
    def __init__(self,body,*,mode='length',extra=0):
        headers=(b'Content-Length: '+str(len(body)+extra).encode()+b'\r\n' if mode=='length'
            else b'Transfer-Encoding: chunked\r\n' if mode=='chunked' else b'')
        wire=(hex(len(body))[2:].encode()+b'\r\n'+body+b'\r\n0\r\n\r\n'
            if mode=='chunked' else body)
        self.headers=io.BytesIO(b'HTTP/1.1 200 OK\r\n'+headers+b'Connection: close\r\n\r\n')
        self.body=io.BytesIO(wire);self.timeout=8;self.timeouts=[]
    def makefile(self,*args):return io.BufferedReader(socket.SocketIO(self,'rb'))
    def recv_into(self,buffer,*args):
        data=self.headers.read(len(buffer))
        if not data:data=self.body.read(len(buffer))
        buffer[:len(data)]=data
        return len(data)
    def gettimeout(self):return self.timeout
    def settimeout(self,value):self.timeout=value;self.timeouts.append(value)
    def _decref_socketios(self):pass


def physical_response(*,body=BODY,mode='length',extra=0):
    sock=OfflineSocket(body,mode=mode,extra=extra)
    response=http.client.HTTPResponse(sock);response.begin()
    return response


class BufferedHTTPResponseEOFTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.budget=Budget.create(self.root/'usage.sqlite')

    def read(self,raw,*,size=-1):
        receipt=self.budget.reserve_http(SOL,[dict(method='getSlot')])
        with DeliveredResponse(raw,receipt) as response:
            return response.read(size)

    def assert_usage(self,size,*,complete):
        state=self.budget.snapshot()
        self.assertEqual(state['http_bytes'],str(size))
        self.assertEqual(state['http_reserved'],'0')
        self.assertEqual(state['http_uncertain_bytes'],'0' if complete else str(MAX_FRAME-size))
        self.assertEqual(state['http_attempts'],'1')

    def test_known_length_truncation_rejects_even_valid_json_and_preserves_partial_charge(self):
        raw=physical_response(extra=10)
        with self.assertRaisesRegex(ValueError,'bounded_http_incomplete_body'):
            self.read(raw)
        self.assertEqual(raw.length,10)
        self.assert_usage(len(BODY),complete=False)

    def test_empty_known_length_body_preserves_the_entire_uncertain_reservation(self):
        with self.assertRaisesRegex(ValueError,'bounded_http_incomplete_body'):
            self.read(physical_response(body=b'',extra=10))
        self.assert_usage(0,complete=False)

    def test_known_length_complete_exact_sized_read_closes_without_uncertain_tail(self):
        self.assertEqual(self.read(physical_response(),size=len(BODY)),BODY)
        self.assert_usage(len(BODY),complete=True)

    def test_complete_unframed_and_chunked_buffered_reads_keep_original_eof_behavior(self):
        for mode in ('unframed','chunked'):
            with self.subTest(mode=mode):
                budget=Budget.create(self.root/(mode+'.sqlite'))
                receipt=budget.reserve_http(SOL,[dict(method='getSlot')])
                with DeliveredResponse(physical_response(mode=mode),receipt) as response:
                    self.assertEqual(response.read(),BODY)
                state=budget.snapshot()
                self.assertEqual(state['http_bytes'],str(len(BODY)))
                self.assertEqual(state['http_uncertain_bytes'],'0')
                self.assertEqual(state['http_reserved'],'0')

    def test_zero_sized_read_neither_truncates_nor_claims_eof(self):
        receipt=self.budget.reserve_http(SOL,[dict(method='getSlot')])
        with DeliveredResponse(physical_response(),receipt) as response:
            self.assertEqual(response.read(0),b'')
            self.assertFalse(receipt.eof)
            self.assertEqual(response.read(),BODY)
        self.assert_usage(len(BODY),complete=True)

    def test_intentionally_partial_known_length_read_retains_original_uncertain_tail(self):
        self.assertEqual(self.read(physical_response(),size=4),BODY[:4])
        self.assert_usage(4,complete=False)


class ParentHTTPResponseEOFTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests.test_provider_clock_domain import identity
        self.enterContext(patch('meme_machine.runtime.provider_clock.current_identity',return_value=identity()))
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.budget=Budget.create(self.root/'usage.sqlite')
        self.governor=Governor(self.root/'governor.sqlite')
        self.source=SourceBinding.configured(EndpointAlias('pump','solana',frozenset(('getSlot',))),
            'pump_discovery',environ={'MM_SOLANA_READ_RPC_URL':SOL},governor=self.governor)
        self.mode='length';self.extra=0;self.body=BODY;self.responses=[]
        def physical(request,timeout):
            self.assertEqual(self.budget.snapshot()['http_reserved'],str(MAX_FRAME))
            raw=physical_response(body=self.body,mode=self.mode,extra=self.extra)
            self.responses.append(raw)
            return raw
        self.http=ParentHTTP(self.budget,[self.source],opener=physical)
        self.addAsyncCleanup(self.http.aclose)

    async def perform(self):
        attempt=ParentAttempt('offline-session','1',self.source.alias,
            (ReadCall('getSlot',b'[{"commitment":"finalized"}]'),),False,time.monotonic()+3)
        try:return await self.http.execute(attempt)
        finally:await self.http.release(attempt,uncertain=True)

    def assert_usage(self,size,*,complete):
        state=self.budget.snapshot()
        self.assertEqual(state['http_bytes'],str(size))
        self.assertEqual(state['http_reserved'],'0')
        self.assertEqual(state['http_uncertain_bytes'],'0' if complete else str(MAX_FRAME-size))
        self.assertEqual(state['http_attempts'],'1')

    async def test_known_length_truncation_never_hands_off_valid_json_as_a_complete_response(self):
        self.extra=10
        with self.assertRaisesRegex(ParentTransportFailure,'provider_response_incomplete'):
            await self.perform()
        self.assert_usage(len(BODY),complete=False)
        self.assertEqual(self.responses[0].length,10)
        self.assertFalse(self.http._states)

    async def test_complete_known_length_body_finishes_without_reading_a_closed_socket_again(self):
        result=await self.perform()
        self.assertEqual(json.loads(result.body)['result'],123)
        self.assert_usage(len(BODY),complete=True)
        self.assertTrue(self.responses[0].isclosed())

    async def test_empty_known_length_truncation_retains_whole_uncertain_tail(self):
        self.body=b'';self.extra=10
        with self.assertRaisesRegex(ParentTransportFailure,'provider_response_incomplete'):
            await self.perform()
        self.assert_usage(0,complete=False)

    async def test_unframed_success_requires_actual_empty_read_and_closes_without_uncertainty(self):
        self.mode='unframed'
        result=await self.perform()
        self.assertEqual(json.loads(result.body)['result'],123)
        self.assert_usage(len(BODY),complete=True)

    async def test_chunked_parent_policy_still_refuses_unbounded_header_loop(self):
        self.mode='chunked'
        with self.assertRaisesRegex(ParentTransportFailure,'parent_chunked_deadline_unbounded'):
            await self.perform()
        self.assert_usage(0,complete=False)


if __name__=='__main__':unittest.main()
