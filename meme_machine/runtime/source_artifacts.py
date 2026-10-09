"""Bounded process-local source metadata, with no market-state authority."""
from collections import OrderedDict,Counter
import json
import hashlib
import os
from pathlib import Path
import struct
import sys
import threading


def _immutable(*args,**kwargs):raise TypeError('immutable_source_artifact')


class FrozenDict(dict):
    __setitem__=__delitem__=clear=pop=popitem=setdefault=update=__ior__=_immutable


class FrozenList(list):
    __setitem__=__delitem__=append=clear=extend=insert=pop=remove=reverse=sort=__iadd__=__imul__=_immutable


def freeze(value):
    if isinstance(value,dict):return FrozenDict({k:freeze(v) for k,v in value.items()})
    if isinstance(value,list):return FrozenList(freeze(v) for v in value)
    return value


def mutable_copy(value):
    if isinstance(value,dict):return {k:mutable_copy(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [mutable_copy(v) for v in value]
    return value


def _size(value):
    total=sys.getsizeof(value)
    if isinstance(value,dict):total+=sum(_size(k)+_size(v) for k,v in value.items())
    elif isinstance(value,(list,tuple)):total+=sum(_size(v) for v in value)
    return total


def fingerprint(path):
    info=Path(path).stat()
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


class ArtifactRegistry:
    def __init__(self,*,max_entries=16,max_bytes=16*1024*1024,max_artifact_bytes=4_000_000):
        self.max_entries=max_entries;self.max_bytes=max_bytes;self.max_artifact_bytes=max_artifact_bytes
        self.entries=OrderedDict();self.bytes=0;self.lock=threading.RLock()
        self.generation=0;self.counters=Counter()
        # Nanosecond stat fields can still have coarse filesystem resolution.
        # Linux change notifications catch same-size writes within one tick.
        self.watches={};self.watch_fd=-1
        if sys.platform=='linux':
            import ctypes
            self.libc=ctypes.CDLL(None,use_errno=True)
            self.watch_fd=self.libc.inotify_init1(os.O_NONBLOCK|os.O_CLOEXEC)

    def __del__(self):
        if getattr(self,'watch_fd',-1)>=0:os.close(self.watch_fd)

    def _watch(self,path):
        if self.watch_fd<0 or path in self.watches.values():return
        wd=self.libc.inotify_add_watch(self.watch_fd,os.fsencode(path),0x2|0x4|0x8|0x400|0x800)
        if wd>=0:self.watches[wd]=path

    def _changes(self):
        if self.watch_fd<0:return
        try:raw=os.read(self.watch_fd,65536)
        except BlockingIOError:return
        offset=0;changed=set()
        while offset<len(raw):
            wd,mask,cookie,length=struct.unpack_from('iIII',raw,offset);offset+=16+length
            if mask&0x4000:changed.update(self.entries)  # Queue overflow refuses all reuse.
            elif wd in self.watches:changed.add(self.watches[wd])
            if mask&0x8000:self.watches.pop(wd,None)
        if changed:
            self.generation+=1
            for path in changed:self._discard(path,unwatch=False)

    def invalidate(self):
        with self.lock:
            for path in list(self.entries):self._discard(path)
            self.generation+=1

    def _discard(self,path,*,unwatch=True):
        old=self.entries.pop(path,None)
        if old:self.bytes-=old[2]
        if unwatch:
            for wd,value in list(self.watches.items()):
                if value==path:
                    self.libc.inotify_rm_watch(self.watch_fd,wd);self.watches.pop(wd,None)

    def get(self,path,*,validate=None,prepare=None,generation=None):
        path=Path(path).absolute()
        with self.lock:
            try:
                self._changes();self._watch(path)
                stamp=fingerprint(path)
                watched=path in self.watches.values()
                # Portable/refused-watch fallback verifies content, retaining
                # parsing reuse without assuming timestamp precision.
                raw=None if watched else path.read_bytes()
                content=None if raw is None else hashlib.sha256(raw).digest()
                key=(stamp,content,generation,self.generation,validate,prepare)
                old=self.entries.get(path)
                if old and old[0]==key:
                    self.counters['hits']+=1;self.entries.move_to_end(path);return old[1]
                self._discard(path,unwatch=False);self.counters['misses']+=1
                if stamp[2]>self.max_artifact_bytes:raise ValueError('source_artifact_size_bound')
                if raw is None:raw=path.read_bytes()
                if len(raw)>self.max_artifact_bytes:raise ValueError('source_artifact_size_bound')
                def invalid_constant(value):raise ValueError('source_artifact_nonfinite')
                parsed=json.loads(raw,parse_constant=invalid_constant);self.counters['parses']+=1
                if validate:validate(parsed)
                value=freeze(parsed)
                if prepare:value=prepare(value)
                self._changes()
                if fingerprint(path)!=stamp or self.generation!=key[3]:raise ValueError('source_artifact_changed_during_load')
                size=_size(value)
                if size>self.max_bytes:raise ValueError('source_artifact_memory_bound')
                while self.entries and (len(self.entries)>=self.max_entries or self.bytes+size>self.max_bytes):
                    self._discard(next(iter(self.entries)));self.counters['evictions']+=1
                self.entries[path]=(key,value,size);self.bytes+=size
                return value
            except (OSError,ValueError,KeyError,TypeError,RecursionError):
                self._discard(path);self.counters['refusals']+=1;raise

    def stats(self):
        with self.lock:return dict(self.counters,entries=len(self.entries),retained_bytes=self.bytes,generation=self.generation)


REGISTRY=ArtifactRegistry()


def invalidate_sources():
    """Call when a source/configuration generation is deliberately replaced."""
    REGISTRY.invalidate()
