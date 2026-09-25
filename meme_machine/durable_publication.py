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
    publish_bytes(path,(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode())


def publish_report(path,value):
    """Export failure has no authority to cancel, settle or stop a lifecycle.

    Return explicit diagnostics for the caller to include in its next report.
    Canonical accounting/state writes MUST NOT use this best-effort interface.
    """
    try:
        publish_json(path,value)
        return {'published':True,'error':None}
    except (OSError,ValueError,TypeError,RuntimeError) as exc:
        # A concurrent diagnostic dict change can invalidate one serialization.
        # Preserve the previous complete report and all independent journals.
        return {'published':False,'error':type(exc).__name__}
