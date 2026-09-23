#!/usr/bin/env bash
set -euo pipefail

PACKAGE_URL="https://github.com/Flapjackpants/CarpetBomber/archive/refs/heads/main.zip"
SCRIPT_URL="https://raw.githubusercontent.com/Flapjackpants/CarpetBomber/main/download.sh"
DEST="/Applications/CarpetBomber"
BIN_DIR="/usr/local/bin"

# Re-exec as root. When piped via curl|bash, $0 is not a real file, so
# re-download the script and run that under sudo instead.
if [[ "$(id -u)" -ne 0 ]]; then
  if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    exec sudo "$0" "$@"
  fi
  tmp="$(mktemp)"
  curl -fsSL "$SCRIPT_URL" -o "$tmp"
  chmod +x "$tmp"
  exec sudo env CB_INSTALLER_TMP="$tmp" "$tmp" "$@"
fi

cleanup() {
  if [[ -n "${CB_INSTALLER_TMP:-}" && -f "$CB_INSTALLER_TMP" ]]; then
    rm -f "$CB_INSTALLER_TMP"
  fi
}
trap cleanup EXIT

# Prefer a local checkout when this script lives next to pyproject.toml;
# otherwise pip-install from the GitHub source archive (no git clone).
INSTALL_TARGET="$PACKAGE_URL"
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
    INSTALL_TARGET="$SCRIPT_DIR"
  fi
fi

rm -rf "$DEST"
mkdir -p "$DEST"

python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install -i https://pypi.org/simple --upgrade pip
"$DEST/.venv/bin/pip" install -i https://pypi.org/simple "$INSTALL_TARGET"

mkdir -p "$BIN_DIR"
ln -sf "$DEST/.venv/bin/CarpetBomber" "$BIN_DIR/CarpetBomber"
ln -sf "$DEST/.venv/bin/carpetbomber-daemon" "$BIN_DIR/carpetbomber-daemon"

echo "Installed to $DEST"
echo "Run from anywhere with: CarpetBomber"
