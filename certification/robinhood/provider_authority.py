"""One Robinhood Alchemy configuration and non-secret application references.

No I/O to a provider occurs here. Only provider constructors resolve a reference
back into a transport URL. Public observation and diagnostics are separate roles.
"""
import hashlib
import os
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit

PRIMARY = 'MM_ROBINHOOD_READ_RPC_URL'
DLMM = 'MM_ROBINHOOD_DLMM_RPC_URL'
ALCHEMY_HOST = 'robinhood-mainnet.g.alchemy.com'
CHAIN_ID = 4663
INTERVAL_SECONDS = .5
_references = {}
_lock = threading.RLock()


def normalize(value):
    try:
        if not isinstance(value, str) or any(c.isspace() for c in value):
            raise ValueError()
        p = urlsplit(value)
        if (p.scheme != 'https' or p.hostname != ALCHEMY_HOST
                or p.port not in (None, 443) or p.username is not None
                or p.password is not None or p.query or p.fragment
                or not re.fullmatch(r'/v2/[A-Za-z0-9_-]+/?', p.path)):
            raise ValueError()
        return 'https://' + ALCHEMY_HOST + p.path.rstrip('/')
    except (ValueError, TypeError):
        raise ValueError('robinhood_canonical_alchemy_configuration_invalid') from None


def fingerprint(value):
    if isinstance(value, str) and re.fullmatch(r'alchemy:[0-9a-f]{64}', value):
        return value.split(':', 1)[1]
    return hashlib.sha256(normalize(value).encode()).hexdigest()


def endpoint(value=None, *, environ=None):
    env = os.environ if environ is None else environ
    configured = str(env.get(PRIMARY, '') or '').strip()
    supplied = value or configured
    if isinstance(supplied, str) and supplied.startswith('alchemy:'):
        with _lock:
            resolved = configured or _references.get(supplied)
        if not resolved or 'alchemy:' + fingerprint(resolved) != supplied:
            raise ValueError('robinhood_provider_identity_changed')
        supplied = resolved
    if not supplied:
        raise ValueError('MM_ROBINHOOD_READ_RPC_URL_requires_full_https_url')
    canonical = normalize(supplied)
    if configured and normalize(configured) != canonical:
        raise ValueError('robinhood_provider_identity_changed')
    alias = str(env.get(DLMM, '') or '').strip()
    if alias and normalize(alias) != canonical:
        raise ValueError('robinhood_dlmm_canonical_authority_mismatch')
    with _lock:
        _references['alchemy:' + fingerprint(canonical)] = canonical
    return canonical


def reference(value=None, *, environ=None):
    return 'alchemy:' + fingerprint(endpoint(value, environ=environ))


def paths(environ=None):
    env = os.environ if environ is None else environ
    root = Path(env.get('MM_ROBINHOOD_STATE_DIR') or
                (Path.home() / '.local/state/the-meme-machine/robinhood')).expanduser().resolve()
    provider = env.get('MM_CERTIFICATION_PROVIDER_DB')
    cache = env.get('MM_CERTIFICATION_RPC_CACHE_DB')
    if provider and not cache:
        cache = str(Path(provider).with_name('shared-robinhood-evidence.sqlite'))
    if cache and not provider:
        provider = str(Path(cache).with_name('shared-robinhood-admission.sqlite'))
    return dict(provider=Path(provider).resolve() if provider else root / 'provider.sqlite',
                cache=Path(cache).resolve() if cache else root / 'evidence.sqlite')


def is_canonical_role(role):
    return role in {'directional_evidence_primary', 'dlmm_reconstruction_primary',
                    'dlmm_reconstruction_primary_fallback',
                    'dlmm_reconstruction_primary_shared_observation',
                    'pons_discovery_gap_recovery_primary'}


def failure_class(error):
    """Provider exception text is never provenance, telemetry or report content."""
    value = str(error)
    if re.fullmatch(r'provider_(?:http|rpc)_-?\d{1,6}', value):
        return value
    known = {
        'provider_transport_failure', 'provider_missing_result',
        'provider_invalid_envelope', 'provider_invalid_batch_envelope',
        'provider_invalid_batch_ids', 'provider_invalid_json', 'provider_response_capacity',
        'provider_log_block_range_limit', 'provider_pool_budget_exhausted',
        'provider_session_budget_exhausted', 'provider_scope_capacity',
        'provider_batch_capacity', 'provider_batch_shape', 'rpc_method_not_read_only',
        'provider_shared_admission_deadline', 'provider_shared_queue_capacity',
        'evidence_deadline_before_transport', 'evidence_deadline_during_transport',
        'wrong_chain', 'provider_chain_identity_unverified',
        'provider_role_not_canonical', 'provider_identity_changed',
        'provider_response_contains_credential', 'provider_boundary_failure',
    }
    return value if value in known else 'provider_boundary_failure'


def protect_response(value, url):
    import json
    body = json.dumps(value, sort_keys=True)
    key = url.rsplit('/', 1)[-1]
    if url in body or (len(key) >= 8 and key in body):
        raise ValueError('provider_response_contains_credential')
    return value


def require_canonical(rpc):
    if not getattr(rpc, 'canonical_authority', False):
        raise ValueError('provider_role_not_canonical')
    if not getattr(rpc, 'chain_verified', False):
        raise ValueError('provider_chain_identity_unverified')
    return rpc.provider_fingerprint


def safe_label(value):
    value=str(value)
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',value):return 'provider_label_redacted'
    with _lock:
        secrets=[url.rsplit('/',1)[-1] for url in _references.values()]
    if any(len(key)>=8 and key in value for key in secrets):return 'provider_label_redacted'
    return value
