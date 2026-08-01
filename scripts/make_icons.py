#!/usr/bin/env python3
"""Render the application icon at every size an installer needs.

The artwork is SVG, under ``assets/icons/source``, and it comes in three builds
rather than one. That is the whole point: a single drawing scaled to 16px turns
to mush, so the designer authored a full-detail mark plus reduced ones for the
small sizes, and this renders each size from the build meant for it.

    full detail   >= 64px
    nwn-save-editor-48   48px only
    nwn-save-editor-32   32px and 16px

What each build drops is recorded in ``assets/icons/source/DESIGN.txt``.

    python scripts/make_icons.py            # writes assets/icons/

Outputs the PNG ladder plus the two formats the installers need: a multi-size
``.ico`` for Windows, and (on macOS) an ``.icns`` via ``iconutil``.
"""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "icons" / "source"
OUT = ROOT / "assets" / "icons"

#: The mark's file stem under ``source``.
STEM = "nwn-save-editor"

#: Every size we ship. 64 is not decoration: macOS builds its 32@2x from it.
SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)

#: Which authored build serves which size. Reading downwards, the first entry
#: whose threshold the size meets wins.
BUILDS = ((64, ""), (48, "-48"), (0, "-32"))


def build_for(size: int) -> Path:
    """The SVG authored for this size."""
    for threshold, suffix in BUILDS:
        if size >= threshold:
            return SOURCE / f"{STEM}{suffix}.svg"
    raise AssertionError("unreachable: the last threshold is 0")


def draw(size: int) -> QImage:
    """The icon at one size, rendered from the build meant for that size."""
    path = build_for(size)
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        raise SystemExit(f"cannot render {path}")
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def write_pngs() -> dict[int, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    written = {}
    for size in SIZES:
        path = OUT / f"icon_{size}.png"
        draw(size).save(str(path), "PNG")
        written[size] = path
    return written


def write_ico() -> Path:
    """A multi-size .ico — Windows picks the right image per context.

    Assembled by hand because Qt writes one image per file, and a single-size
    .ico is exactly the thing that looks wrong in a large-icons folder view.
    """
    target = OUT / "icon.ico"
    encoded = []
    for size in (16, 32, 48, 64, 128, 256):
        scratch = OUT / f"_tmp_{size}.png"
        draw(size).save(str(scratch), "PNG")
        encoded.append((size, scratch.read_bytes()))
        scratch.unlink()

    header = struct.pack("<HHH", 0, 1, len(encoded))
    offset = 6 + 16 * len(encoded)
    entries, blobs = b"", b""
    for size, data in encoded:
        side = 0 if size >= 256 else size  # 0 means 256 in an .ico directory
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    target.write_bytes(header + entries + blobs)
    return target


def write_icns() -> Path | None:
    """A macOS .icns via iconutil, which wants a specifically named iconset."""
    if sys.platform != "darwin":
        return None
    iconset = OUT / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    # (rendered size, filename). The @2x entries are the Retina variants, and
    # each is rendered at its true pixel size rather than scaled from its 1x.
    for size, name in (
        (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
    ):
        draw(size).save(str(iconset / name), "PNG")
    target = OUT / "icon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)], check=True)
    for leftover in iconset.iterdir():
        leftover.unlink()
    iconset.rmdir()
    return target


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    _ = app
    pngs = write_pngs()
    print(f"wrote {len(pngs)} PNGs -> {OUT}")
    for size in SIZES:
        print(f"  {size:>4}px from {build_for(size).name}")
    print(f"wrote {write_ico().name}")
    icns = write_icns()
    print(f"wrote {icns.name}" if icns else "skipped .icns (needs macOS/iconutil)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
