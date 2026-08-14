"""Which skills are *class* skills for a character, and the rank cap that follows.

A skill's maximum rank depends on whether it is a class skill for the character:
a class skill caps at ``character level + 3``, a cross-class skill at half that.
The save stores only ranks, not which skills are class skills — but the class
tables do: each class in ``classes.2da`` names a ``CLS_SKILL_*`` table marking
its class skills, and a skill is a class skill for the *character* if any one of
its classes treats it so. This reads that from an install's 2das, so the cap can
be right per skill instead of using the generous class-skill bound for everything.
"""

from __future__ import annotations

from collections.abc import Iterable
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


def _to_int(value: str, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def class_skill_ids(reader: _Reader, class_ids: Iterable[int]) -> set[int]:
    """The set of skill ids that are class skills for *any* of ``class_ids``.

    Empty when the class tables cannot be read — the caller then falls back to the
    generous class-skill cap, never a wrongly tight one.
    """
    classes = reader.read_2da("classes") or {}
    out: set[int] = set()
    seen_tables: dict[str, set[int]] = {}
    for class_id in class_ids:
        row = classes.get(class_id)
        if row is None:
            continue
        table = _col(row, "SkillsTable")
        if not _is_set(table):
            continue
        key = table.lower()
        if key not in seen_tables:
            cs = reader.read_2da(key) or {}
            seen_tables[key] = {
                idx
                for r in cs.values()
                if _col(r, "ClassSkill") == "1" and (idx := _to_int(_col(r, "SkillIndex"))) >= 0
            }
        out |= seen_tables[key]
    return out


def skill_rank_cap(character_level: int, *, class_skill: bool) -> int:
    """The highest rank a skill may reach: ``level + 3`` for a class skill, half
    that (rounded down) for a cross-class skill. Never below the level-1 values."""
    full = max(3, character_level + 3)
    return full if class_skill else max(1, full // 2)
