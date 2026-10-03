"""Ordinary local state open; checkpoint compaction is managed by the supervisor."""
from contextlib import contextmanager

@contextmanager
def snapshot(path,*,name,lane):
    yield None
