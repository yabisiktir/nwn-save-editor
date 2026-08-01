#!/usr/bin/env python3
"""Freeze the editor and package it for whichever OS you are on.

    python scripts/build_app.py            # freeze + package
    python scripts/build_app.py --no-package   # freeze only
    python scripts/build_app.py --clean        # start from nothing

A PySide6 app cannot be cross-built: the freeze embeds a Python interpreter and
Qt's native libraries for the machine it runs on. So this makes the artifact for
*this* platform, and the other two are produced by CI on their own runners. That
extends to CPU architecture — PySide6 has per-arch wheels, so an Apple Silicon
build is arm64-only and an Intel Mac needs its own. The names say which.

    macOS     dist/NWN Save Editor.app  ->  dist/nwn-save-editor-<ver>-macos-<arch>.dmg
    Windows   dist/nwn-save-editor/     ->  an Inno Setup .exe (see CI)
    Linux     dist/nwn-save-editor/     ->  .tar.gz (AppImage in CI)

Nothing here is signed. Unsigned, macOS Gatekeeper asks the user to right-click
→ Open the first time, and Windows SmartScreen warns; both are expected. The
hooks for signing are marked in the spec.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "nwn-save-editor.spec"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

APP_NAME = "NWN Save Editor"
SLUG = "nwn-save-editor"


def version() -> str:
    """The version from pyproject, so the artifact name cannot drift from it."""
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def freeze(clean: bool) -> None:
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)]
    if clean:
        command.insert(3, "--clean")
    print("$ " + " ".join(command))
    subprocess.run(command, check=True, cwd=ROOT)


def mac_arch() -> str:
    """The architecture the freeze actually produced.

    PySide6 ships per-architecture wheels, so a freeze on Apple Silicon is
    arm64-only and will not launch on an Intel Mac. Naming the artifact after
    the arch is the difference between "it doesn't work" and "you downloaded the
    wrong one".
    """
    return "arm64" if platform.machine() == "arm64" else "x86_64"


def package_macos() -> Path:
    """A .dmg with the app and an Applications symlink to drag it into."""
    app = DIST / f"{APP_NAME}.app"
    if not app.is_dir():
        raise SystemExit(f"{app} was not produced; did the freeze fail?")

    staging = BUILD / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copytree(app, staging / app.name, symlinks=True)
    # The drag-to-install convention. Without it people copy it to the desktop.
    (staging / "Applications").symlink_to("/Applications")

    target = DIST / f"{SLUG}-{version()}-macos-{mac_arch()}.dmg"
    target.unlink(missing_ok=True)
    subprocess.run(
        ["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", str(staging),
         "-ov", "-format", "UDZO", str(target)],
        check=True, stdout=subprocess.DEVNULL,
    )
    shutil.rmtree(staging, ignore_errors=True)
    return target


def package_linux() -> Path:
    """A .tar.gz of the one-dir build. CI additionally produces an AppImage."""
    folder = DIST / SLUG
    if not folder.is_dir():
        raise SystemExit(f"{folder} was not produced; did the freeze fail?")
    arch = "aarch64" if platform.machine() in ("aarch64", "arm64") else "x86_64"
    target = DIST / f"{SLUG}-{version()}-linux-{arch}.tar.gz"
    target.unlink(missing_ok=True)
    with tarfile.open(target, "w:gz") as tar:
        tar.add(folder, arcname=f"{SLUG}-{version()}")
    return target


def package_windows() -> Path:
    """A .zip. The signed .exe installer is built by CI with Inno Setup."""
    folder = DIST / SLUG
    if not folder.is_dir():
        raise SystemExit(f"{folder} was not produced; did the freeze fail?")
    target = DIST / f"{SLUG}-{version()}-windows-x64"
    made = shutil.make_archive(str(target), "zip", root_dir=folder)
    return Path(made)


def package() -> Path:
    if sys.platform == "darwin":
        return package_macos()
    if sys.platform.startswith("win"):
        return package_windows()
    return package_linux()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clean", action="store_true", help="discard previous build output")
    parser.add_argument("--no-package", action="store_true", help="freeze only")
    args = parser.parse_args(argv)

    if args.clean:
        shutil.rmtree(BUILD, ignore_errors=True)
        shutil.rmtree(DIST, ignore_errors=True)

    freeze(args.clean)
    if args.no_package:
        print(f"\nfrozen -> {DIST}")
        return 0

    artifact = package()
    size = artifact.stat().st_size / 1e6
    print(f"\npackaged -> {artifact}  ({size:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
