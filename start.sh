#!/usr/bin/env bash
set -euo pipefail
BUNDLE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export DESKDANCE_ROOT="${DESKDANCE_ROOT:-$BUNDLE_DIR}"
cd "$BUNDLE_DIR"
if [[ ! -f frontend/build/index.html ]]; then
  command -v npm >/dev/null || { echo 'Install Node.js/npm to build the interface.' >&2; exit 1; }
  (cd frontend && npm ci && npm run build)
fi
if command -v cargo >/dev/null; then
  cargo build --release --locked --manifest-path deskdanced/Cargo.toml
elif [[ ! -x deskdanced/target/release/deskdanced ]]; then
  echo 'Install Rust/Cargo to build the backend. See BUNDLE-README.md.' >&2
  exit 1
fi
printf 'Open http://127.0.0.1:8321 in your browser. Press Ctrl+C to close the studio.\n'
exec deskdanced/target/release/deskdanced
