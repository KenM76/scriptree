#!/usr/bin/env bash
# ScripTree launcher (Linux / macOS)
# Usage:
#   ./run_scriptree.sh
#   ./run_scriptree.sh path/to/tool.scriptree
#   ./run_scriptree.sh path/to/tree.scriptreetree -configuration standalone

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/run_scriptree.py" "$@"
