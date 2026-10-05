"""Size telemetry for SQLite files that can disappear during checkpoint."""
from pathlib import Path


def transient_file_size(path):
    try:return Path(path).stat().st_size
    except FileNotFoundError:return 0
