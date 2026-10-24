"""Offline CONNECT, target TLS and unchanged WebSocket framing witnesses."""
import base64
import hashlib
import io
import os
import ssl
import unittest
from unittest.mock import Mock, patch
import zlib

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons import sequencer_feed as feed


HOST = 'feed.mainnet.chain.robinhood.com'


class ProxySocket:
    def __init__(self, response=b'HTTP/1.1 200 Connection established\r\n\r\n'):
        self.response, self.sent, self.closed = response, [], False

    def sendall(self, value):
        self.sent.append(value)

    def setsockopt(self, *_args):
        pass

    def makefile(self, *_args):
        return io.BytesIO(self.response)

    def close(self):
        self.closed = True


class WebSocketSocket:
    def __init__(self, payload):
        compressor = zlib.compressobj(wbits=-15)
        encoded = compressor.compress(payload) + compressor.flush(zlib.Z_SYNC_FLUSH)
        encoded = encoded[:-4]
        self.frame = bytes((0xC1, len(encoded))) + encoded
        self.buffer, self.sent, self.closed = bytearray(), [], False

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, request):
        self.sent.append(request)
        key = request.split(b'Sec-WebSocket-Key: ', 1)[1].split(b'\r\n', 1)[0]
        accept = base64.b64encode(hashlib.sha1(key + b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
        self.buffer.extend(b'HTTP/1.1 101 Switching Protocols\r\nSec-WebSocket-Accept: ' + accept +
            b'\r\nSec-WebSocket-Extensions: permessage-deflate\r\n\r\n' + self.frame)

    def recv(self, count):
        value = bytes(self.buffer[:count])
        del self.buffer[:count]
        return value

    def close(self):
        self.closed = True


class SequencerProxyTests(unittest.TestCase):
    def test_actual_stdlib_connect_then_target_tls_preserves_coalesced_compressed_frame(self):
        raw = ProxySocket()
        payload = b'{"messages":[]}'
        wrapped = WebSocketSocket(payload)
        context = Mock()
        context.wrap_socket.return_value = wrapped
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://user:secret%2Fvalue@proxy.invalid:8080'}, clear=True), \
                patch.object(feed.socket, 'create_connection', return_value=raw) as dial, \
                patch.object(feed.ssl, 'create_default_context', return_value=context) as tls:
            client = feed._WebSocket('wss://' + HOST, timeout=1).connect()
            self.assertEqual(client.recv_message(), payload.decode())
            client.close()
        self.assertEqual(dial.call_args.args[0], ('proxy.invalid', 8080))
        self.assertEqual(dial.call_args.args[1], 1)
        request = b''.join(raw.sent)
        self.assertTrue(request.startswith(('CONNECT ' + HOST + ':443 HTTP/').encode()))
        self.assertIn(b'Proxy-Authorization: Basic ' + base64.b64encode(b'user:secret/value'), request)
        self.assertNotIn(b'Proxy-Authorization', b''.join(wrapped.sent))
        self.assertNotIn(b'secret', b''.join(wrapped.sent))
        tls.assert_called_once_with()
        context.wrap_socket.assert_called_once_with(raw, server_hostname=HOST)
        self.assertTrue(wrapped.closed)

    def test_no_proxy_configuration_retains_direct_target_socket_path(self):
        raw, wrapped, context = Mock(), Mock(), Mock()
        context.wrap_socket.return_value = wrapped
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(feed.socket, 'create_connection', return_value=raw) as dial, \
                patch.object(feed.ssl, 'create_default_context', return_value=context), \
                patch.object(feed.http.client, 'HTTPConnection', side_effect=AssertionError('unexpected proxy')):
            self.assertIs(feed._open_tls_socket(HOST, 443, 2), wrapped)
        dial.assert_called_once_with((HOST, 443), timeout=2)
        context.wrap_socket.assert_called_once_with(raw, server_hostname=HOST)

    def test_no_proxy_standard_domain_and_port_rules_and_lowercase_precedence(self):
        for bypass in (HOST, '.chain.robinhood.com', HOST + ':443', '*'):
            with self.subTest(bypass=bypass), patch.dict(os.environ,
                    {'HTTPS_PROXY': 'http://proxy.invalid:8080', 'NO_PROXY': bypass}, clear=True):
                self.assertIsNone(feed._proxy_endpoint(HOST, 443))
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://upper.invalid:8080',
                'https_proxy': 'http://lower.invalid:8081', 'NO_PROXY': '.chain.robinhood.com'}, clear=True):
            self.assertEqual(feed._proxy_endpoint(HOST + '.evil.invalid', 443)[:2], ('lower.invalid', 8081))
        with patch.dict(os.environ, {'HTTP_PROXY': 'http://fallback.invalid:8082'}, clear=True):
            self.assertEqual(feed._proxy_endpoint(HOST, 443)[:2], ('fallback.invalid', 8082))

    def test_explicit_unsupported_or_malformed_proxy_never_falls_back_to_direct(self):
        for proxy in ('https://proxy.invalid', 'socks5://proxy.invalid:1080',
                      'http://proxy.invalid:99999', 'http://proxy.invalid:0', 'http://proxy.invalid/path',
                      'http://proxy.invalid/?token=SECRET', 'http://user%0A:SECRET@proxy.invalid'):
            with self.subTest(proxy_scheme=proxy.split(':', 1)[0]), \
                    patch.dict(os.environ, {'HTTPS_PROXY': proxy}, clear=True), \
                    patch.object(feed.socket, 'create_connection', side_effect=AssertionError('direct bypass')):
                with self.assertRaisesRegex(BoundaryError, '^sequencer_feed_proxy_configuration$') as caught:
                    feed._open_tls_socket(HOST, 443, 1)
                self.assertNotIn('SECRET', str(caught.exception))

    def test_proxy_denial_is_sanitized_closes_socket_and_does_not_attempt_target_tls(self):
        raw = ProxySocket(b'HTTP/1.1 407 SECRET https://private.invalid\r\n\r\n')
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://user:SECRET@proxy.invalid:8080'}, clear=True), \
                patch.object(feed.socket, 'create_connection', return_value=raw) as dial, \
                patch.object(feed.ssl, 'create_default_context', side_effect=AssertionError('denied tunnel TLS')):
            with self.assertRaisesRegex(OSError, '^sequencer_feed_proxy_connect_failed$') as caught:
                feed._open_tls_socket(HOST, 443, 1)
        self.assertEqual(dial.call_count, 1)
        self.assertTrue(raw.closed)
        self.assertNotIn('SECRET', str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_target_certificate_and_tls_timeout_fail_closed_without_retry(self):
        for failure in (ssl.SSLCertVerificationError('SECRET certificate'), TimeoutError('SECRET proxy')):
            raw, context = ProxySocket(), Mock()
            context.wrap_socket.side_effect = failure
            with self.subTest(error_type=type(failure).__name__), patch.dict(os.environ,
                    {'HTTPS_PROXY': 'http://proxy.invalid:8080'}, clear=True), \
                    patch.object(feed.socket, 'create_connection', return_value=raw) as dial, \
                    patch.object(feed.ssl, 'create_default_context', return_value=context):
                with self.assertRaisesRegex(OSError, '^sequencer_feed_proxy_connect_failed$'):
                    feed._open_tls_socket(HOST, 443, 1)
            self.assertEqual(dial.call_count, 1)
            self.assertTrue(raw.closed)

    def test_proxy_dial_timeout_never_retries_or_dials_target(self):
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://user:SECRET@proxy.invalid:8080'}, clear=True), \
                patch.object(feed.socket, 'create_connection', side_effect=TimeoutError('SECRET')) as dial, \
                patch.object(feed.ssl, 'create_default_context', side_effect=AssertionError('no tunnel')):
            with self.assertRaisesRegex(OSError, '^sequencer_feed_proxy_connect_failed$'):
                feed._open_tls_socket(HOST, 443, 1)
        self.assertEqual(dial.call_count, 1)


if __name__ == '__main__':
    unittest.main()
