"""How many new spells a spontaneous caster *knows* on gaining a class level.

A spontaneous caster (Bard, Sorcerer, and PRC equivalents) knows a fixed number
of spells per spell level, growing with class level. ``classes.2da`` names the
class's ``SpellKnownTable`` (a ``CLS_SPKN_*``), whose rows are class levels and
whose ``SpellLevel0..9`` columns give the *cumulative* count known at each spell
level. The difference between two class levels is how many new spells the level
lets you learn — the budget the level-up must spend.

Prepared casters (Wizard, Cleric, …) have no such table, so this returns nothing
for them: their spellbooks fill by a different mechanism the editor edits directly.
"""

from __future__ import annotations

from typing import Protocol


class _Reader(Protocol):
    def read_2da(self, name: str) -> dict[int, dict[str, str]] | None: ...


def _col(row: dict[str, str], name: str) -> str:
    for key, value in row.items():
        if key.lower() == name.lower():
            return value
    return ""


def _is_set(value: str) -> bool:
    return value not in ("", "****")


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def spells_known_gained(
    reader: _Reader, class_id: int, prev_class_level: int, new_class_level: int
) -> dict[int, int]:
    """``{spell level: count}`` of new spells this class level lets you learn.

    Empty when the class has no ``SpellKnownTable`` (not a spontaneous caster) or
    the level adds none.
    """
    classes = reader.read_2da("classes") or {}
    row = classes.get(class_id)
    if row is None:
        return {}
    table_name = _col(row, "SpellKnownTable")
    if not _is_set(table_name):
        return {}
    table = reader.read_2da(table_name.lower()) or {}

    def known_at(class_level: int, spell_level: int) -> int:
        if class_level < 1:
            return 0
        entry = table.get(class_level - 1)  # rows are 0-indexed by class level
        return _to_int(_col(entry, f"SpellLevel{spell_level}")) if entry else 0

    out: dict[int, int] = {}
    for spell_level in range(10):
        gained = known_at(new_class_level, spell_level) - known_at(prev_class_level, spell_level)
        if gained > 0:
            out[spell_level] = gained
    return out
