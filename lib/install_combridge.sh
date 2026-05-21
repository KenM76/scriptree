#!/usr/bin/env bash
# install_combridge.sh — populate <ScripTree>/lib/combridge/ with
# the combridge runtime binaries.  Companion to install_combridge.ps1.
#
# combridge is a .NET application targeting Windows COM, so the
# happy path lives in the PowerShell script.  This file exists for
# symmetry with install_python.sh and supports two modes:
#
#   --local-source <dir>   Copy from a local combridge build dir.
#                          Used on dev machines where you've already
#                          built combridge (cross-compiled or via
#                          dotnet on the host).
#
#   (no --local-source)    Download the latest release zip from the
#                          combridge GitHub repository (requires
#                          ``curl`` + ``unzip``).
#
# Usage:
#   bash lib/install_combridge.sh [SCRIPTREE_HOME] [--local-source DIR]
#                                  [--github-repo OWNER/REPO]
#                                  [--version TAG] [--asset PATTERN]

set -euo pipefail

# ── Argument parsing ─────────────────────────────────────────────────
SCRIPTREE_HOME=""
LOCAL_SOURCE=""
GITHUB_REPO="KenM76/combridge"
VERSION=""
ASSET_PATTERN="*combridge*.zip"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --local-source)
            LOCAL_SOURCE="$2"; shift 2 ;;
        --github-repo)
            GITHUB_REPO="$2"; shift 2 ;;
        --version)
            VERSION="$2"; shift 2 ;;
        --asset)
            ASSET_PATTERN="$2"; shift 2 ;;
        --help|-h)
            sed -n '2,25p' "$0"; exit 0 ;;
        -*)
            echo "Unknown option: $1" >&2; exit 2 ;;
        *)
            if [[ -z "$SCRIPTREE_HOME" ]]; then
                SCRIPTREE_HOME="$1"
            else
                echo "Unexpected positional arg: $1" >&2; exit 2
            fi
            shift ;;
    esac
done

# ── Resolve paths ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$SCRIPTREE_HOME" ]]; then
    SCRIPTREE_HOME="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
COMBRIDGE_DIR="$SCRIPTREE_HOME/lib/combridge"

echo "ScripTree install: $SCRIPTREE_HOME"
echo "Target combridge dir: $COMBRIDGE_DIR"

ensure_empty_target() {
    if [[ -d "$COMBRIDGE_DIR" ]]; then
        # Wipe everything except .gitkeep / README.md
        find "$COMBRIDGE_DIR" -mindepth 1 -maxdepth 1 \
            ! -name '.gitkeep' ! -name 'README.md' \
            -exec rm -rf {} +
    else
        mkdir -p "$COMBRIDGE_DIR"
    fi
}

