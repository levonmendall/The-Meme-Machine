#!/bin/sh
set -eu
exec "$MM_STAGE_E_V3_PYTHON" -I -S -B -X "pycache_prefix=$MM_STAGE_E_V3_CACHE" "$MM_STAGE_E_V3_BOOTSTRAP" --multiprocessing "$@"
