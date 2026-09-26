"""Narrow, byte-pinned exceptions for reviewed provider-free workflows."""
import base64
import hashlib
import re

# Reviewed at 9a99c8ae5e57b4ead6671d2eb81d4d0e06802175 and
# 4ab66653a23475a72abe88bc96adf9f6e0b7fd9a after Run 378's pre-market refusal.
# A renamed job or an altered workflow cannot acquire this exception by name.
REVIEWED_OFFLINE = {
    '.github/workflows/moderate-thresholds-preflight.yml':
        '1f0f533becf5371b9c66d7ca482f5df3f175357543831b5fbdfea3aa7b0528c4',
    '.github/workflows/moderate-thresholds-full-nonmarket.yml':
        '87e803788bed4a67efe7a4e7d4ecb547f45c54f78b09934b2875689335701575',
}


def reviewed_offline_digest(run, read):
    path = str(run.get('path', '')).split('@')[0]
    expected = REVIEWED_OFFLINE.get(path)
    sha = run.get('head_sha', '')
    if expected is None or not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{40}', sha):
        return None
    try:
        row = read('contents/' + path + '?ref=' + sha)
        if row.get('encoding') != 'base64' or row.get('type') != 'file':
            return None
        content = row.get('content', '')
        if not isinstance(content, str) or len(content) > 350000:
            return None
        body = base64.b64decode(''.join(content.split()), validate=True)
        observed = hashlib.sha256(body).hexdigest()
        return observed if observed == expected else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None  # Missing or ambiguous identity retains the market block.
