"""Ability scores a class grants as it levels, from its ``StatGainTable``.

Some classes raise an ability simply by advancing. A Red Dragon Disciple gains
Strength at its 2nd, 4th and 10th levels, Constitution at its 7th, Intelligence
at its 9th and Charisma at its 10th. ``classes.2da`` names the table holding
them — ``cls_stat_dradis`` for that class — and each row is one class level.

**None of it is written back into the save.** The stored score stays at what the
character rolled and spent points on; the engine re-adds the class gains, like
the racial adjustment, every time the character loads. A sheet that shows the
stored number therefore reads low by exactly this much, and the discrepancy grows
with every level of such a class.
"""

from __future__ import annotations

from dataclasses import dataclass

from nwnfile.hak_stack import HakStack
from nwnfile.races import ABILITY_FIELDS

#: Column per ability in a ``cls_stat_*`` table. The table spells them in full
#: and uses the same three-letter names the character record does.
_GAIN_COLUMNS = {f: f for f in ABILITY_FIELDS}


@dataclass
class ClassTable:
    """``classes.2da`` plus the per-class stat-gain tables it points at."""

    stack: HakStack

    def __post_init__(self) -> None:
        self._classes: dict[int, dict[str, str]] | None = None
        self._loaded = False
        self._gains: dict[str, dict[int, dict[str, str]] | None] = {}

    def _table(self) -> dict[int, dict[str, str]]:
        if not self._loaded:
            self._classes = self.stack.read_2da("classes")
            self._loaded = True
        return self._classes or {}

    @property
    def available(self) -> bool:
        return bool(self._table())

    def label(self, class_id: int) -> str:
        row = self._table().get(class_id) or {}
        label = row.get("Label", "")
        return "" if label in ("", "****") else label.replace("_", " ")

    def stat_gain_table(self, class_id: int) -> str:
        """The ``cls_stat_*`` table for a class, or ``""`` if it grants nothing."""
        row = self._table().get(class_id) or {}
        name = row.get("StatGainTable", "")
        return "" if name in ("", "****") else name

    def gains(self, class_id: int, level: int) -> dict[str, int]:
        """``{ability: total}`` a class has granted by ``level``.

        Rows are cumulative: each is one class level, and every level up to and
        including the character's has already been taken.
        """
        name = self.stat_gain_table(class_id)
        if not name or level <= 0:
            return {}
        if name not in self._gains:
            self._gains[name] = self.stack.read_2da(name)
        table = self._gains[name]
        if not table:
            return {}
        out: dict[str, int] = {}
        for index, row in table.items():
            # The row's own Level column is authoritative where present: it is
            # what the engine matches on, and a table need not start at 1.
            try:
                row_level = int(row.get("Level", index + 1))
            except (TypeError, ValueError):
                row_level = index + 1
            if row_level > level:
                continue
            for ability, column in _GAIN_COLUMNS.items():
                raw = row.get(column, "")
                if raw in ("", "****"):
                    continue
                try:
                    value = int(raw)
                except ValueError:
                    continue
                if value:
                    out[ability] = out.get(ability, 0) + value
        return out


def character_classes(player) -> list[tuple[int, int]]:
    """``[(class id, level), …]`` from a character's ``ClassList``."""
    field = getattr(player, "fields", {}).get("ClassList")
    if field is None or not hasattr(field.value, "structs"):
        return []
    out: list[tuple[int, int]] = []
    for struct in field.value.structs:
        class_id = struct.get("Class")
        level = struct.get("ClassLevel")
        if class_id is not None and level:
            out.append((int(class_id), int(level)))
    return out
