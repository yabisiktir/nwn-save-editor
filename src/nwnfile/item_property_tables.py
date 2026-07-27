"""Read the NWN ``iprp_*`` tables so any item property can be edited *safely*.

A property struct stores three raw numbers that only mean something via lookup
tables:

* ``Subtype`` — a row in the property's *subtype* 2da (which ability, which spell,
  which damage type …), named by ``itempropdef.2da``'s ``SubTypeResRef``.
* ``CostValue`` — a row in the property's *cost* 2da (``+5``, ``1d6``, ``5
  Charges/Use``, ``50%`` …); the ``CostTable`` field indexes ``iprp_costtable.2da``
  which names that 2da.
* ``Param1`` — a row in the property's ``Param1ResRef`` 2da (rare).

This reader resolves each of those into ``{row -> label}`` option maps, so the editor
can present only valid choices — you can never store an out-of-range value that would
corrupt the item. PRC's extended tables (in ``prc8_2das.hak``) are read in preference
to the base game, so PRC properties/spells/feats are covered too. The huge feat/spell
subtype tables reuse the bundled maps in :mod:`vaultkeeper.game.item_properties`.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from vaultkeeper.core.formats.erf_reader import ErfReader
from vaultkeeper.core.formats.key_bif_reader import KeyBifReader

_2DA_RESTYPE = 2017
#: property ids whose subtype table is huge / PRC-extended — reuse bundled maps.
_BUNDLED_SUBTYPES = {12: "_feats", 15: "_spells", 82: "_onhit_spells", 52: "_skills", 29: "_skills"}


def parse_2da(text: str) -> tuple[list[str], dict[int, dict[str, str]]]:
    """Parse a 2DA into ``(header, {row_index: {column: value}})``."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip().startswith("2DA"):
        i += 1
    i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    header = lines[i].split() if i < len(lines) else []
    rows: dict[int, dict[str, str]] = {}
    for line in lines[i + 1:]:
        if not line.strip():
            continue
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        if not parts or not parts[0].isdigit():
            continue
        rows[int(parts[0])] = dict(zip(header, parts[1:], strict=False))
    return header, rows


class ItemPropertyTables:
    """Resolves valid subtype / cost / param options for item properties."""

    def __init__(self, game_root: Path | None, hak_path: Path | None = None, tlk=None) -> None:
        self._kb = KeyBifReader.for_install(game_root)
        self._hak = hak_path if hak_path is not None and hak_path.is_file() else None
        self._erf = ErfReader()
        self._tlk = tlk
        self._cache: dict[str, dict[int, dict[str, str]] | None] = {}

    @classmethod
    def for_install(cls, game_root: Path | None, hak_dir: Path | None = None) -> ItemPropertyTables:
        """Build from an install, preferring ``prc8_2das.hak`` + the base ``dialog.tlk``."""
        hak_path = None
        if hak_dir is not None:
            candidate = hak_dir / "prc8_2das.hak"
            hak_path = candidate if candidate.is_file() else None
        tlk = None
        if game_root is not None:
            from vaultkeeper.game.item_names import _dialog_tlk_path, _load_tlk

            tlk = _load_tlk(_dialog_tlk_path(game_root))
        return cls(game_root, hak_path, tlk)

    @property
    def available(self) -> bool:
        return self._read("iprp_costtable") is not None

    # -- option maps ------------------------------------------------------ #
    def cost_options(self, cost_table: int) -> dict[int, str]:
        """Valid ``CostValue`` rows + labels for a property's ``CostTable`` id."""
        costtable = self._read("iprp_costtable")
        if costtable is None or cost_table not in costtable:
            return {}
        name = costtable[cost_table].get("Name", "****")
        return self._label_map(name)

    def subtype_options(self, property_name: int) -> dict[int, str] | None:
        """Valid ``Subtype`` rows + labels for a property, or ``None`` if it has none."""
        if property_name in _BUNDLED_SUBTYPES:
            from vaultkeeper.game import item_properties

            return dict(getattr(item_properties, _BUNDLED_SUBTYPES[property_name])())
        subtype_ref = self._def(property_name, "SubTypeResRef")
        return self._label_map(subtype_ref) if subtype_ref else None

    def param1_options(self, property_name: int) -> dict[int, str] | None:
        """Valid ``Param1`` rows + labels for a property, or ``None`` if it has none."""
        param_ref = self._def(property_name, "Param1ResRef")
        return self._label_map(param_ref) if param_ref else None

    def property_name_label(self, property_name: int) -> str | None:
        """The property type's own name from ``itempropdef.2da`` (Label column)."""
        label = self._def(property_name, "Label")
        return label.replace("_", " ") if label else None

    # -- internals -------------------------------------------------------- #
    def _def(self, property_name: int, column: str) -> str | None:
        table = self._read("itempropdef")
        row = table.get(property_name) if table else None
        value = row.get(column) if row else None
        return value if value and value != "****" else None

    def _label_map(self, resref: str | None) -> dict[int, str]:
        if not resref or resref == "****":
            return {}
        table = self._read(resref.lower())
        if table is None:
            return {}
        return {index: self._row_label(row, index) for index, row in table.items()}

    def _row_label(self, row: dict[str, str], index: int) -> str:
        name = row.get("Name", "****")
        if name.isdigit() and self._tlk is not None:
            text = self._tlk.get(int(name))
            if text:
                return text
        label = row.get("Label", "")
        return label.replace("_", " ") if label and label != "****" else str(index)

    def _read(self, name: str) -> dict[int, dict[str, str]] | None:
        if name not in self._cache:
            text: str | None = None
            if self._hak is not None:
                res = self._erf.find_resource(self._hak, name, res_type=_2DA_RESTYPE)
                if res is not None:
                    text = self._erf.read_resource_bytes(self._hak, res).decode("latin-1")
            if text is None and self._kb is not None:
                text = self._kb.read_2da_text(name)
            self._cache[name] = parse_2da(text)[1] if text else None
        return self._cache[name]
