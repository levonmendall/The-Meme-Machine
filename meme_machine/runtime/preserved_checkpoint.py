"""Local verified SQLite snapshots for the existing native prefix reducers."""
from contextlib import contextmanager
import hashlib,os,sqlite3,tempfile,time
from pathlib import Path
from meme_machine.runtime.journal import digest
@contextmanager
def snapshot(path,*,name,lane):
    path=Path(path)
    if not path.is_file() or not os.environ.get('MM_PAPER_EPOCH'):
        yield None;return
    # Keep only a temporary consistent backup; no RPC or certification archive.
    with tempfile.TemporaryDirectory(prefix='native-checkpoint-',dir=path.parent) as folder:
        target=Path(folder)/'snapshot.sqlite'
        source=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=30)
        copy=sqlite3.connect(target)
        try:source.backup(copy)
        finally:copy.close();source.close()
        with target.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
        yield target,dict(state_hash=checksum,snapshot_sha256=checksum,
            snapshot_name=name,epoch_id=os.environ['MM_PAPER_EPOCH'],window_index=time.time_ns(),artifact=None)
def history_authority(history,lane):
    return dict(state_hash=digest([lane,history.db.execute('SELECT count(*),max(at) FROM points').fetchone(),history.db.total_changes]),history_sha256=history.initial_file_sha256,
        epoch_id=os.environ.get('MM_PAPER_EPOCH','offline'),window_index=time.time_ns(),artifact=None)
