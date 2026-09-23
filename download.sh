#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="/Applications/CarpetBomber"
BIN_DIR="/usr/local/bin"

if [[ "$(id -u)" -ne 0 ]]; then
  exec sudo "$0" "$@"
fi

rm -rf "$DEST"

mkdir -p "$DEST"
rsync -a \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '*.egg-info/' \
  --exclude '.git/' \
  "$SCRIPT_DIR/" "$DEST/"

python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install -i https://pypi.org/simple --upgrade pip
"$DEST/.venv/bin/pip" install -i https://pypi.org/simple "$DEST"

mkdir -p "$BIN_DIR"
ln -sf "$DEST/.venv/bin/CarpetBomber" "$BIN_DIR/CarpetBomber"
ln -sf "$DEST/.venv/bin/carpetbomber-daemon" "$BIN_DIR/carpetbomber-daemon"

echo "Installed to $DEST"
echo "Run from anywhere with: CarpetBomber"
