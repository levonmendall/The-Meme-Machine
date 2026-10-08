"""Nonsecret runtime identity for ordinary acceptance status and handoff."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import os
import re
import shlex
import sqlite3
import subprocess
from urllib.parse import urlsplit

UNITS=('paper.service','observer.service','monitor.service','metrics.service',
       'uptime-health.service','backup.service','backup.timer','acceptance@.service')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def environment(path):
    """Never include or hash a credential, URL path, query or user information."""
    names=[];endpoints={};public={}
    for line in Path(path).read_text().splitlines():
        match=re.match(r'^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)$',line)
        if match is None:continue
        name,raw=match.groups();names.append(name)
        parsed=shlex.split(raw);value=parsed[0] if parsed else ''
        if name.endswith(('_URL','_ENDPOINT')):
            endpoint=urlsplit(value)
            if endpoint.hostname:
                public_endpoint=dict(scheme=endpoint.scheme,hostname=endpoint.hostname,port=endpoint.port)
                endpoints[name]=dict(public_endpoint,identity_sha256=hashlib.sha256(
                    json.dumps(public_endpoint,sort_keys=True).encode()).hexdigest())
        if name in ('MM_MODE','MM_STATE_ROOT','MM_RPC_CAPABILITIES'):
            public[name]=value
    stat=Path(path).stat()
    return dict(variable_names=sorted(set(names)),provider_endpoints=endpoints,
                public_values=public,file_metadata=dict(uid=stat.st_uid,gid=stat.st_gid,
                    mode=oct(stat.st_mode&0o777),mtime_ns=stat.st_mtime_ns))


def capture(source, *, configuration_root='/etc/meme-machine', unit_root='/etc/systemd/system'):
    source=Path(source);configuration_root=Path(configuration_root);unit_root=Path(unit_root)
    def git(*args):
        return subprocess.check_output(['git',*args],cwd=source,text=True,timeout=5).strip()
    if git('status','--porcelain'):raise ValueError('acceptance_requires_clean_deployed_source')
    units={}
    for suffix in UNITS:
        name='meme-machine-'+suffix;path=unit_root/name
        units[name]=dict(file_sha256=sha(path),dropins={p.name:sha(p) for p in sorted((unit_root/(name+'.d')).glob('*.conf'))})
    packages={d.metadata['Name']:d.version for d in importlib.metadata.distributions()}
    storage=json.loads((configuration_root/'storage.json').read_text())
    device=os.stat(storage['volume_device'])
    return dict(commit=git('rev-parse','HEAD'),tree=git('rev-parse','HEAD^{tree}'),
        python=platform.python_version(),sqlite=sqlite3.sqlite_version,
        websockets=importlib.metadata.version('websockets'),requirements_sha256=sha(source/'requirements.txt'),
        installed_requirements=packages,units=units,storage=storage,
        environment=environment(configuration_root/'paper.env'),
        maintenance_environment=environment(configuration_root/'digitalocean.env'),
        block_device_identity=dict(major=os.major(device.st_rdev),minor=os.minor(device.st_rdev)),
        backup_configuration_sha256=sha(configuration_root/'backup.json'),
        provider_networks=dict(solana='mainnet-beta',robinhood_chain_id=4663),
        authority='observation_only')


def write(path, value):
    from .observation import atomic_json
    atomic_json(path,value)
    return sha(path)
