"""Which properties the game lets an item keep, and a per-save fix when it won't.

NWN checks an item's properties against ``itemprops.2da`` when it loads a
character: each base item names a column there (``baseitems.2da``
``PropColumn``), and a property whose cell in that column is ``****`` is **removed
on load**. Custom-content packs disagree about those cells. Every CEP version lets a
Torch carry bonus feats, spell slots, immunities…; PRC8's ``prc8_2das.hak`` keeps
the base game's "Light only". So SoF3's Holy Symbol of Thoth (a Torch) keeps its 18
properties in a PRC+CEP2 module and is cut to Light the first time the character
loads into a module whose top ``itemprops.2da`` is PRC's. Nothing in the save
records this; the properties are simply gone.

This module (Qt-free) answers "will this save's rules strip it?"
(:class:`ItemRules`, :func:`blocked_properties`), and builds the fix: a copy of the
save's *own* winning ``itemprops.2da`` with only the needed cells switched on
(:func:`patch_itemprops`), packed as a tiny hak meant for the **top** of the save's
``Mod_HakList`` so it outranks PRC's copy (:func:`build_rules_hak`). Every other
cell keeps the value the save already uses.
"""
from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Iterable
from pathlib import Path

from nwnfile.formats.erf_writer import build_hak

_2DA = 2017
_MANIFEST = "vk_itemrule_haks.json"
_TOKEN = re.compile(r'"[^"]*"|\S+')


class ItemRules:
    """``baseitems.2da`` + ``itemprops.2da`` as the save's module resolves them."""

    def __init__(self, baseitems: dict | None, itemprops: dict | None) -> None:
        self._baseitems = baseitems or {}
        self._itemprops = itemprops or {}
        header = next(iter(self._itemprops.values()), {})
        #: "20" -> "20_Torch": itemprops' columns are named "<PropColumn>_<label>"
        self._columns = {c.split("_", 1)[0]: c for c in header if c[:1].isdigit()}

    @classmethod
    def from_stack(cls, stack) -> ItemRules:
        """From a :class:`nwnfile.hak_stack.HakStack` (haks first, then base)."""
        return cls(stack.read_2da("baseitems"), stack.read_2da("itemprops"))

    @property
    def known(self) -> bool:
        return bool(self._baseitems and self._itemprops)

    def column(self, base_item: int) -> str | None:
        """The ``itemprops.2da`` column for a base item, e.g. ``"20_Torch"``."""
        row = self._baseitems.get(base_item) or {}
        return self._columns.get(str(row.get("PropColumn", "")).strip())

    def base_item_label(self, base_item: int) -> str:
        row = self._baseitems.get(base_item) or {}
        label = str(row.get("label") or row.get("Label") or "").replace("_", " ").strip()
        return label.title() if label and label != "****" else f"base item {base_item}"

    def allows(self, base_item: int, property_name: int) -> bool:
        """Whether an item of this base type keeps this property on load. Unknown
        (tables unreadable, row/column missing) counts as allowed: only a definite
        ``****`` is reported, never a guess."""
        column = self.column(base_item)
        row = self._itemprops.get(property_name)
        if column is None or row is None:
            return True
        return str(row.get(column, "")).strip() not in ("****", "")


def blocked_properties(base_item: int, props: Iterable, rules: ItemRules) -> list:
    """The properties in ``props`` that ``rules`` would strip from this base item."""
    return [p for p in props if not rules.allows(base_item, p.property_name)]


def patch_itemprops(text: str, cells: Iterable[tuple[int, str]]) -> str:
    """``text`` (an ``itemprops.2da``) with each ``(row, column)`` cell set to ``1``.

    Only the named cells change; every other byte of those rows and every other row
    is kept, so the result is the save's own table plus exactly the allowances
    asked for."""
    wanted: dict[int, set[str]] = {}
    for row, column in cells:
        wanted.setdefault(int(row), set()).add(column)
    lines = text.split("\n")
    header_at = _header_index(lines)
    if header_at is None:
        raise ValueError("not a 2DA: no column header")
    header = lines[header_at].split()
    for i in range(header_at + 1, len(lines)):
        tokens = list(_TOKEN.finditer(lines[i]))
        if not tokens or not tokens[0].group().isdigit():
            continue
        columns = wanted.get(int(tokens[0].group()))
        if not columns:
            continue
        line = lines[i]
        # right-to-left so earlier spans stay valid while later ones are replaced
        for name in sorted(columns, key=header.index, reverse=True):
            at = header.index(name) + 1  # +1: the row-number token
            if at < len(tokens):
                tok = tokens[at]
                line = line[:tok.start()] + "1" + line[tok.end():]
        lines[i] = line
    return "\n".join(lines)


def build_rules_hak(itemprops_text: str) -> bytes:
    """A hak holding just ``itemprops.2da``."""
    return build_hak([("itemprops", _2DA, itemprops_text.encode("latin-1"))])


def record_hak(hak_dir: Path, name: str) -> None:
    """Remember a rules hak this editor wrote (``vk_itemrule_haks.json``)."""
    path = Path(hak_dir) / _MANIFEST
    names: list[str] = []
    with contextlib.suppress(OSError, ValueError):
        names = list(json.loads(path.read_text(encoding="utf-8")))
    if name not in names:
        names.append(name)
    path.write_text(json.dumps(names, indent=2), encoding="utf-8")


def _header_index(lines: list[str]) -> int | None:
    i = 0
    while i < len(lines) and not lines[i].strip().startswith("2DA"):
        i += 1
    i += 1
    while i < len(lines) and (not lines[i].strip()
                              or lines[i].strip().upper().startswith("DEFAULT")):
        i += 1
    return i if i < len(lines) else None
