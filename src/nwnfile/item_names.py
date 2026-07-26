"""Resolve base-item names that a ``.bic`` stores only as a ``dialog.tlk`` StrRef.

Standard game items (rings, potions, containers …) carry no inline
``LocalizedName`` — just a StrRef into the game's talk table. The reader records
that as :attr:`InventoryItem.name_strref`; this looks it up in ``dialog.tlk`` from
the game install so "(unnamed: nw_it_mring030)" becomes "Ring of Nine Lives".

StrRefs below ``0x01000000`` are base strings in ``dialog.tlk``; higher ones belong
to a module's custom tlk (not resolved here — those items keep the resref
fallback). Resolution is best-effort: with no install/tlk, names are unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

from vaultkeeper.core.formats.bic_reader import CharacterInfo, InventoryItem
from vaultkeeper.core.formats.tlk_reader import CUSTOM_TLK_BASE, TlkReader, TlkTable

_DIALOG_LANGS = ("en", "de", "fr", "it", "es", "pl")
_tlk_cache: dict[Path, TlkTable | None] = {}

_DATA_DIR = Path(__file__).resolve().parent / "data"
BASE_ITEM_NAMES_FILE = "Base Item Names.json"
_base_item_names: dict[int, str] | None = None


def default_base_item_names() -> dict[int, str]:
    """Bundled base item type names (``baseitems.2da`` id -> name), cached."""
    global _base_item_names
    if _base_item_names is None:
        path = _DATA_DIR / BASE_ITEM_NAMES_FILE
        _base_item_names = {}
        if path.is_file():
            for key, name in json.loads(path.read_text(encoding="utf-8")).items():
                try:
                    _base_item_names[int(key)] = name
                except (TypeError, ValueError):
                    continue
    return _base_item_names


def base_item_type(base_item: int) -> str | None:
    """The item-type name for a ``BaseItem`` id (e.g. 52 -> "Ring"), or ``None``."""
    return default_base_item_names().get(base_item)


def _dialog_tlk_path(game_root: Path) -> Path | None:
    """Locate ``dialog.tlk`` under a game install (EE ``lang/<l>/data`` or classic)."""
    for lang in _DIALOG_LANGS:
        candidate = game_root / "lang" / lang / "data" / "dialog.tlk"
        if candidate.is_file():
            return candidate
    classic = game_root / "dialog.tlk"
    return classic if classic.is_file() else None


def _load_tlk(path: Path | None) -> TlkTable | None:
    if path is None:
        return None
    if path not in _tlk_cache:
        _tlk_cache[path] = TlkReader().read(path)
    return _tlk_cache[path]


class ItemNameResolver:
    """Fills in item names from a base ``dialog.tlk`` (StrRef -> string)."""

    def __init__(self, base_tlk: TlkTable | None) -> None:
        self._base = base_tlk

    @property
    def available(self) -> bool:
        return self._base is not None

    def name_for(self, strref: int) -> str | None:
        if strref < 0 or strref >= CUSTOM_TLK_BASE or self._base is None:
            return None
        text = self._base.get(strref)
        return text or None

    def resolve_items(self, items: list[InventoryItem]) -> None:
        """Replace tlk-only names with their resolved string (recurses containers)."""
        for item in items:
            if item.name_strref >= 0:
                resolved = self.name_for(item.name_strref)
                if resolved:
                    item.name = resolved
            self.resolve_items(item.contents)

    def resolve_character(self, info: CharacterInfo) -> None:
        self.resolve_items([entry.item for entry in info.equipped_items])
        self.resolve_items(info.inventory_items)


def resolver_for(game_root: Path | None) -> ItemNameResolver:
    """An :class:`ItemNameResolver` backed by the install's ``dialog.tlk`` (cached)."""
    path = _dialog_tlk_path(game_root) if game_root else None
    return ItemNameResolver(_load_tlk(path))
