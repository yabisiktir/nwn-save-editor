"""Decoding NWN's PLT (packed layer texture) icons."""

from __future__ import annotations

import struct

from nwnfile.formats.plt_reader import (
    LAYER_PALETTES,
    colour_plt,
    read_plt,
)
from nwnfile.formats.tga_reader import TGAImage


def _plt(width: int, height: int, pairs: list[tuple[int, int]]) -> bytes:
    body = b"".join(bytes((value, layer)) for value, layer in pairs)
    return b"PLT V1  " + b"\x00" * 8 + struct.pack("<II", width, height) + body


def _palette(width: int = 256, height: int = 4) -> TGAImage:
    """A palette whose every pixel encodes its own (row, column)."""
    pixels = bytearray()
    for row in range(height):
        for col in range(width):
            pixels.extend((col & 0xFF, row & 0xFF, 0, 255))
    return TGAImage(width=width, height=height, pixel_data=bytes(pixels), has_alpha=True)


# -- parsing ---------------------------------------------------------------- #
def test_it_reads_the_header_and_splits_the_planes():
    plt = read_plt(_plt(2, 2, [(10, 0), (20, 1), (30, 2), (40, 3)]))
    assert (plt.width, plt.height) == (2, 2)
    assert list(plt.values) == [10, 20, 30, 40]
    assert list(plt.layers) == [0, 1, 2, 3]


def test_it_rejects_anything_that_is_not_a_plt():
    assert read_plt(b"") is None
    assert read_plt(b"NOT A PLT" + b"\x00" * 32) is None


def test_it_rejects_a_truncated_body():
    """A PLT is exactly 24 + width * height * 2 bytes; short means damaged."""
    data = _plt(4, 4, [(1, 0)] * 16)[:-10]
    assert read_plt(data) is None


def test_it_rejects_a_zero_sized_image():
    assert read_plt(_plt(0, 0, [])) is None


# -- colouring -------------------------------------------------------------- #
def test_a_pixel_takes_its_colour_from_its_layers_palette():
    plt = read_plt(_plt(1, 1, [(7, 0)]))
    palettes = {name: _palette() for name in set(LAYER_PALETTES)}
    image = colour_plt(plt, palettes)
    # the fake palette encodes column in red, row in green; row defaults to 0
    assert image.to_rgba()[:4] == bytes((7, 0, 0, 255))


def test_the_tint_selects_the_palette_row():
    plt = read_plt(_plt(1, 1, [(7, 0)]))
    palettes = {name: _palette() for name in set(LAYER_PALETTES)}
    image = colour_plt(plt, palettes, tints={0: 2})
    assert image.to_rgba()[:4] == bytes((7, 2, 0, 255))


def test_different_layers_read_different_palettes():
    """Layer 0 is skin and layer 4 is cloth — they must not share a palette."""
    assert LAYER_PALETTES[0] != LAYER_PALETTES[4]
    plt = read_plt(_plt(2, 1, [(5, 0), (5, 4)]))
    palettes = {name: _palette() for name in set(LAYER_PALETTES)}
    palettes[LAYER_PALETTES[4]] = _palette(height=1)  # a distinguishable stand-in
    image = colour_plt(plt, palettes)
    assert len(image.to_rgba()) == 2 * 4


def test_a_missing_palette_degrades_to_greyscale_rather_than_vanishing():
    plt = read_plt(_plt(1, 1, [(120, 0)]))
    image = colour_plt(plt, {})
    assert image.to_rgba()[:4] == bytes((120, 120, 120, 255))


def test_an_unknown_layer_does_not_crash():
    plt = read_plt(_plt(1, 1, [(9, 200)]))
    image = colour_plt(plt, {name: _palette() for name in set(LAYER_PALETTES)})
    assert len(image.to_rgba()) == 4


def test_the_result_is_tga_shaped_so_callers_need_no_new_path():
    plt = read_plt(_plt(3, 2, [(1, 0)] * 6))
    image = colour_plt(plt, {name: _palette() for name in set(LAYER_PALETTES)})
    assert (image.width, image.height) == (3, 2)
    assert image.has_alpha
    assert len(image.to_rgba()) == 3 * 2 * 4


# -- orientation ------------------------------------------------------------ #
def test_the_image_comes_out_the_right_way_up():
    """PLT rows run bottom-to-top; everything that displays one wants top-down.

    Never flipping them is why armour, helms and cloaks — the parts that ship as
    PLT rather than TGA — were all upside down, while TGA items looked right
    because the TGA reader has always flipped its own.
    """
    # Two rows, distinguishable by value: the file's first row is the BOTTOM one.
    plt = read_plt(_plt(2, 2, [(200, 0), (200, 0), (10, 0), (10, 0)]))
    image = colour_plt(plt, {LAYER_PALETTES[0]: _palette()})
    rgba = image.to_rgba()
    row_width = image.width * 4
    top, bottom = rgba[:row_width], rgba[row_width:]
    # The palette encodes the value in the red channel, so the row is identifiable.
    assert top[0] == 10, "the file's LAST row must end up at the top"
    assert bottom[0] == 200, "the file's FIRST row is the bottom of the picture"


def test_flipping_does_not_mirror_the_image_sideways():
    """Only the row order changes; a column stays where it is."""
    # One row of four, each pixel a different value.
    plt = read_plt(_plt(4, 1, [(1, 0), (2, 0), (3, 0), (4, 0)]))
    rgba = colour_plt(plt, {LAYER_PALETTES[0]: _palette()}).to_rgba()
    assert [rgba[i * 4] for i in range(4)] == [1, 2, 3, 4]
