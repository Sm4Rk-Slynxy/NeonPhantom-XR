#!/usr/bin/env bash
set -euo pipefail
BUNDLE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$BUNDLE_DIR"
QUEST_BOOTSTRAP_PYTHON="${DESKDANCE_QUEST_BOOTSTRAP_PYTHON:-python3}"
"$QUEST_BOOTSTRAP_PYTHON" -m venv .venv-quest-gpu
.venv-quest-gpu/bin/python -m pip install -r requirements-quest-gpu.txt
printf 'Optional NVIDIA depth runtime installed. Restart start-quest.sh and choose Auto or GPU preferred.\n'
