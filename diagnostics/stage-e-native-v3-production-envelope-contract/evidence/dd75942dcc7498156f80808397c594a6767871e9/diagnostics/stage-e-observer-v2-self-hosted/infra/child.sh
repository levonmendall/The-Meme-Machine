#!/bin/sh
exec /workspace/stage-e-runtime/bin/python -I -S -B -X pycache_prefix=/mnt/volume_nyc1_1790918115030/meme-machine-observer-v2-7a516a6a/bytecode-disabled "$MM_OBSERVER_INFRA/bootstrap.py" --multiprocessing "$@"
