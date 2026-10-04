"""Offline configurable Alchemy estimate. Unknown methods are never priced as zero."""
from pathlib import Path
import hashlib
import json

DEFAULT=Path(__file__).with_name('alchemy-cu-schedule.json')

def estimate(methods, schedule=None):
    path=Path(schedule or DEFAULT);raw=path.read_bytes();spec=json.loads(raw)
    priced={m:n*spec['methods'][m] for m,n in methods.items() if m in spec['methods']}
    unknown={m:n for m,n in methods.items() if m not in spec['methods']}
    return dict(estimated_cu_by_method=priced,estimated_cu=sum(priced.values()) if not unknown else None,
        known_estimated_cu=sum(priced.values()),unpriced_methods=unknown,
        schedule_sha256=hashlib.sha256(raw).hexdigest(),schedule_source=spec['source'],
        logical_calls=sum(methods.values()),billing_estimate_only=True)
