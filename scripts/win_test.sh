#!/bin/bash
#
# Run the pure-Python tests against a real Windows Python, from macOS, using a
# CrossOver bottle.
#
# Why this exists
# ---------------
# The suite ran green on macOS for months while `is_network_path` was broken on
# Windows, because a test cannot catch a host assumption it shares. CI on a
# Windows runner does catch those, but it costs a push and several minutes, and
# it only reports after the fact.
#
# This gives the same signal in about five seconds. What it reproduces is real,
# not mocked:
#
#   * os.name == "nt", sys.platform == "win32"
#   * cp1252 as the locale encoding, which is where read_text() without an
#     explicit encoding blows up
#   * ntpath as the path flavour: drive letters, backslash separators, and the
#     fact that Path() normalises a POSIX-looking path into a backslashed one
#   * Windows filename rules (no ':' in a name) and symlink privilege
#
# It found a real bug the macOS suite structurally could not: is_network_path
# handled a network path given as a *string* but not as a *Path*, because only
# on Windows do those two stringify differently.
#
# What it does NOT reproduce
# --------------------------
# Wine is not Windows. File locking, ACLs and genuine Win32 API edge cases
# differ, and case sensitivity here comes from the host filesystem (APFS is
# case-insensitive by default, which happens to match Windows -- by luck, not by
# emulation).
#
# So this is a third data point that is cheap enough to run every time. It does
# not replace the Windows CI job.
#
# The default run skips the Qt tests, for speed rather than capability: Qt does
# load under Wine, with its real "windows" platform plugin, and both full suites
# pass there. Point pytest at the whole tests directory if you want them, or use
# --shot, which is the part of the UI a headless assertion cannot check anyway.
#
# Usage
# -----
#   scripts/win_test.sh --setup        # once: create the bottle, install Python
#   scripts/win_test.sh                # run this repo's non-Qt tests
#   scripts/win_test.sh -k some_test   # extra args go to pytest
#   scripts/win_test.sh --shot         # render the main window as Windows draws it
#
# --setup also installs PySide6, which is what makes --shot (and the Qt tests,
# if you point pytest at them) possible: Qt loads under Wine with its native
# "windows" platform plugin, so the PNG shows genuine Windows text metrics.
#
set -uo pipefail

CX_ROOT="${CX_ROOT:-/Applications/CrossOver.app/Contents/SharedSupport/CrossOver}"
BOTTLE="${WIN_TEST_BOTTLE:-PyWinTest}"
BOTTLE_DIR="$HOME/Library/Application Support/CrossOver/Bottles/$BOTTLE"
PY_VERSION="${WIN_TEST_PYTHON:-3.12.8}"
WINPY='C:\py\python.exe'

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

die() { echo "error: $*" >&2; exit 1; }

# Wine maps the host root at Z:.
win_path() { printf 'Z:%s' "$(printf '%s' "$1" | tr '/' '\\')"; }

winrun() { "$CX_ROOT/bin/wine" --bottle "$BOTTLE" "$@" 2>&1 | grep -v "^Using a 32-bit prefix"; }

# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
setup() {
    [ -d "$CX_ROOT" ] || die "CrossOver not found at $CX_ROOT (set CX_ROOT)"

    if [ ! -d "$BOTTLE_DIR" ]; then
        echo "creating bottle '$BOTTLE' (win10_64)..."
        "$CX_ROOT/bin/cxbottle" --bottle "$BOTTLE" --create --template win10_64 \
            --description "Windows Python for cross-platform test runs" \
            || die "could not create the bottle"
    fi

    local tmp
    tmp="$(mktemp -d)"
    echo "downloading Python $PY_VERSION (embeddable, amd64)..."
    # The embeddable zip, not the installer: no MSI to fight, just unzip.
    curl -fsSL -o "$tmp/py.zip" \
        "https://www.python.org/ftp/python/$PY_VERSION/python-$PY_VERSION-embed-amd64.zip" \
        || die "download failed"
    curl -fsSL -o "$tmp/get-pip.py" https://bootstrap.pypa.io/get-pip.py \
        || die "get-pip download failed"

    mkdir -p "$BOTTLE_DIR/drive_c/py"
    unzip -q -o "$tmp/py.zip" -d "$BOTTLE_DIR/drive_c/py"
    cp "$tmp/get-pip.py" "$BOTTLE_DIR/drive_c/py/"
    rm -rf "$tmp"

    # The embeddable build ships a ._pth that disables site and site-packages,
    # so pip installs would be invisible. Re-enable both.
    local major_minor="${PY_VERSION%.*}"
    printf 'python%s.zip\n.\nLib\\site-packages\nimport site\n' \
        "${major_minor//./}" > "$BOTTLE_DIR/drive_c/py/python${major_minor//./}._pth"

    echo "installing pip, pytest and Qt..."
    winrun "$WINPY" 'C:\py\get-pip.py' --no-warn-script-location >/dev/null
    # PySide6 is ~200 MB and only --shot and the Qt tests need it, but installing
    # it here keeps "setup once" true.
    winrun "$WINPY" -m pip install -q --no-warn-script-location \
        pytest pytest-qt requests "PySide6>=6.7,<6.9" >/dev/null

    # PYTHONPATH does not survive the CrossOver wine wrapper, so nwnfile goes on
    # the path with a .pth file instead. Written whichever repo you set up from,
    # so one bottle serves both: Vaultkeeper imports nwnfile from this sibling
    # checkout, and its own pyproject only puts its own src on the path.
    local editor_src="$(dirname "$REPO")/nwn-save-editor/src"
    if [ -d "$editor_src" ]; then
        win_path "$editor_src" > "$BOTTLE_DIR/drive_c/py/Lib/site-packages/nwn-dev.pth"
    else
        echo "note: no nwn-save-editor checkout beside this one; Vaultkeeper runs" \
             "in this bottle will not find nwnfile" >&2
    fi

    echo
    winrun "$WINPY" -c "import sys, os, locale; print('ready:', os.name, sys.platform, locale.getpreferredencoding(), sys.version.split()[0])"
}

if [ "${1:-}" = "--setup" ]; then setup; exit $?; fi

[ -x "$CX_ROOT/bin/wine" ] || die "CrossOver not found at $CX_ROOT (set CX_ROOT)"
[ -d "$BOTTLE_DIR/drive_c/py" ] || die "bottle not provisioned -- run: $0 --setup"

# --------------------------------------------------------------------------- #
# --shot: render the main window as Windows draws it
# --------------------------------------------------------------------------- #
if [ "${1:-}" = "--shot" ]; then
    shift
    # Wine cannot follow a bare host path, so the defaults are translated to Z:.
    # Anything passed explicitly is forwarded untouched -- give those as the
    # bottle sees them.
    extra=()
    if [ $# -eq 0 ]; then
        user_dir="$HOME/Documents/Neverwinter Nights"
        game_root="$HOME/Library/Application Support/Steam/steamapps/common/Neverwinter Nights"
        [ -d "$user_dir" ] && extra+=(--user-dir "$(win_path "$user_dir")")
        [ -d "$game_root" ] && extra+=(--game-root "$(win_path "$game_root")")
    fi
    echo "bottle: $BOTTLE   writing to build/screenshots/"
    winrun "$WINPY" "$(win_path "$REPO/scripts/window_shot.py")" \
        --prefix win- "${extra[@]}" "$@"
    exit $?
fi

# --------------------------------------------------------------------------- #
# Run the tests
# --------------------------------------------------------------------------- #

args=()
for f in "$REPO"/tests/test_*.py; do
    grep -q "PySide6\|nwnsaveeditor\|qtbot\|vaultkeeper\.ui" "$f" && continue
    args+=("$(win_path "$REPO")\\tests\\$(basename "$f")")
done
[ ${#args[@]} -gt 0 ] || die "no non-Qt test files found under $REPO/tests"

echo "bottle: $BOTTLE   repo: $(basename "$REPO")   non-Qt test files: ${#args[@]}"
echo

# rootdir is pinned so pyproject's pythonpath and ini options still apply, and
# the cache is off so a Windows run never writes into the working tree.
winrun "$WINPY" -m pytest --rootdir "$(win_path "$REPO")" \
    -p no:cacheprovider --no-header "${args[@]}" "$@"
