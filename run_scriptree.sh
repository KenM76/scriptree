#!/usr/bin/env bash
# ScripTree launcher (Linux / macOS)
# Usage:
#   ./run_scriptree.sh
#   ./run_scriptree.sh path/to/tool.scriptree
#   ./run_scriptree.sh path/to/tree.scriptreetree -configuration standalone
#
# Search order for Python:
#   1. <ScripTree>/lib/python/bin/python3   (portable install)
#   2. python3 on PATH
#   3. python on PATH (some distros only ship the un-suffixed name)
# If none of those exist, prompts the user to install a portable Python
# (Option A on macOS, point to package manager on Linux).

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── 1. Portable Python under lib/python/ ────────────────────────────
if [ -x "$SCRIPT_DIR/lib/python/bin/python3" ]; then
    PY="$SCRIPT_DIR/lib/python/bin/python3"
# ── 2/3. python3 / python on PATH ───────────────────────────────────
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PY="$(command -v python)"
else
    cat <<EOF
No Python 3 interpreter found.

ScripTree requires Python 3.11 or later. Pick one:

  1. Install a portable Python (recommended on macOS):
     bash "$SCRIPT_DIR/lib/install_python.sh"

  2. Use your distro's package manager:
     Debian / Ubuntu:   sudo apt install python3.11
     Fedora / RHEL:     sudo dnf install python3.11
     Arch:              sudo pacman -S python
     macOS / Homebrew:  brew install python@3.13

  3. Use python-build-standalone for a fully portable Linux Python:
     https://github.com/indygreg/python-build-standalone/releases
     (extract under "$SCRIPT_DIR/lib/python/")

After installing, re-run:
  bash "$SCRIPT_DIR/run_scriptree.sh"
EOF
    exit 1
fi

exec "$PY" "$SCRIPT_DIR/run_scriptree.py" "$@"
