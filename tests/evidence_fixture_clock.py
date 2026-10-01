"""Translate only known event timestamp bytes in explicitly synthetic replay frames."""
import base64
import struct

from meme_machine.solana_program_decoders import (
    MIGRATION_DISC, PUMPSWAP_BUY_EVENT, PUMPSWAP_SELL_EVENT,
)

PUMP_TRADE = bytes([189,219,127,211,78,230,97,238])
PUMP_CREATE = bytes([27,114,169,77,222,235,99,118])


def event_clock_offset(raw):
    disc = raw[:8]
    if disc == PUMP_TRADE:
        return 89
    if disc in (PUMPSWAP_BUY_EVENT, PUMPSWAP_SELL_EVENT):
        return 8
    if disc == MIGRATION_DISC:
        return 128
    if disc == PUMP_CREATE:
        offset = 8
        for _ in range(3):
            size = struct.unpack_from('<I', raw, offset)[0]
            offset += 4 + size
        return offset + 128
    return None


def event_clock_patches(transactions):
    patches = {}
    for tx in transactions:
        for line in tx['meta'].get('logMessages') or []:
            if not line.startswith('Program data: '):
                continue
            raw = base64.b64decode(line[14:], validate=True)
            offset = event_clock_offset(raw)
            if offset is None:
                continue
            # Base64 groups contain three bytes. Preserve both neighboring bytes;
            # replace only the signed 64-bit clock inside complete groups.
            lo, hi = offset // 3 * 3, (offset + 10) // 3 * 3
            chunk = raw[lo:hi]
            if len(chunk) != hi - lo:
                raise ValueError('fixture_event_clock_layout')
            patches[base64.b64encode(chunk)] = (chunk, offset - lo)
    return tuple((token, chunk, offset) for token, (chunk, offset) in patches.items())


def rebase_event_clocks(frame, patches, at):
    for token, original, offset in patches:
        chunk = bytearray(original)
        struct.pack_into('<q', chunk, offset, at)
        frame = frame.replace(token, base64.b64encode(chunk))
    return frame
