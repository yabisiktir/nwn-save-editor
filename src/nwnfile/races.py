"""Racial ability adjustments from ``racialtypes.2da``.

A save stores a character's abilities as **base scores, without the racial
adjustment** — the engine adds it when the character loads. So a sheet that shows
the stored number alone reads low against the game's, by exactly the amount in
this table.

The columns are not in the order anyone expects: ``StrAdjust DexAdjust IntAdjust
ChaAdjust WisAdjust ConAdjust`` — Int and Cha come *before* Wis and Con. They are
read by header name here for that reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from nwnfile.hak_stack import HakStack

#: The save's ability field names, in the order a character sheet lists them.
ABILITY_FIELDS: tuple[str, ...] = ("Str", "Dex", "Con", "Int", "Wis", "Cha")

_ADJUST_COLUMN = {
    "Str": "StrAdjust",
    "Dex": "DexAdjust",
    "Con": "ConAdjust",
    "Int": "IntAdjust",
    "Wis": "WisAdjust",
    "Cha": "ChaAdjust",
}


@dataclass
class RaceTable:
    """``racialtypes.2da`` as resolved for one save's hak list."""

    stack: HakStack

    def __post_init__(self) -> None:
        self._rows: dict[int, dict[str, str]] | None = None
        self._loaded = False

    def _table(self) -> dict[int, dict[str, str]]:
        if not self._loaded:
            self._rows = self.stack.read_2da("racialtypes")
            self._loaded = True
        return self._rows or {}

    @property
    def available(self) -> bool:
        return bool(self._table())

    @property
    def row_count(self) -> int:
        return len(self._table())

    def has_race(self, race_id: int) -> bool:
        return race_id in self._table()

    def label(self, race_id: int) -> str:
        """The 2DA ``Label`` — a plain name, unlike ``Name`` which is a TLK id."""
        row = self._table().get(race_id) or {}
        label = row.get("Label", "")
        return "" if label in ("", "****") else label.replace("_", " ")

    def adjustments(self, race_id: int) -> dict[str, int]:
        """``{ability field: adjustment}`` for the races that state one."""
        row = self._table().get(race_id)
        if row is None:
            return {}
        out: dict[str, int] = {}
        for field, column in _ADJUST_COLUMN.items():
            raw = row.get(column, "")
            if raw in ("", "****"):
                continue
            try:
                value = int(raw)
            except ValueError:
                continue
            if value:
                out[field] = value
        return out
