"""Small strict ABI reader for authenticated research events and read calls."""
from . import BoundaryError
from .keccak import keccak256


def signature(item):
    def typ(i):
        if i['type'].startswith('tuple'):
            return '(' + ','.join(typ(c) for c in i['components']) + ')' + i['type'][5:]
        return i['type']
    return item['name'] + '(' + ','.join(typ(x) for x in item['inputs']) + ')'


def topic(sig):
    return '0x' + keccak256(sig.encode()).hex()


def calldata(sig, *values):
    words = [int(v, 16) if isinstance(v, str) else v for v in values]
    if any(not 0 <= v < 2**256 for v in words):
        raise BoundaryError('abi_argument_range')
    return topic(sig)[:10] + ''.join(f'{v:064x}' for v in words)


def words(data):
    try:
        if not isinstance(data, str) or not data.startswith('0x'):
            raise ValueError()
        raw = bytes.fromhex(data[2:])
        if len(raw) % 32 or len(raw) > 32768:
            raise ValueError()
        return [raw[i:i+32] for i in range(0, len(raw), 32)]
    except ValueError:
        raise BoundaryError('malformed_abi_words') from None


def scalar(typ, word):
    n = int.from_bytes(word, 'big')
    if typ == 'address':
        if n >= 2**160:
            raise BoundaryError('abi_address_padding')
        return '0x' + word[-20:].hex()
    if typ == 'bytes32':
        return '0x' + word.hex()
    if typ == 'bool':
        if n > 1:
            raise BoundaryError('abi_bool_range')
        return bool(n)
    if typ.startswith('uint'):
        if n >= 2**int(typ[4:] or 256):
            raise BoundaryError('abi_integer_range')
        return n
    if typ.startswith('int'):
        n = n - 2**256 if n >= 2**255 else n
        bits = int(typ[3:] or 256)
        if not -2**(bits-1) <= n < 2**(bits-1):
            raise BoundaryError('abi_integer_range')
        return n
    raise BoundaryError('unsupported_abi_type')


def decode_event(abi, event):
    matches = [a for a in abi if a['type'] == 'event' and not a.get('anonymous')
               and event['topics'] and topic(signature(a)) == event['topics'][0].lower()]
    if len(matches) != 1:
        raise BoundaryError('unsupported_event_signature')
    spec = matches[0]
    indexed = [i for i in spec['inputs'] if i['indexed']]
    plain = [i for i in spec['inputs'] if not i['indexed']]
    if len(event['topics']) != len(indexed) + 1:
        raise BoundaryError('event_topic_count')
    data = words(event['data'])
    if any('[' in i['type'] or i['type'] in ('tuple', 'bytes', 'string') for i in plain):
        raise BoundaryError('unsupported_dynamic_event')
    if len(data) != len(plain):
        raise BoundaryError('event_data_length')
    out = {}
    for spec_i, value in zip(indexed, event['topics'][1:]):
        w = words(value)
        if len(w) != 1:
            raise BoundaryError('event_topic_length')
        out[spec_i['name']] = scalar(spec_i['type'], w[0])
    for spec_i, value in zip(plain, data):
        out[spec_i['name']] = scalar(spec_i['type'], value)
    return dict(name=spec['name'], signature=signature(spec), args=out)
