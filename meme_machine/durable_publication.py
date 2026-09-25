"""Non-authoritative JSON publication with independent failure handling."""
import json
import os
from pathlib import Path
import uuid


def publish_bytes(path, content):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:temporary.unlink(missing_ok=True)


def publish_json(path,value):
    from .solana_provider_config import AlchemyEndpoint,public_value
    endpoint=os.environ.get('MM_SOLANA_READ_RPC_URL')
    credential=AlchemyEndpoint.parse(endpoint).credential if endpoint else None
    public_value(value,credential)
    publish_bytes(path,(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode())


def publish_report(path,value,*,asynchronous=False):
    """Export failure has no authority to cancel, settle or stop a lifecycle.

    Return explicit diagnostics for the caller to include in its next report.
    Canonical accounting/state writes MUST NOT use this best-effort interface.
    """
    if asynchronous:return background_report(path,value)
    try:
        publish_json(path,value)
        return {'published':True,'error':None}
    except (OSError,ValueError,TypeError,RuntimeError) as exc:
        # A concurrent diagnostic dict change can invalidate one serialization.
        # Preserve the previous complete report and all independent journals.
        return {'published':False,'error':type(exc).__name__}


class ReportPublisher:
    """One bounded latest-snapshot mailbox; report I/O cannot hold a lane thread."""
    def __init__(self,path):
        import threading,queue
        self.path=Path(path);self.queue=queue.Queue(maxsize=1);self.stop=threading.Event()
        self.result={'published':False,'pending':False,'error':None};self.dropped=0
        self.thread=threading.Thread(target=self._run,name='report-publisher',daemon=True);self.thread.start()
    def submit(self,value):
        import copy,queue
        try:snapshot=copy.deepcopy(value)
        except (RuntimeError,TypeError,ValueError) as exc:return dict(published=False,error=type(exc).__name__)
        try:self.queue.put_nowait(snapshot)
        except queue.Full:
            try:self.queue.get_nowait();self.queue.task_done();self.dropped+=1
            except queue.Empty:pass
            try:self.queue.put_nowait(snapshot)
            except queue.Full:self.dropped+=1
        return dict(self.result,pending=True,superseded_reports=self.dropped)
    def _run(self):
        import queue
        while not self.stop.is_set() or not self.queue.empty():
            try:value=self.queue.get(timeout=.1)
            except queue.Empty:continue
            try:self.result=publish_report(self.path,value)
            except BaseException as exc:self.result=dict(published=False,error=type(exc).__name__)
            finally:self.queue.task_done()
    def close(self,timeout=.25):
        self.stop.set();self.thread.join(timeout=timeout)
        return not self.thread.is_alive()

_publishers={}

def background_report(path,value):
    key=str(Path(path).resolve())
    publisher=_publishers.get(key)
    if publisher is None:
        if len(_publishers)>=4:return dict(published=False,error='publisher_registry_bound')
        publisher=_publishers[key]=ReportPublisher(path)
    return publisher.submit(value)

def flush_reports(timeout=.25):
    for publisher in _publishers.values():publisher.close(timeout)

import atexit
atexit.register(flush_reports)
