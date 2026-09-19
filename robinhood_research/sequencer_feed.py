"""Observation-only Robinhood Nitro sequencer-feed client.

The official feed provides low-latency ordering/liveness evidence. It is never used
as qualification, allocation, execution or settlement authority. This module only
tracks bounded feed continuity and metadata; RPC/finality evidence remains canonical.
"""
from __future__ import annotations

import base64
from collections import OrderedDict
import hashlib
import json
import os
import socket
import ssl
import struct
import time
import zlib
from urllib.parse import urlsplit

from . import BoundaryError
from .provider_topology import SEQUENCER_FEED_URL


FEED_ENV = "MM_ROBINHOOD_SEQUENCER_FEED_URL"
MAX_FRAME_BYTES = 16 * 1024 * 1024
MAX_TRACKED_SEQUENCES = 4096


def feed_url(environ=None):
    values = os.environ if environ is None else environ
    value = str(values.get(FEED_ENV, "") or "").strip() or SEQUENCER_FEED_URL
    parsed = urlsplit(value)
    if (
        parsed.scheme != "wss"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise BoundaryError("robinhood_sequencer_feed_requires_wss")
    return value


def _canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class SequencerFeedState:
    """Bounded continuity telemetry for Nitro broadcast envelopes."""

    def __init__(self):
        self.envelopes = 0
        self.messages = 0
        self.signed_messages = 0
        self.duplicates = 0
        self.conflicts = 0
        self.regressions = 0
        self.gap_events = 0
        self.missing_sequences = 0
        self.malformed = 0
        self.non_message_envelopes = 0
        self.first_sequence = None
        self.last_sequence = None
        self.latest_header_block_number = None
        self.latest_header_timestamp = None
        self.last_received_at = None
        self._seen = OrderedDict()

    def _remember(self, sequence, fingerprint):
        prior = self._seen.get(sequence)
        if prior is not None:
            if prior == fingerprint:
                self.duplicates += 1
            else:
                self.conflicts += 1
            return False
        self._seen[sequence] = fingerprint
        while len(self._seen) > MAX_TRACKED_SEQUENCES:
            self._seen.popitem(last=False)
        return True

    def ingest(self, payload, *, received_at=None):
        now = time.time() if received_at is None else float(received_at)
        try:
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            envelope = json.loads(payload) if isinstance(payload, str) else payload
            if not isinstance(envelope, dict):
                raise ValueError("envelope")
            if "messages" not in envelope:
                self.non_message_envelopes += 1
                return 0
            rows = envelope.get("messages")
            if not isinstance(rows, list):
                raise ValueError("messages")
        except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            self.malformed += 1
            return 0

        self.envelopes += 1
        self.last_received_at = now
        accepted = 0
        for row in rows:
            try:
                if not isinstance(row, dict):
                    raise ValueError("message")
                sequence = row.get("sequenceNumber")
                if type(sequence) is not int or sequence < 0:
                    raise ValueError("sequence")
                fingerprint = _canonical_hash(row)
            except (ValueError, TypeError):
                self.malformed += 1
                continue

            is_new = self._remember(sequence, fingerprint)
            if not is_new:
                continue
            if self.last_sequence is not None:
                if sequence > self.last_sequence + 1:
                    self.gap_events += 1
                    self.missing_sequences += sequence - self.last_sequence - 1
                elif sequence < self.last_sequence:
                    self.regressions += 1
            self.first_sequence = (
                sequence if self.first_sequence is None else self.first_sequence
            )
            self.last_sequence = (
                sequence
                if self.last_sequence is None
                else max(self.last_sequence, sequence)
            )
            if row.get("signatureV2"):
                self.signed_messages += 1

            inner = row.get("message")
            if isinstance(inner, dict):
                inner = inner.get("message")
            header = inner.get("header") if isinstance(inner, dict) else None
            if isinstance(header, dict):
                block_number = header.get("blockNumber")
                timestamp = header.get("timestamp")
                if type(block_number) is int and block_number >= 0:
                    self.latest_header_block_number = block_number
                if type(timestamp) is int and timestamp >= 0:
                    self.latest_header_timestamp = timestamp
            self.messages += 1
            accepted += 1
        return accepted

    def summary(self, *, now=None):
        observed = time.time() if now is None else float(now)
        return dict(
            authority="observation_only",
            envelopes=self.envelopes,
            messages=self.messages,
            signed_messages=self.signed_messages,
            signature_presence_rate=(
                None if not self.messages else self.signed_messages / self.messages
            ),
            first_sequence=self.first_sequence,
            last_sequence=self.last_sequence,
            duplicates=self.duplicates,
            conflicts=self.conflicts,
            regressions=self.regressions,
            gap_events=self.gap_events,
            missing_sequences=self.missing_sequences,
            malformed=self.malformed,
            non_message_envelopes=self.non_message_envelopes,
            latest_header_block_number=self.latest_header_block_number,
            latest_header_timestamp=self.latest_header_timestamp,
            feed_message_age_seconds=(
                None
                if self.latest_header_timestamp is None
                else max(0.0, observed - self.latest_header_timestamp)
            ),
            seconds_since_receive=(
                None
                if self.last_received_at is None
                else max(0.0, observed - self.last_received_at)
            ),
        )


class _WebSocket:
    """Minimal bounded WSS reader for the Nitro feed; no third-party dependency."""

    def __init__(self, url, *, timeout=5.0, max_frame_bytes=MAX_FRAME_BYTES):
        self.url = url
        self.timeout = float(timeout)
        self.max_frame_bytes = int(max_frame_bytes)
        self.sock = None
        self.permessage_deflate = False
        self.server_no_context_takeover = False
        self._inflater = None

    @staticmethod
    def _read_exact(sock, size):
        chunks = []
        remaining = size
        while remaining:
            chunk = sock.recv(remaining)
            if not chunk:
                raise BoundaryError("sequencer_feed_connection_closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def connect(self):
        parsed = urlsplit(self.url)
        if parsed.scheme != "wss" or not parsed.hostname:
            raise BoundaryError("robinhood_sequencer_feed_requires_wss")
        port = parsed.port or 443
        raw = socket.create_connection(
            (parsed.hostname, port),
            timeout=self.timeout,
        )
        context = ssl.create_default_context()
        sock = context.wrap_socket(raw, server_hostname=parsed.hostname)
        sock.settimeout(self.timeout)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        key = base64.b64encode(os.urandom(16)).decode()
        host = parsed.hostname if port == 443 else f"{parsed.hostname}:{port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Extensions: permessage-deflate; client_max_window_bits\r\n"
            "User-Agent: meme-machine-robinhood-observer/1\r\n\r\n"
        ).encode()
        sock.sendall(request)
        response = bytearray()
        while b"\r\n\r\n" not in response:
            if len(response) > 64 * 1024:
                raise BoundaryError("sequencer_feed_handshake_capacity")
            response.extend(sock.recv(4096))
        header = bytes(response).split(b"\r\n\r\n", 1)[0].decode(
            "iso-8859-1"
        )
        lines = header.split("\r\n")
        if not lines or " 101 " not in lines[0]:
            raise BoundaryError("sequencer_feed_handshake_rejected")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()
        ).decode()
        if headers.get("sec-websocket-accept") != expected:
            raise BoundaryError("sequencer_feed_handshake_identity")
        extension = headers.get("sec-websocket-extensions", "")
        if "permessage-deflate" not in extension.lower():
            raise BoundaryError("sequencer_feed_compression_required")
        self.permessage_deflate = True
        self.server_no_context_takeover = (
            "server_no_context_takeover" in extension.lower()
        )
        self._inflater = zlib.decompressobj(wbits=-15)
        self.sock = sock
        return self

    def close(self):
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _send_control(self, opcode, payload=b""):
        if self.sock is None:
            return
        if len(payload) > 125:
            raise BoundaryError("sequencer_feed_control_capacity")
        mask = os.urandom(4)
        masked = bytes(value ^ mask[i % 4] for i, value in enumerate(payload))
        self.sock.sendall(
            bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked
        )

    def _inflate_message(self, payload):
        if not self.permessage_deflate:
            return payload
        if self._inflater is None or self.server_no_context_takeover:
            self._inflater = zlib.decompressobj(wbits=-15)
        try:
            data = self._inflater.decompress(payload + b"\x00\x00\xff\xff")
        except zlib.error:
            raise BoundaryError("sequencer_feed_compression_error") from None
        if len(data) > self.max_frame_bytes:
            raise BoundaryError("sequencer_feed_message_capacity")
        if self.server_no_context_takeover:
            self._inflater = None
        return data

    def recv_message(self):
        if self.sock is None:
            raise BoundaryError("sequencer_feed_not_connected")
        fragments = bytearray()
        message_opcode = None
        compressed = False
        while True:
            first, second = self._read_exact(self.sock, 2)
            final = bool(first & 0x80)
            rsv1 = bool(first & 0x40)
            if first & 0x30:
                raise BoundaryError("sequencer_feed_reserved_bits")
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(self.sock, 2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(self.sock, 8))[0]
            if length > self.max_frame_bytes:
                raise BoundaryError("sequencer_feed_frame_capacity")
            mask = self._read_exact(self.sock, 4) if masked else None
            payload = self._read_exact(self.sock, length)
            if mask is not None:
                payload = bytes(
                    value ^ mask[i % 4] for i, value in enumerate(payload)
                )
            if opcode == 0x8:
                return None
            if opcode == 0x9:
                if rsv1:
                    raise BoundaryError("sequencer_feed_control_compression")
                self._send_control(0xA, payload)
                continue
            if opcode == 0xA:
                if rsv1:
                    raise BoundaryError("sequencer_feed_control_compression")
                continue
            if opcode in (0x1, 0x2):
                if message_opcode is not None:
                    raise BoundaryError("sequencer_feed_fragment_shape")
                message_opcode = opcode
                compressed = rsv1
                fragments.extend(payload)
            elif opcode == 0x0:
                if message_opcode is None or rsv1:
                    raise BoundaryError("sequencer_feed_fragment_shape")
                fragments.extend(payload)
            else:
                raise BoundaryError("sequencer_feed_opcode")
            if len(fragments) > self.max_frame_bytes:
                raise BoundaryError("sequencer_feed_message_capacity")
            if final:
                data = bytes(fragments)
                if compressed:
                    data = self._inflate_message(data)
                if message_opcode in (0x1, 0x2):
                    try:
                        return data.decode("utf-8")
                    except UnicodeDecodeError:
                        raise BoundaryError("sequencer_feed_non_utf8") from None


