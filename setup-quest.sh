#!/usr/bin/env bash
set -euo pipefail
BUNDLE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$BUNDLE_DIR"
QUEST_BOOTSTRAP_PYTHON="${DESKDANCE_QUEST_BOOTSTRAP_PYTHON:-python3}"
"$QUEST_BOOTSTRAP_PYTHON" -m venv .venv-quest
.venv-quest/bin/python -m pip install -r requirements-quest.txt
printf 'Quest CPU runtime ready. Run ./start-quest.sh.\n'
