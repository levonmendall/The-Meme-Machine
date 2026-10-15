"""Pinned Sourcify compilation attestations checked against exact RPC runtime.

The complete compiler input is retained once per contract as bounded compressed
JSON. Repository revisions are comparison provenance, not assumed deployment code.
No selector-only, address-only, or arbitrary bytecode-mask authentication.
"""
import base64
import hashlib
import json
from pathlib import Path
import zlib

from . import BoundaryError, CHAIN_ID

ROOT = Path(__file__).with_name('verified')


def load(role):
    if not role.replace('_', '').isalnum():
        raise BoundaryError('invalid_contract_role')
    return json.loads((ROOT / (role + '.json')).read_text())


def compiler_input(pin):
    raw = zlib.decompress(base64.b64decode(pin['compiler_input_zlib_base64']))
    if len(raw) > 4_000_000 or hashlib.sha256(raw).hexdigest() != pin['compiler_input_sha256']:
        raise BoundaryError('compiler_source_integrity')
    return json.loads(raw)


def verify_compilation(pin):
    if int(pin['chainId']) != CHAIN_ID or pin['runtimeMatch'] not in ('match', 'exact_match'):
        raise BoundaryError('unverified_compilation')
    if pin['proxyResolution'] != dict(isProxy=False, proxyType=None, implementations=[]):
        raise BoundaryError('unresolved_proxy_implementation')
    source = compiler_input(pin)
    for name, hashes in pin['source_comparison'].items():
        if hashlib.sha256(source['sources'][name]['content'].encode()).hexdigest() != hashes['verified_sha256']:
            raise BoundaryError('compiler_source_integrity')
    runtime = pin['runtimeBytecode']
    actual = bytes.fromhex(runtime['onchainBytecode'][2:])
    compiled = bytearray.fromhex(runtime['recompiledBytecode'][2:])
    if len(actual) != len(compiled) or not actual:
        raise BoundaryError('runtime_length_mismatch')
    covered = set()
    for t in runtime['transformations']:
        offset, ident = t['offset'], t['id']
        if t['type'] != 'replace':
            raise BoundaryError('unsupported_bytecode_transformation')
        if t['reason'] == 'immutable':
            refs = runtime['immutableReferences'][ident]
            ref = next((r for r in refs if r['start'] == offset), None)
            if ref is None:
                raise BoundaryError('unproven_immutable_reference')
            value = bytes.fromhex(runtime['transformationValues']['immutables'][ident][2:])
            if len(value) != ref['length']:
                raise BoundaryError('immutable_length')
        elif t['reason'] == 'cborAuxdata':
            ref = runtime['cborAuxdata'][ident]
            if ref['offset'] != offset:
                raise BoundaryError('metadata_offset')
            value = bytes.fromhex(runtime['transformationValues']['cborAuxdata'][ident][2:])
            if len(value) != len(bytes.fromhex(ref['value'][2:])):
                raise BoundaryError('metadata_length')
        else:
            raise BoundaryError('unsupported_bytecode_transformation')
        span = set(range(offset, offset + len(value)))
        if covered & span or offset < 0 or offset + len(value) > len(compiled):
            raise BoundaryError('invalid_bytecode_transformation')
        covered |= span
        compiled[offset:offset + len(value)] = value
    if compiled != actual or hashlib.sha256(actual).hexdigest() != pin['runtime_sha256']:
        raise BoundaryError('compiled_runtime_disagreement')
    return pin


def authenticate(role, address, code):
    pin = verify_compilation(load(role))
    if address.lower() != pin['address'].lower():
        raise BoundaryError('deployment_address_disagreement')
    if code.lower() != pin['runtimeBytecode']['onchainBytecode'].lower():
        raise BoundaryError('deployment_bytecode_disagreement')
    return dict(role=role, address=address.lower(), runtime_sha256=pin['runtime_sha256'],
                match_id=pin['matchId'], compiler_input_sha256=pin['compiler_input_sha256'],
                implementation=None, proxy=False)
