#!/usr/bin/env bash
# Install a portable Python into <ScripTree>/lib/python/.
#
# macOS path: download python.org's universal2 macOS .pkg, extract it
# manually with pkgutil + cpio (avoids running the system installer
# and keeps the install fully portable), drop pip in.
#
# Linux path: there's no canonical "embeddable" Python build for Linux
# from python.org. We point the user at their package manager AND at
# python-build-standalone (https://github.com/indygreg/python-build-
# standalone) for users who want a truly portable Linux Python under
# lib/python/.
#
# The script is best-effort. On macOS it sets up the install fully
# automatically. On Linux it prints actionable instructions and exits.

set -euo pipefail

# ── Resolve ScripTreeHome ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTREE_HOME="$(dirname "$SCRIPT_DIR")"
LIB_DIR="$SCRIPTREE_HOME/lib"
PY_DIR="$LIB_DIR/python"

echo "ScripTree install: $SCRIPTREE_HOME"
echo "Target Python dir: $PY_DIR"

# Hard-coded fallback (bumped per ScripTree release).
FALLBACK_VERSION="3.13.1"

# ── Detect platform ──────────────────────────────────────────────────
case "$(uname -s)" in
  Darwin) PLATFORM=macos ;;
  Linux)  PLATFORM=linux ;;
  *)      echo "Unsupported platform: $(uname -s)" >&2; exit 1 ;;
esac

# ── Pick latest version from python.org (or fall back) ──────────────
get_latest_version() {
  # Try python.org's release feed. curl/jq pipeline keeps the
  # implementation tiny.
  local api='https://www.python.org/api/v2/downloads/release/?is_published=true&pre_release=false'
  local result
  if command -v curl >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
    result=$(curl -fsSL --max-time 15 "$api" 2>/dev/null \
      | jq -r '.[] | select(.name | test("^Python 3\\.\\d+\\.\\d+$")) | .name | sub("^Python "; "")' 2>/dev/null \
      | sort -V \
      | tail -n 1) || result=""
    if [ -n "$result" ]; then
      echo "$result"
      return
    fi
  fi
  echo "$FALLBACK_VERSION"
}

PYTHON_VERSION="${1:-$(get_latest_version)}"
echo "Installing Python $PYTHON_VERSION"

# ── macOS path ────────────────────────────────────────────────────────
if [ "$PLATFORM" = "macos" ]; then
  PKG_NAME="python-${PYTHON_VERSION}-macos11.pkg"
  PKG_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/${PKG_NAME}"
  TMP_DIR="$(mktemp -d -t scriptree-python.XXXXXX)"
  trap "rm -rf '$TMP_DIR'" EXIT

  echo
  echo "Downloading $PKG_URL"
  curl -fSL --progress-bar -o "$TMP_DIR/$PKG_NAME" "$PKG_URL"

  echo
  echo "Extracting .pkg manually (no system-wide install)"
  # pkgutil --expand-full unpacks into a directory tree without
  # running any postinstall scripts.
  pkgutil --expand-full "$TMP_DIR/$PKG_NAME" "$TMP_DIR/expanded"

  # The framework lives inside Python_Framework.pkg/Payload (a cpio
  # archive on older macOS, a directory tree on newer pkgutil).
  # The Framework path is:
  #   <expanded>/Python_Framework.pkg/Payload/Versions/<version>/
  PAYLOAD_ROOT="$TMP_DIR/expanded/Python_Framework.pkg/Payload"
  if [ ! -d "$PAYLOAD_ROOT" ]; then
    echo "Unexpected pkg layout — couldn't find Python_Framework.pkg/Payload" >&2
    exit 1
  fi

  # The Versions/X.Y folder contains bin/, lib/, include/, etc. —
  # everything we need for a self-contained Python.
  VERSION_DIR=$(find "$PAYLOAD_ROOT/Versions" -maxdepth 1 -mindepth 1 -type d | head -n 1)
  if [ -z "$VERSION_DIR" ]; then
    echo "No version directory found under $PAYLOAD_ROOT/Versions" >&2
    exit 1
  fi

  rm -rf "$PY_DIR"
  mkdir -p "$PY_DIR"
  echo "Copying $VERSION_DIR -> $PY_DIR"
  cp -R "$VERSION_DIR/." "$PY_DIR/"

  # Embedded python on mac sometimes ships its bin/ dir without a
  # "python" symlink — only "python3" / "python3.X". Make a stable
  # alias so callers can use $PY_DIR/bin/python.
  if [ ! -e "$PY_DIR/bin/python" ] && [ -e "$PY_DIR/bin/python3" ]; then
    ln -s python3 "$PY_DIR/bin/python"
  fi

  PY_EXE="$PY_DIR/bin/python3"

  # Bootstrap pip (newer Python ships ensurepip).
  echo
  echo "Bootstrapping pip via ensurepip"
  "$PY_EXE" -m ensurepip --upgrade

  # Install ScripTree's vendored deps.
  if [ -f "$LIB_DIR/update_lib.py" ]; then
    echo
    echo "Running update_lib.py --trim"
    "$PY_EXE" "$LIB_DIR/update_lib.py" --trim || \
      echo "update_lib.py returned non-zero; you may need to run it manually."
  fi

  echo
  echo "Done. Portable Python installed at:"
  echo "  $PY_DIR"
  echo
  echo "run_scriptree.sh will now pick it up automatically."
  exit 0
fi

# ── Linux path ───────────────────────────────────────────────────────
# No clean python.org embeddable build for Linux; we offer two options.

cat <<EOF

Linux portable-Python install
=============================

There is no official python.org "embeddable" build for Linux, so
ScripTree can't drop a self-contained Python into lib/python/ on Linux
the same way it does on Windows and macOS. You have two options:

OPTION 1 — system Python via your distro's package manager
-----------------------------------------------------------
This is the simplest path. ScripTree just needs Python 3.11+ on PATH.

  Debian / Ubuntu:
    sudo apt install python3.11 python3.11-venv

  Fedora / RHEL / Rocky:
    sudo dnf install python3.11

  Arch:
    sudo pacman -S python

  openSUSE:
    sudo zypper install python311

After installing, re-run run_scriptree.sh.

OPTION 2 — python-build-standalone (portable, no root)
-------------------------------------------------------
Astral / Anthropic / Posit ship a project at

  https://github.com/indygreg/python-build-standalone/releases

…which publishes static-linked, fully portable Python builds for
Linux, macOS, and Windows. To install one under lib/python/:

  cd "$LIB_DIR"
  # Find the newest "install_only" tarball matching your arch:
  #   x86_64-unknown-linux-gnu  (most x64 Linux)
  #   aarch64-unknown-linux-gnu (Linux on ARM64 / Raspberry Pi 4)
  curl -fLO 'https://github.com/indygreg/python-build-standalone/releases/download/<DATE>/cpython-<VERSION>+<DATE>-x86_64-unknown-linux-gnu-install_only.tar.gz'
  tar xzf cpython-*-install_only.tar.gz
  # The extracted tree is named "python" — it should land at lib/python.

After extracting, run_scriptree.sh will pick up lib/python/bin/python3
automatically.

EOF
exit 1
