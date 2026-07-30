"""Decode NWN ``PLT`` images (packed layer textures).

Cloaks, robes and other tintable parts do not ship a plain TGA icon — they ship a
PLT, which stores no colour at all. Each pixel is two bytes: a *value* and a
*layer*. The value indexes a column of one of the game's palette textures, and the
layer says which palette to use, so the same artwork can be recoloured per item.

Layout, verified against the shipped ``icloak_m_001`` (64x128, 16,408 bytes, which
is exactly ``24 + width * height * 2``):

===========  ======================================================
offset       meaning
0            ``PLT V1  `` (8 bytes)
8            2 unused dwords
16           width, height (little-endian dwords)
24           ``width * height`` pairs of ``(value, layer)`` bytes
===========  ======================================================

Rows run bottom-to-top, as in TGA.

The result is deliberately :class:`~vaultkeeper.core.formats.tga_reader.TGAImage`
shaped so callers that already know how to show a TGA need no new path, and this
module stays free of Qt.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_MAGIC = b"PLT V1  "
_HEADER = 24

#: PLT layer -> the palette texture that colours it. The game's layer order.
LAYER_PALETTES: tuple[str, ...] = (
    "pal_skin01",    # 0 skin
    "pal_hair01",    # 1 hair
    "pal_armor01",   # 2 metal 1
    "pal_armor02",   # 3 metal 2
    "pal_cloth01",   # 4 cloth 1
    "pal_cloth01",   # 5 cloth 2
    "pal_leath01",   # 6 leather 1
    "pal_leath01",   # 7 leather 2
    "pal_tattoo01",  # 8 tattoo 1
    "pal_tattoo01",  # 9 tattoo 2
)


@dataclass
class Plt:
    """A decoded PLT: its size and the raw (value, layer) planes."""

    width: int
    height: int
    values: bytes  #: one byte per pixel — the palette column
    layers: bytes  #: one byte per pixel — which palette


def read_plt(data: bytes) -> Plt | None:
    """Decode PLT bytes, or ``None`` if this is not a well-formed PLT."""
    if len(data) < _HEADER or not data.startswith(_MAGIC):
        return None
    width, height = struct.unpack_from("<II", data, 16)
    if width <= 0 or height <= 0:
        return None
    pixels = width * height
    if len(data) < _HEADER + pixels * 2:
        return None
    body = data[_HEADER:_HEADER + pixels * 2]
    return Plt(width=width, height=height, values=body[0::2], layers=body[1::2])


def colour_plt(plt: Plt, palettes: dict[str, object], tints: dict[int, int] | None = None):
    """Colour a PLT into a :class:`TGAImage`-shaped result.

    ``palettes`` maps a palette name to its decoded ``TGAImage``; each is a 256-wide
    strip whose columns are the value axis and whose rows are the selectable tints.
    ``tints`` picks the row per layer, defaulting to 0 — an inventory icon carries
    no per-item tint, so the game's first row is the honest choice.
    """
    from vaultkeeper.core.formats.tga_reader import TGAImage

    tints = tints or {}
    rows: dict[str, tuple[bytes, int, int]] = {}
    for name, image in palettes.items():
        if image is None:
            continue
        rows[name] = (image.to_rgba(), image.width, image.height)

    out = bytearray(plt.width * plt.height * 4)
    for index, (value, layer) in enumerate(zip(plt.values, plt.layers, strict=False)):
        name = LAYER_PALETTES[layer] if layer < len(LAYER_PALETTES) else None
        entry = rows.get(name) if name else None
        if entry is None:
            # No palette for this layer: fall back to greyscale from the value, so
            # the artwork still reads rather than vanishing.
            out[index * 4:index * 4 + 4] = bytes((value, value, value, 255))
            continue
        pixels, width, height = entry
        row = min(tints.get(layer, 0), height - 1)
        offset = ((row * width) + min(value, width - 1)) * 4
        out[index * 4:index * 4 + 4] = pixels[offset:offset + 4]

    return TGAImage(
        width=plt.width, height=plt.height, pixel_data=bytes(out), has_alpha=True
    )
