"""Root maintenance HTTPS client. Credentials never enter PAPER or observations."""
import json
from pathlib import Path
import shlex
import urllib.error
import urllib.request

class APIError(RuntimeError):
    def __init__(self,status):
        self.status=status
        super().__init__('DigitalOcean HTTP '+str(status))

def request(method,path,body=None,timeout=60):
    file=Path('/etc/meme-machine/digitalocean.env');meta=file.stat()
    if meta.st_uid!=0 or meta.st_gid!=0 or meta.st_mode & 0o777!=0o600:
        raise RuntimeError('DigitalOcean credential permissions')
    token=None
    for line in file.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        key,value=line.split('=',1)
        if key.strip()=='DIGITALOCEAN_TOKEN':
            parsed=shlex.split(value,comments=True)
            if len(parsed)!=1:raise ValueError('DigitalOcean credential syntax')
            token=parsed[0]
    if not token:raise RuntimeError('DigitalOcean credential unavailable')
    if not path.startswith('/v2/') or '..' in path:raise ValueError('DigitalOcean path')
    req=urllib.request.Request('https://api.digitalocean.com'+path,method=method,
        data=None if body is None else json.dumps(body,allow_nan=False).encode(),
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:
            raw=response.read(4*1024**2+1)
            if len(raw)>4*1024**2:raise ValueError('DigitalOcean response bound')
            return response.status,json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        error.close();raise APIError(error.code) from None
