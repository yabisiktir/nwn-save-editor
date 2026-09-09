# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the NWN Save Editor.

Run through ``scripts/build_app.py``, which knows what to do with the result on
each platform. Frozen per OS on purpose: a PySide6 app cannot be cross-built, so
each artifact is produced on the machine it targets.

Two things here are not boilerplate:

* ``nwnfile``'s bundled game tables are read as *files* relative to the module
  (``Path(__file__).parent / "data"``), not as package resources, so they have to
  land at ``nwnfile/data`` inside the bundle or every feat and item shows as a
  raw id.
* The Qt modules we never touch are excluded. PySide6 ships a browser engine and
  a 3D stack; left in, they roughly triple the download for no benefit.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"

datas = [
    # Read by path at runtime — see the module docstring.
    (str(SRC / "nwnfile" / "data"), "nwnfile/data"),
    # The application icon, found via sys._MEIPASS by ui/editor/appicon.py.
    (str(ROOT / "assets" / "icons"), "assets/icons"),
]

# A native nwnsc bundled under tools/<os>/ (see script_compiler._find_bundled_nwnsc)
# is shipped when present, so the Tier-2 port compiles with no wine and no install.
# Optional and OS-specific, so the tree is not always there — include it only when a
# binary for this platform exists. (datas drops the exec bit; the app re-adds it.)
_bundled_nwnsc = ROOT / "tools" / (
    "windows" if sys.platform.startswith("win")
    else "macos" if sys.platform == "darwin" else "linux")
if _bundled_nwnsc.is_dir() and any(_bundled_nwnsc.glob("nwnsc*")):
    datas.append((str(_bundled_nwnsc), f"tools/{_bundled_nwnsc.name}"))

hiddenimports = [
    # Screens are imported lazily by name, so static analysis cannot see them.
    *collect_submodules("nwnsaveeditor.ui.editor.screens"),
    *collect_submodules("nwnsaveeditor.ui.dialogs"),
]

#: Qt we do not use. PySide6 is large; this is where most of the saving is.
excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtQuick3D",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtQuick",
    "PySide6.QtQml", "PySide6.QtWebSockets", "PySide6.QtWebChannel",
    # Scientific stack that sometimes rides along in a dev venv.
    "tkinter", "matplotlib", "numpy", "scipy", "pandas", "PIL", "pytest",
]

a = Analysis(
    [str(SRC / "nwnsaveeditor" / "ui" / "editor" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nwn-save-editor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX and macOS code signing do not get along
    console=False,      # a GUI app: no terminal window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icons" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="nwn-save-editor",
)

app = BUNDLE(
    coll,
    name="NWN Save Editor.app",
    icon=str(ROOT / "assets" / "icons" / "icon.icns"),
    bundle_identifier="net.vaultkeeper.nwnsaveeditor",
    version="0.1.0",
    info_plist={
        "NSHighResolutionCapable": True,          # or the icon and text are soft
        "LSApplicationCategoryType": "public.app-category.utilities",
        "LSMinimumSystemVersion": "11.0",
        "NSHumanReadableCopyright": "GPL-3.0-or-later",
        # Opening a save folder from Finder is a natural thing to want later; the
        # editor already takes folders on the command line.
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Neverwinter Nights save",
                "CFBundleTypeRole": "Editor",
                "LSItemContentTypes": ["public.folder"],
                "LSHandlerRank": "Alternate",
            }
        ],
    },
)
