"""Whether a character meets a feat's prerequisites, from ``feat.2da``.

Each feat row carries its requirements in fixed columns — minimum abilities and
base attack, required feats (``PREREQFEAT1/2``), an "any one of" group
(``OrReqFeat0..4``), skill ranks, a minimum level, a Fortitude minimum, and an
epic flag. As with prestige classes, the game checks these at level-up, not on
load, so a save can hold a feat the character never qualified for; this reads the
same columns so an "applicable feats" filter can be offered when adding one.

Spell-level requirements (``MINSPELLLVL``) are not judged — a save does not make
casting level obvious — so a feat gated only on that is treated as available
rather than wrongly hidden. Reading only, no Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class _Reader(Protocol):
    def read_2da(self, name: str) -> dict[int, dict[str, str]] | None: ...


def _col(row: dict[str, str], name: str) -> str:
    for key, value in row.items():
        if key.lower() == name.lower():
            return value
    return ""


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


#: feat.2da minimum-ability columns -> the ability key used in a character snapshot.
_ABILITY_COLUMNS = {
    "MINSTR": "Str", "MINDEX": "Dex", "MINCON": "Con",
    "MININT": "Int", "MINWIS": "Wis", "MINCHA": "Cha",
}


@dataclass(frozen=True)
class FeatSnapshot:
    """The parts of a character a feat prerequisite is judged against."""

    feats: frozenset[int] = frozenset()
    abilities: dict[str, int] = field(default_factory=dict)  # "Str"… -> score in play
    skills: dict[int, int] = field(default_factory=dict)  # skill index -> rank
    bab: int = 0
    level: int = 0
    fort_save: int = 0


def meets_prerequisites(reader: _Reader, feat_id: int, character: FeatSnapshot) -> bool:
    """True when ``character`` meets every prerequisite ``feat.2da`` states for
    ``feat_id`` that a save can judge (an unknown feat is treated as available)."""
    row = (reader.read_2da("feat") or {}).get(feat_id)
    if row is None:
        return True

    bab = _to_int(_col(row, "MINATTACKBONUS"))
    if bab and character.bab < bab:
        return False
    for column, key in _ABILITY_COLUMNS.items():
        need = _to_int(_col(row, column))
        if need and character.abilities.get(key, 0) < need:
            return False
    for column in ("PREREQFEAT1", "PREREQFEAT2"):
        required = _col(row, column)
        if required not in ("", "****") and _to_int(required) not in character.feats:
            return False
    or_feats = [
        _to_int(_col(row, f"OrReqFeat{i}"))
        for i in range(5)
        if _col(row, f"OrReqFeat{i}") not in ("", "****")
    ]
    if or_feats and not any(f in character.feats for f in or_feats):
        return False
    for skill_col, rank_col in (("REQSKILL", "ReqSkillMinRanks"),
                                ("REQSKILL2", "ReqSkillMinRanks2")):
        skill = _col(row, skill_col)
        if skill not in ("", "****") and (
            character.skills.get(_to_int(skill), 0) < _to_int(_col(row, rank_col))
        ):
            return False
    level = _to_int(_col(row, "MinLevel"))
    if level and character.level < level:
        return False
    fort = _to_int(_col(row, "MinFortSave"))
    if fort and character.fort_save < fort:
        return False
    return not (_col(row, "PreReqEpic") == "1" and character.level < 21)
