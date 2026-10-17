"""Original protected Pons RPC profile over a fixed parent capability channel.

An endpoint/file digest is provenance, not self-authentication. Only the original
trusted parent reads its existing protected profile. The child cannot select a
path, mint support, discover methods, relax native parsers or gain funding.
"""
import hashlib
import json
import math
import os
import re
import stat
from types import MappingProxyType

SCHEMA='parent-pons-rpc-profile-v1'
METHODS=frozenset(('eth_getBlockReceipts','eth_callMany','eip1898_eth_call',
    'eip1898_eth_getCode','native_quote_batch'))
LIMITS=frozenset(('validated','max_response_bytes','max_latency_seconds',
    'max_throughput_cu','max_transactions','max_logical_elements'))
MAX_PROFILE=16*1024
_ISSUER=object()
_HEX=re.compile('[0-9a-f]{64}\\Z')


class ProfileFailure(ValueError):pass


def _require(value,code):
    if not value:raise ProfileFailure(code)


def _encoded(row):
    return json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _digest(value):return type(value) is str and _HEX.fullmatch(value) is not None


def _methods(value):
    _require(type(value) is dict and set(value)<=METHODS,'pons_profile_methods')
    result={}
    for name,row in value.items():
        _require(type(row) is dict and set(row)<= {'supported','observed_limits'},'pons_profile_method_shape')
        entry={}
        if 'supported' in row:
            _require(type(row['supported']) is bool,'pons_profile_supported_type')
            entry['supported']=row['supported']
        if 'observed_limits' in row:
            limits=row['observed_limits']
            _require(type(limits) is dict and set(limits)<=LIMITS,'pons_profile_limits')
            for key,item in limits.items():
                if key=='validated':valid=type(item) is bool
                elif key=='max_latency_seconds':valid=type(item) in (int,float) and math.isfinite(item) and 0<=item<=30
                else:valid=type(item) is int and 0<=item<=16*1024*1024
                _require(valid,'pons_profile_limit_type')
            entry['observed_limits']=dict(limits)
        result[name]=entry
    return result


def _selected_methods(row):
    # Unknown profile metadata never crosses the wire. Malformed optional hints
    # retain ordinary acquisition rather than becoming a new support assertion.
    selected={}
    for name in METHODS:
        original=row['methods'].get(name)
        if type(original) is not dict:continue
        entry={}
        if type(original.get('supported')) is bool:entry['supported']=original['supported']
        limits=original.get('observed_limits')
        if type(limits) is dict:
            safe={k:v for k,v in limits.items() if k in LIMITS}
            try:entry['observed_limits']=_methods({name:dict(observed_limits=safe)})[name]['observed_limits']
            except ProfileFailure:pass
        selected[name]=entry
    return _methods(selected)


def required_methods(methods):
    result=set()
    for name in ('eth_getBlockReceipts','eth_callMany'):
        if methods.get(name,{}).get('supported') is True:result.add(name)
    for method in ('eth_call','eth_getCode'):
        if methods.get('eip1898_'+method,{}).get('supported') is True:result.add(method)
    if methods.get('native_quote_batch',{}).get('supported') is True:
        result.update(('eth_call','eth_getCode','eth_gasPrice','eth_getBlockByNumber'))
    return frozenset(result)


