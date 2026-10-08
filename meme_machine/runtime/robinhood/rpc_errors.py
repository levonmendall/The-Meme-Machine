"""Bounded RPC error attribution with explicit credential redaction."""
import hashlib
import re


def classify(error, endpoint=None):
    error=error if isinstance(error,dict) else {}
    code=error.get('code');code=code if type(code) is int and abs(code)<1000000 else None
    message=error.get('message');message=message if isinstance(message,str) else ''
    bounded=message[:8192]
    excerpt=bounded
    if endpoint:
        excerpt=excerpt.replace(endpoint,'<provider-url>')
        credential=endpoint.rsplit('/',1)[-1]
        if len(credential)>=8:excerpt=excerpt.replace(credential,'<credential>')
    excerpt=re.sub(r'(?i)(?:https?|wss?)://[^\s"\'<>]+','<url>',excerpt)
    excerpt=re.sub(r'(?i)(?:api[_-]?key|authorization)\s*[=:]\s*(?:bearer\s+)?[^\s,}]+|bearer\s+[^\s,}]+',
                   '<credential>',excerpt)
    normalized=bounded.strip().lower()
    category='unclassified'
    if code==-32000 and len(message)<=8192 and (
        normalized in ('header not found','block not found','state not available','state unavailable')
        or re.fullmatch(r'(?:header|block) (?:0x[0-9a-f]+|[0-9]+) not found',normalized)
    ):category='state_unavailable'
    elif normalized.startswith('execution reverted'):category='execution_reverted'
    elif code==429:category='rate_limit'
    return dict(code=code,category=category,message_characters=min(len(message),8193),
                message_sha256=hashlib.sha256(bounded.encode()).hexdigest(),
                message_excerpt=excerpt[:512],
                truncated=len(message)>8192)


def boundary(detail):
    if detail['category']=='state_unavailable':return 'provider_state_unavailable'
    return 'provider_rpc_'+(str(detail['code']) if detail['code'] is not None else 'unknown')
