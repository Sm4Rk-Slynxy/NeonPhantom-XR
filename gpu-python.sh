#!/usr/bin/env bash
# Launch the app-local GPU Python with cuDNN's component libraries discoverable.
set -euo pipefail
BUNDLE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
GPU_ENV="$BUNDLE_DIR/.venv-cuda"
GPU_LIB_DIRS=""
for GPU_LIB_DIR in "$GPU_ENV"/lib/python*/site-packages/nvidia/*/lib; do
  [[ -d "$GPU_LIB_DIR" ]] && GPU_LIB_DIRS="${GPU_LIB_DIRS:+$GPU_LIB_DIRS:}$GPU_LIB_DIR"
done
export LD_LIBRARY_PATH="${GPU_LIB_DIRS}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$GPU_ENV/bin/python" "$@"