class SequencerBlockClock:
    """Persistent observation-only L2 block clock for Pons discovery.

    Nitro broadcast sequenceNumber is the Robinhood L2 sequence/block progression.
    A gap, conflict, regression or malformed frame fails closed. The clock does not
    provide transaction/state authority; callers still authenticate exact blocks/logs
    through the governed directional evidence RPC.
    """

    def __init__(self, url=None, *, timeout=5.0):
        self.url=url or feed_url()
        self.timeout=float(timeout)
        self.state=SequencerFeedState()
        self.client=None

    def connect(self):
        if self.client is None:
            self.client=_WebSocket(
                self.url,timeout=self.timeout
            ).connect()
        return self

    def close(self):
        client,self.client=self.client,None
        if client is not None:
            client.close()

    def _healthy(self):
        s=self.state
        if s.gap_events or s.conflicts or s.regressions or s.malformed:
            raise BoundaryError("sequencer_discovery_continuity_lost")

    def wait_for_after(self, sequence, *, timeout=1.0):
        self.connect()
        deadline=time.monotonic()+max(0.05,float(timeout))
        while time.monotonic()<deadline:
            remaining=max(0.05,deadline-time.monotonic())
            self.client.sock.settimeout(min(1.0,remaining))
            try:
                payload=self.client.recv_message()
            except socket.timeout:
                continue
            if payload is None:
                raise BoundaryError("sequencer_feed_connection_closed")
            self.state.ingest(payload,received_at=time.time())
            self._healthy()
            latest=self.state.last_sequence
            if latest is not None and latest>int(sequence):
                return int(latest)
        return None

    def status(self):
        row=self.state.summary(now=time.time())
        row.update(
            role="pons_discovery_clock",
            authority="observation_only",