"""Resolve an item's inventory icon (a TGA) from the installed game data.

An item's picture is derived from its ``BaseItem`` (baseitems.2da row) and its
``ModelPart1``. Simple items (``ModelType`` 0 — rings, potions, containers …) have a
per-variant icon ``i<ItemClass>_<ModelPart1:03d>``; anything else (weapons, armour)
uses the base item's ``DefaultIcon`` (a per-type picture). Both are TGA resources in
the base game's BIF archives, read with :class:`KeyBifReader` (so this needs the
install; it degrades to "no icon" without it).

Custom content (CEP/PRC) ships its own item-icon variants inside haks — also TGA.
When a ``hak_dir`` is given (opt-in, it is slower), those haks are indexed once and
searched as a fallback, so e.g. a ring's exact ``iit_ring_100`` from ``cep2_core5``
is used instead of the generic base ``iit_ring``.

Returns raw TGA bytes — the Qt conversion to a pixmap lives in the UI.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from nwnfile.formats.erf_reader import ErfReader, ErfResource
from nwnfile.formats.key_bif_reader import KeyBifReader

_TGA_RES_TYPE = 3
_MAX_RESREF = 16


class ItemIconSource:
    """Looks up item inventory icons (TGA bytes) from the install, cached."""

    def __init__(self, game_root: Path | None, hak_dir: Path | None = None) -> None:
        self._reader = KeyBifReader.for_install(game_root)
        #: base item id -> (ItemClass, DefaultIcon, ModelType)
        self._base_items: dict[int, tuple[str, str, int]] = {}
        self._cache: dict[tuple[int, int], bytes | None] = {}
        self._image_cache: dict[tuple[int, int], object] = {}
        self._palette_cache: dict[str, object] | None = None
        #: opt-in hak icon search: resref -> (hak path, resource), built lazily.
        self._hak_dir = hak_dir if hak_dir is not None and hak_dir.is_dir() else None
        self._hak_index: dict[str, tuple[Path, ErfResource]] | None = None
        self._erf = ErfReader()
        if self._reader is not None:
            self._load_base_items()

    @property
    def available(self) -> bool:
        return bool(self._base_items)

    def _load_base_items(self) -> None:
        text = self._reader.read_2da_text("baseitems") if self._reader else None
        if text is None:
            return
        lines = text.splitlines()
        start = next(n for n, line in enumerate(lines) if line.strip().startswith("2DA")) + 1
        while start < len(lines) and not lines[start].strip():
            start += 1
        header = lines[start].split()
        for line in lines[start + 1:]:
            if not line.strip():
                continue
            try:
                parts = shlex.split(line)
            except ValueError:
                parts = line.split()
            if not parts or not parts[0].isdigit():
                continue
            # parts[0] is the row index; the rest align with the header columns.
            row = dict(zip(header, parts[1:], strict=False))

            def cell(name: str, cols=row) -> str:
                value = cols.get(name, "****")
                return "" if value == "****" else value

            model_type = cell("ModelType")
            self._base_items[int(parts[0])] = (
                cell("ItemClass"), cell("DefaultIcon"),
                int(model_type) if model_type.isdigit() else -1,
            )

    #: Tintable parts (cloaks, robes) ship a PLT rather than a TGA: it stores no
    #: colour, only a palette index per pixel. See core.formats.plt_reader.
    PLT_RES_TYPE = 6

    def _candidates(self, base_item: int, model_part: int) -> list[str]:
        row = self._base_items.get(base_item)
        if row is None:
            return []
        item_class, default_icon, model_type = row
        candidates: list[str] = []
        if model_type == 0 and item_class:
            candidates.append(f"i{item_class}_{model_part:03d}")
        if default_icon:
            candidates.append(default_icon)
        return [c[:_MAX_RESREF] for c in candidates]

    def _build_hak_index(self) -> None:
        """Index every ``i*`` TGA icon across the hak folder (once, ~0.5s)."""
        index: dict[str, tuple[Path, ErfResource]] = {}
        if self._hak_dir is not None:
            for hak in sorted(self._hak_dir.glob("*.hak")):
                try:
                    info = self._erf.read_info(hak)
                    if info is None or not info.is_valid:
                        continue
                    for res in self._erf.list_resources(hak):
                        if res.res_type == _TGA_RES_TYPE and res.resref.startswith("i"):
                            index.setdefault(res.resref.lower(), (hak, res))
                except Exception:  # noqa: BLE001 — a bad hak just contributes no icons
                    continue
        self._hak_index = index

    def _hak_bytes(self, resref: str) -> bytes | None:
        if self._hak_dir is None:
            return None
        if self._hak_index is None:
            self._build_hak_index()
        entry = self._hak_index.get(resref.lower()) if self._hak_index else None
        if entry is None:
            return None
        hak, res = entry
        try:
            return self._erf.read_resource_bytes(hak, res)
        except Exception:  # noqa: BLE001
            return None

    def icon_image(self, base_item: int, model_part: int):
        """An item's icon as a decoded ``TGAImage``, or ``None``.

        Handles both of the formats the game uses: a plain TGA, or a PLT that has
        to be coloured through the palette textures first.
        """
        from nwnfile.formats.tga_reader import TGAReader

        key = (base_item, model_part)
        if key not in self._image_cache:
            image = None
            data = self.icon_bytes(base_item, model_part)
            if data is not None:
                image = TGAReader().read_bytes(data)
            if image is None:
                image = self._plt_image(base_item, model_part)
            self._image_cache[key] = image
        return self._image_cache[key]

    def _plt_image(self, base_item: int, model_part: int):
        """Decode and colour the PLT icon for an item, if it has one."""
        from nwnfile.formats.plt_reader import (
            LAYER_PALETTES,
            colour_plt,
            read_plt,
        )

        if self._reader is None:
            return None
        for resref in self._candidates(base_item, model_part):
            raw = self._reader.read(resref, self.PLT_RES_TYPE)
            plt = read_plt(raw) if raw else None
            if plt is not None:
                return colour_plt(plt, self._palettes(LAYER_PALETTES))
        return None

    def _palettes(self, names) -> dict:
        """The palette textures a PLT needs, decoded once."""
        from nwnfile.formats.tga_reader import TGAReader

        if self._palette_cache is None:
            self._palette_cache = {}
            for name in set(names):
                raw = self._reader.read(name, _TGA_RES_TYPE) if self._reader else None
                self._palette_cache[name] = TGAReader().read_bytes(raw) if raw else None
        return self._palette_cache

    def icon_bytes(self, base_item: int, model_part: int) -> bytes | None:
        """Raw TGA bytes for an item's icon (cached), or ``None`` if not found.

        Each candidate resref is tried in the base game first, then (if a hak
        folder was supplied) in the haks — so a custom per-variant icon beats the
        generic base fallback.
        """
        key = (base_item, model_part)
        if key not in self._cache:
            data = None
            for resref in self._candidates(base_item, model_part):
                if self._reader is not None:
                    data = self._reader.read(resref, _TGA_RES_TYPE)
                if data is None:
                    data = self._hak_bytes(resref)
                if data is not None:
                    break
            self._cache[key] = data
        return self._cache[key]
