"""Turning decoded game images into Qt objects.

:mod:`nwnfile` decodes TGA and PLT into plain pixel buffers and stays free of Qt,
so the conversion has to live above it. It sits here because the editor needs it
and Vaultkeeper depends on the editor — putting it the other way round would have
the file layer's only consumers importing each other.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage, QPixmap

#: The portrait preview box the character viewer defaults to.
DEFAULT_PORTRAIT_BOX = 128


def crop_portrait(pixmap: QPixmap) -> QPixmap:
    """Trim a portrait's power-of-two padding — the flat shelf under the face.

    The picture is 64x100 inside a 64x128 file; without this every portrait is
    shown sitting on a band of whatever colour its bottom row happens to be.
    """
    from nwnfile.portrait_images import art_height

    height = art_height(pixmap.width(), pixmap.height())
    return (
        pixmap if height >= pixmap.height()
        else pixmap.copy(0, 0, pixmap.width(), height)
    )


def _pixmap(image) -> QPixmap | None:
    """A QPixmap from a decoded image, or ``None`` if it is not usable."""
    if image is None or image.width <= 0 or image.height <= 0:
        return None
    qimg = QImage(
        image.to_rgba(), image.width, image.height, QImage.Format.Format_RGBA8888
    )
    return None if qimg.isNull() else QPixmap.fromImage(qimg)


def tga_to_pixmap(path: Path, *, box: int = DEFAULT_PORTRAIT_BOX) -> QPixmap | None:
    """Load a TGA portrait scaled to fit ``box`` (``None`` on failure)."""
    from nwnfile.formats.tga_reader import TGAReader

    pixmap = _pixmap(TGAReader().read_file(path))
    if pixmap is None:
        return None
    pixmap = crop_portrait(pixmap)
    return pixmap.scaled(
        box, box,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def load_item_icon(source, item, *, female: bool = False) -> QIcon | None:
    """An item's inventory icon as a QIcon (``None`` if unavailable).

    The source handles both formats — a plain TGA, or a PLT coloured through the
    game's palette textures, which cloaks and other tintable parts ship instead.

    Armour is pictured as the torso it puts on the wearer, so it needs the parts
    off the item *and* whose body they are drawn on — pass ``female`` for a woman's
    character, or every suit shows the man's cut of it.
    """
    pixmap = _pixmap(source.icon_image(
        item.base_item,
        item.model_part,
        model_part2=getattr(item, "model_part2", 0),
        model_part3=getattr(item, "model_part3", 0),
        armor_torso=getattr(item, "armor_torso", 0),
        armor_robe=getattr(item, "armor_robe", 0),
        female=female,
    ))
    return None if pixmap is None else QIcon(pixmap)


def item_icon_source(host):
    """An ``ItemIconSource`` over the host's game install.

    With the host's ``hak_item_icons`` setting on, the user's hak folder is
    searched too — opt-in, because the first lookup scans every hak. With
    ``exact_item_icons`` off, no per-variant icon is worked out at all and every
    item of a type shows that type's one default picture.
    """
    from nwnfile.item_icons import icon_source_for

    ctx = getattr(host, "ctx", None)
    game_root = getattr(ctx, "game_root", None)
    hak_dir = None
    settings = host._settings() if hasattr(host, "_settings") else None
    if getattr(settings, "hak_item_icons", False):
        user_dir = getattr(ctx, "game_user_dir", None)
        if user_dir is not None:
            hak_dir = user_dir / "hak"
    # Keyed on the install: it indexes the game's KEY/BIF (and every hak when
    # the setting is on), which is much too slow to redo per window.
    exact = getattr(settings, "exact_item_icons", True)
    return icon_source_for(game_root, hak_dir, exact)
