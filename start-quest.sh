#!/usr/bin/env bash
set -euo pipefail
BUNDLE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$BUNDLE_DIR"
QUEST_PYTHON="${DESKDANCE_QUEST_PYTHON:-$BUNDLE_DIR/.venv-quest/bin/python}"
if [[ ! -x "$QUEST_PYTHON" && -z "${DESKDANCE_QUEST_PYTHON:-}" ]]; then QUEST_PYTHON="$BUNDLE_DIR/.venv-gpu/bin/python"; fi
if [[ ! -x "$QUEST_PYTHON" ]]; then QUEST_PYTHON=python3; fi
exec "$QUEST_PYTHON" "$BUNDLE_DIR/quest/companion.py" "$@"
