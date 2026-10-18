"""Genuine own-process identity; foreign/denied observations stay UNKNOWN.

Only the fixed copied child installs this deny-only process scope. It creates no
financial authority, reads no arbitrary PID and never treats denied proc access
as evidence that a lease owner died. Production has no installed scope.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re

ALIVE='ALIVE'
DEAD='DEAD'
UNKNOWN='UNKNOWN'
_ACTIVE=None


class NativeLivenessUnknown(RuntimeError):
    def __init__(self):super().__init__('isolated_native_liveness_unknown')


def _capture():
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    start=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]
    pid=os.getpid()
    if (not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',boot)
            or not start.isdigit() or int(start)<=0 or pid<=1):
        raise NativeLivenessUnknown()
    return boot,pid,str(int(start))


@dataclass(frozen=True,init=False)
class NativeProcessLiveness:
    _identity:tuple
    _closed:bool

    def __init__(self):
        try:identity=_capture()
        except (OSError,ValueError,IndexError):raise NativeLivenessUnknown() from None
        object.__setattr__(self,'_identity',identity)
        object.__setattr__(self,'_closed',False)

    def _current(self):
        if self._closed:raise NativeLivenessUnknown()
        try:value=_capture()
        except (OSError,ValueError,IndexError):raise NativeLivenessUnknown() from None
        if value!=self._identity:raise NativeLivenessUnknown()
        return value

    def identity(self):
        boot,pid,start=self._current()
        return f'{boot}:{pid}:{start}'

    def observe(self,value):
        try:
            boot,pid,start=self._current()
            if type(value) is not str:return UNKNOWN
            previous_boot,previous_pid,previous_start=value.split(':')
            if (not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',previous_boot)
                    or not previous_pid.isdigit() or not previous_start.isdigit()
                    or int(previous_pid)<=1 or int(previous_start)<=0):return UNKNOWN
            if previous_boot!=boot:return DEAD
            if int(previous_pid)!=pid:return UNKNOWN
            return ALIVE if str(int(previous_start))==start else DEAD
        except (NativeLivenessUnknown,ValueError,IndexError):return UNKNOWN

    def alive(self,value):
        observation=self.observe(value)
        if observation==UNKNOWN:raise NativeLivenessUnknown()
        return observation==ALIVE

    def close(self):
        global _ACTIVE
        if self._closed:return
        if os.getpid()!=self._identity[1]:raise NativeLivenessUnknown()
        if _ACTIVE is self:_ACTIVE=None
        object.__setattr__(self,'_closed',True)


def install_native_liveness():
    global _ACTIVE
    if _ACTIVE is not None:raise NativeLivenessUnknown()
    scope=NativeProcessLiveness();_ACTIVE=scope
    return scope


def current_scope():
    # Never silently fall back to unrestricted legacy observations after fork.
    if _ACTIVE is not None and os.getpid()!=_ACTIVE._identity[1]:
        raise NativeLivenessUnknown()
    return _ACTIVE