class ParentPonsProfiles:
    __slots__=('_http','_rows')

    def __setattr__(self,*args):raise AttributeError('immutable_parent_pons_profiles')

    @classmethod
    def configured(cls,http,*,environ):
        from .parent_transport import ParentHTTP
        from meme_machine.operational.supervisor import pons_capability_path
        _require(type(http) is ParentHTTP,'pons_profile_original_parent_required')
        sources=[s for s in http.sources.values() if s.alias.family=='robinhood']
        loaded=None;checksum=None
        configured=bool(environ.get('MM_RPC_CAPABILITIES'))
        path=pons_capability_path(environ) if configured else None
        if configured:
            _require(path is not None,'pons_profile_protected_file_unverified')
            flags=os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW
            descriptor=os.open(path,flags)
            try:
                before=os.fstat(descriptor)
                _require(stat.S_ISREG(before.st_mode) and not before.st_mode&0o022
                    and before.st_size<=MAX_PROFILE,'pons_profile_protected_file_unverified')
                with os.fdopen(descriptor,'rb',closefd=False) as stream:raw=stream.read(MAX_PROFILE+1)
                after=os.fstat(descriptor)
                _require(len(raw)<=MAX_PROFILE and (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==
                    (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns),'pons_profile_file_changed')
                loaded=json.loads(raw);checksum=hashlib.sha256(raw).hexdigest()
            finally:os.close(descriptor)
        rows={}
        for source in sources:
            domain=hashlib.sha256(('4663:'+source._url).encode()).hexdigest()
            methods={}
            if loaded is not None:
                row=loaded['endpoints'][domain]
                _require(type(row) is dict and row.get('chain_id')==4663
                    and row.get('provider_domain')==domain and row.get('provider_fingerprint')==source.identity
                    and type(row.get('methods')) is dict,'pons_profile_source_mismatch')
                methods=_selected_methods(row)
                _require(required_methods(methods)<=source.alias.methods,'pons_profile_method_not_granted')
            rows[source.alias.name]=dict(schema=SCHEMA,source=source.receipt(),source_domain=domain,
                profile_file_sha256=checksum,status='LOADED' if loaded is not None else 'ABSENT',methods=methods)
        value=object.__new__(cls)
        object.__setattr__(value,'_http',http)
        object.__setattr__(value,'_rows',MappingProxyType({name:_encoded(row) for name,row in rows.items()}))
        return value

    def export(self,alias,*,session):
        _require(alias in self._rows,'pons_profile_source_unavailable')
        row=json.loads(self._rows[alias]);row['session']=session
        return row


def parent_profile_response(profiles,http,session,alias):
    from .parent_transport import ParentHTTP
    _require(type(http) is ParentHTTP and type(alias) is str and alias in http.sources
        and http.sources[alias].alias.family=='robinhood','pons_profile_source_unavailable')
    if profiles is None:
        return dict(schema=SCHEMA,session=session,source=http.sources[alias].receipt(),
            source_domain=None,profile_file_sha256=None,status='UNAVAILABLE',methods={})
    _require(type(profiles) is ParentPonsProfiles and profiles._http is http,'pons_profile_parent_owner')
    return profiles.export(alias,session=session)


class ChildPonsProfile:
    __slots__=('channel','source','status','_encoded')

    def __init__(self,channel,source,row,*,_issuer=None):
        _require(_issuer is _ISSUER,'pons_profile_parent_receipt_required')
        object.__setattr__(self,'channel',channel);object.__setattr__(self,'source',source)
        object.__setattr__(self,'status',row['status']);object.__setattr__(self,'_encoded',_encoded(row))

    def __setattr__(self,*args):raise AttributeError('immutable_child_pons_profile')

    def value(self):return json.loads(self._encoded)

    def row(self):
        value=self.value()
        return dict(chain_id=4663,provider_domain=value['source_domain'],
            provider_fingerprint=self.source.endpoint_identity,methods=value['methods'])


def profile_from_parent(channel,source,row):
    from .child_transport import ChildChannel
    from .parent_transport import SourceReference
    _require(type(channel) is ChildChannel and not channel.closed
        and channel.sources.get(source.alias) is source and source.family=='robinhood'
        and type(row) is dict and set(row)=={'schema','session','source','source_domain',
            'profile_file_sha256','status','methods'} and row['schema']==SCHEMA
        and row['session']==channel.session and SourceReference.from_receipt(row['source'])==source,
        'pons_profile_session_or_source')
    status=row['status']
    _require(status in ('UNAVAILABLE','ABSENT','LOADED'),'pons_profile_status')
    _methods(row['methods'])
    _require((status=='UNAVAILABLE' and row['source_domain'] is None or
        status in ('ABSENT','LOADED') and _digest(row['source_domain']))
        and (status=='LOADED' and _digest(row['profile_file_sha256']) or
             status in ('ABSENT','UNAVAILABLE') and row['profile_file_sha256'] is None)
        and (status=='LOADED' or row['methods']=={}),'pons_profile_provenance')
    return ChildPonsProfile(channel,source,row,_issuer=_ISSUER)


def require_profile(profile,port):
    from .child_transport import require_rpc_port
    require_rpc_port(port,'robinhood')
    _require(type(profile) is ChildPonsProfile and profile.channel is port.channel
        and profile.source is port.source and profile.status!='UNAVAILABLE'
        and getattr(port.channel,'_pons_profiles',{}).get(port.source.alias) is profile,
        'pons_profile_authenticated_owner_required')
    return profile
