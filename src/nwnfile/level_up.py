"""Work out what gaining a level in a class grants, from the class 2das.

Adding a class level is far more than ``ClassLevel += 1``: the level brings hit
points, base-attack and saving-throw gains, a skill-point budget, sometimes a
feat, and — for casters — spell slots. The engine reads all of it from the class
tables, so it can be recomputed here for base *and* PRC classes without running
the game.

This is the calculation only. Applying it (writing ClassList/XP/HP/…), the level
cap and consistency guards, and the choices a player makes (which skills, which
feat) sit on top of :class:`LevelGains`. A PRC class computes just like a base
one, but its *script-managed* features — a prestige caster's spellbook, on-hit or
skin class abilities — are not character data and do not come from this: the data
will be right, and the caller flags what still needs an in-game re-level.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class LevelGains:
    """Everything one class level grants. Deterministic gains are values; the
    choices a player makes are surfaced as a budget (``skill_points``) or a flag
    (``general_feat`` / ``ability_increase``)."""

    class_id: int
    class_name: str
    class_level: int  # the new level *in this class* (1-based)
    character_level: int  # the new *total* character level
    hit_die: int
    bab_gain: int
    fort_gain: int
    ref_gain: int
    will_gain: int
    skill_point_base: int  # class SkillPointBase, before Int mod / the level-1 x4
    granted_feats: tuple[tuple[int, str], ...]  # (feat id, label) auto-granted here
    general_feat: bool  # a general feat is due (every 3rd character level)
    ability_increase: bool  # an ability point is due (every 4th character level)
    is_base_class: bool  # False => PRC/custom, whose script features need in-game
    spellcaster: bool  # has a spell-gain/known table (spells to sort out)

    def skill_points(self, int_modifier: int) -> int:
        """Skill points this level grants: ``max(1, base + Int)`` — quadrupled at
        the character's very first level, as D&D does."""
        per = max(1, self.skill_point_base + int_modifier)
        return per * 4 if self.character_level == 1 else per

    def hit_points(self, con_modifier: int, *, rule: str = "max") -> int:
        """HP this level grants. The first character level always takes the full
        hit die; after that ``rule`` is ``"max"`` or ``"average"`` (round up).
        Never below 1, as the engine floors it."""
        full = self.character_level == 1 or rule == "max"
        roll = self.hit_die if full else self.hit_die // 2 + 1
        return max(1, roll + con_modifier)


class LevelUpCalculator:
    """Compute :class:`LevelGains` from an install's class tables.

    Tables are cached on the instance, so reuse one calculator across a run.
    """

    def __init__(self, reader: _Reader) -> None:
        self._reader = reader
        self._classes: dict[int, dict[str, str]] | None = None
        self._feats: dict[int, dict[str, str]] | None = None
        self._base_class_ids: set[int] | None = None
        self._tables: dict[str, dict[int, dict[str, str]] | None] = {}

    def _class_table(self) -> dict[int, dict[str, str]]:
        if self._classes is None:
            self._classes = self._reader.read_2da("classes") or {}
        return self._classes

    def _feat_table(self) -> dict[int, dict[str, str]]:
        if self._feats is None:
            self._feats = self._reader.read_2da("feat") or {}
        return self._feats

    def _table(self, name: str) -> dict[int, dict[str, str]] | None:
        key = name.lower()
        if key not in self._tables:
            self._tables[key] = self._reader.read_2da(key)
        return self._tables[key]

    def _base_classes(self) -> set[int]:
        if self._base_class_ids is None:
            reader = getattr(self._reader, "read_base_2da", None)
            table = reader("classes") if callable(reader) else None
            self._base_class_ids = set(table) if table else set()
        return self._base_class_ids

    def _column_delta(self, table_name: str, level: int, column: str) -> int:
        """A per-level column's increase from ``level - 1`` to ``level``.

        Rows are 0-indexed by class level (row 0 = level 1), so the value *at*
        ``level`` is row ``level - 1``. Below level 1 the contribution is 0.
        """
        table = self._table(table_name)
        if not table or level < 1:
            return 0
        now = _to_int(_col(table.get(level - 1, {}), column))
        before = _to_int(_col(table.get(level - 2, {}), column)) if level > 1 else 0
        return now - before

    def _granted_feats(
        self, feats_table: str, level: int
    ) -> tuple[tuple[int, str], ...]:
        """Feats the class grants automatically at exactly this class level."""
        table = self._table(feats_table)
        if not table:
            return ()
        out: list[tuple[int, str]] = []
        for row in table.values():
            if _to_int(_col(row, "GrantedOnLevel"), -1) != level:
                continue
            feat_id = _to_int(_col(row, "FeatIndex"), -1)
            if feat_id < 0:
                continue
            label = _col(self._feat_table().get(feat_id, {}), "LABEL").replace("_", " ")
            out.append((feat_id, label or _col(row, "FeatLabel").replace("_", " ")))
        return tuple(out)

    def gains(
        self, class_id: int, new_class_level: int, *, character_level: int
    ) -> LevelGains | None:
        """What gaining ``new_class_level`` in ``class_id`` grants, or ``None`` if
        the class is not in this install.

        ``character_level`` is the new *total* level after the gain — it drives the
        every-third-level feat and every-fourth-level ability point, which are
        character-wide, not per class.
        """
        row = self._class_table().get(class_id)
        if row is None:
            return None
        atk = _col(row, "AttackBonusTable")
        sav = _col(row, "SavingThrowTable")
        level = new_class_level
        return LevelGains(
            class_id=class_id,
            class_name=_col(row, "Label").replace("_", " "),
            class_level=level,
            character_level=character_level,
            hit_die=_to_int(_col(row, "HitDie")),
            bab_gain=self._column_delta(atk, level, "BAB"),
            fort_gain=self._column_delta(sav, level, "FortSave"),
            ref_gain=self._column_delta(sav, level, "RefSave"),
            will_gain=self._column_delta(sav, level, "WillSave"),
            skill_point_base=_to_int(_col(row, "SkillPointBase")),
            granted_feats=self._granted_feats(_col(row, "FeatsTable"), level),
            general_feat=character_level % 3 == 0,
            ability_increase=character_level % 4 == 0,
            is_base_class=class_id in self._base_classes(),
            spellcaster=_is_set(_col(row, "SpellGainTable"))
            or _is_set(_col(row, "SpellKnownTable")),
        )
