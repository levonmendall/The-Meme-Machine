"""Cooperative process shutdown for existing bounded native waits."""
import threading
import time

requested=threading.Event()

class Shutdown(BaseException):pass

def sleep(seconds,*,sleeper=time.sleep):
    if requested.is_set():raise Shutdown()
    # Keep native virtual clocks and test sleepers intact. Production waits can
    # be interrupted promptly, without resetting any native strategy clock.
    if getattr(sleeper,'__module__',None)!='time':return sleeper(seconds)
    if requested.wait(max(0,float(seconds))):raise Shutdown()