verify_install() {
    if [[ ! -f "$COMBRIDGE_DIR/combridge.exe" ]]; then
        echo "ERROR: combridge.exe not at $COMBRIDGE_DIR/combridge.exe after install." >&2
        echo "       The source build may be missing its entry point, or the" >&2
        echo "       release zip has an unexpected layout." >&2
        exit 1
    fi
    sz=$(stat -c %s "$COMBRIDGE_DIR/combridge.exe" 2>/dev/null || stat -f %z "$COMBRIDGE_DIR/combridge.exe")
    echo
    echo "Done. combridge.exe in place ($sz bytes)."

    if [[ -d "$COMBRIDGE_DIR/plugins" ]]; then
        echo "Plugins discovered:"
        for p in "$COMBRIDGE_DIR/plugins"/*.dll; do
            [[ -f "$p" ]] && echo "  - $(basename "$p")"
        done
    else
        echo "WARN: No plugins/ directory found." >&2
    fi
}

# ── Mode 1: local copy ───────────────────────────────────────────────
if [[ -n "$LOCAL_SOURCE" ]]; then
    LOCAL_SOURCE="$(cd "$LOCAL_SOURCE" && pwd)"
    echo
    echo "Mode: local copy"
    echo "Source: $LOCAL_SOURCE"

    if [[ ! -f "$LOCAL_SOURCE/combridge.exe" ]]; then
        echo "ERROR: $LOCAL_SOURCE does not contain combridge.exe." >&2
        echo "       Point --local-source at the directory holding the built .exe" >&2
        echo "       (typically <combridge>/bin/Release/net10.0-windows)." >&2
        exit 1
    fi

    ensure_empty_target
    echo
    echo "Copying $LOCAL_SOURCE -> $COMBRIDGE_DIR ..."
    # cp -a preserves attributes; ./ src means "contents of, not the dir itself".
    cp -a "$LOCAL_SOURCE/." "$COMBRIDGE_DIR/"

    verify_install
    exit 0
fi

# ── Mode 2: GitHub release download ─────────────────────────────────
echo
echo "Mode: GitHub release download"
echo "Repo:  $GITHUB_REPO"

if [[ -n "$VERSION" ]]; then
    api_url="https://api.github.com/repos/$GITHUB_REPO/releases/tags/$VERSION"
    echo "Target version: $VERSION"
else
    api_url="https://api.github.com/repos/$GITHUB_REPO/releases/latest"
    echo "Target version: (latest)"
fi

command -v curl >/dev/null || { echo "ERROR: curl not installed."; exit 1; }
command -v unzip >/dev/null || { echo "ERROR: unzip not installed."; exit 1; }

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

release_json="$tmpdir/release.json"
if ! curl -fsSL --max-time 30 \
    -H "User-Agent: ScripTree-install_combridge.sh" \
    -o "$release_json" "$api_url"; then
    cat >&2 <<EOF
ERROR: failed to query the GitHub releases API.

  URL: $api_url

Causes:
  * network blocked / offline
  * rate limit (60 anon calls/hour/IP)
  * repository doesn't exist or isn't public yet
  * combridge release hasn't been published

WORKAROUND: build combridge locally and re-run with --local-source:

  bash lib/install_combridge.sh --local-source <combridge-build-dir>
EOF
    exit 1
fi

# Pick the matching asset.  We use grep+awk to avoid requiring jq.
# Matches the "browser_download_url" line whose preceding "name"
# matches the asset pattern.
asset_url=$(python3 - "$release_json" "$ASSET_PATTERN" <<'PY'
import json, sys, fnmatch
release_json, pattern = sys.argv[1], sys.argv[2]
with open(release_json) as f:
    data = json.load(f)
for a in data.get("assets", []):
    if fnmatch.fnmatch(a.get("name", ""), pattern):
        print(a["browser_download_url"])
        sys.exit(0)
sys.exit(1)
PY
) || true

if [[ -z "$asset_url" ]]; then
    echo "ERROR: no asset matching '$ASSET_PATTERN' on this release." >&2
    echo "       Override with --asset, or use --local-source." >&2
    exit 1
fi

zipfile="$tmpdir/combridge.zip"
echo
echo "Downloading $asset_url"
if ! curl -fL --max-time 600 -o "$zipfile" "$asset_url"; then
    echo "ERROR: download failed.  Try --local-source." >&2
    exit 1
fi

ensure_empty_target
echo
echo "Extracting to $COMBRIDGE_DIR"
unzip -q "$zipfile" -d "$COMBRIDGE_DIR"

# Flatten one level if the zip wraps everything in a single subdir.
if [[ ! -f "$COMBRIDGE_DIR/combridge.exe" ]]; then
    subdirs=("$COMBRIDGE_DIR"/*/)
    if [[ ${#subdirs[@]} -eq 1 && -f "${subdirs[0]}combridge.exe" ]]; then
        echo "Release zip wrapped in '$(basename "${subdirs[0]}")/' — flattening."
        # Move contents up one level.
        find "${subdirs[0]}" -mindepth 1 -maxdepth 1 -exec mv {} "$COMBRIDGE_DIR/" \;
        rmdir "${subdirs[0]}"
    fi
fi

verify_install
