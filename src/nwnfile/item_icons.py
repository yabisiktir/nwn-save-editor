"""Resolve an item's inventory icon (a TGA) from the installed game data.

An item's picture is derived from its ``BaseItem`` (baseitems.2da row) and its
``ModelPart1``. Simple items (``ModelType`` 0 — rings, potions, containers …) have a
per-variant icon ``i<ItemClass>_<ModelPart1:03d>``; anything else (weapons, armour)
uses the base item's ``DefaultIcon`` (a per-type picture). Both are TGA resources in
the base game's BIF archives, read with :class:`KeyBifReader` (so this needs the
install; it degrades to "no icon" without it).

Returns raw TGA bytes — the Qt conversion to a pixmap lives in the UI.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from vaultkeeper.core.formats.key_bif_reader import KeyBifReader

_TGA_RES_TYPE = 3
_MAX_RESREF = 16


class ItemIconSource:
    """Looks up item inventory icons (TGA bytes) from the install, cached."""

    def __init__(self, game_root: Path | None) -> None:
        self._reader = KeyBifReader.for_install(game_root)
        #: base item id -> (ItemClass, DefaultIcon, ModelType)
        self._base_items: dict[int, tuple[str, str, int]] = {}
        self._cache: dict[tuple[int, int], bytes | None] = {}
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

    def icon_bytes(self, base_item: int, model_part: int) -> bytes | None:
        """Raw TGA bytes for an item's icon (cached), or ``None`` if not found."""
        key = (base_item, model_part)
        if key not in self._cache:
            data = None
            if self._reader is not None:
                for resref in self._candidates(base_item, model_part):
                    data = self._reader.read(resref, _TGA_RES_TYPE)
                    if data is not None:
                        break
            self._cache[key] = data
        return self._cache[key]
