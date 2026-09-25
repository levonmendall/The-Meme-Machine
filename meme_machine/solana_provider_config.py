"""Single Alchemy configuration/credential boundary; no network on construction."""
from dataclasses import dataclass, field
import hashlib
import json
import re
from urllib.parse import urlsplit

HOST = 'solana-mainnet.g.alchemy.com'
STREAM_HOST = 'solana-mainnet.streaming.alchemy.com'
from .pump import MAINNET as GENESIS
# Refuse URL-shaped credentials on all publication surfaces, including unconfigured
# credentials. Configured bare keys are checked at the transport boundary as well.
SECRET_PATTERN = re.compile(r'(?:https|wss)://[^\s"\'<>]*alchemy\.com/v2/[^\s"\'<>]+|(?:api[_-]?key|authorization)\s*[=:]\s*[^\s,}]+', re.I)


def public_value(value, credential=None):
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    if SECRET_PATTERN.search(raw) or credential and credential in raw:
        raise ValueError('provider_credential_publication_rejected')
    return value


@dataclass(frozen=True)
class AlchemyEndpoint:
    http_url: str = field(repr=False)
    stream_url: str = field(repr=False)
    credential: str = field(repr=False)
    identity: str
    provider: str = 'alchemy_solana_mainnet'
    network: str = 'solana-mainnet'

    @classmethod
    def parse(cls, value):
        try:
            if not isinstance(value, str) or any(c.isspace() for c in value):
                raise ValueError()
            p = urlsplit(value)
            if (p.scheme != 'https' or p.netloc not in (HOST, HOST + ':443')
                    or p.query or p.fragment or '?' in value or '#' in value
                    or not re.fullmatch(r'/v2/[A-Za-z0-9_-]{8,128}', p.path)):
                raise ValueError()
            key = p.path[4:]
            canonical = 'https://' + HOST + p.path
            return cls(canonical, 'wss://' + STREAM_HOST + p.path, key,
                       hashlib.sha256(canonical.encode()).hexdigest())
        except (ValueError, TypeError):
            raise ValueError('authoritative_alchemy_endpoint_required') from None

    def public(self, value):
        return public_value(value, self.credential)
