"""What Strict rule mode enforces, and what it deliberately does not.

Two different kinds of limit get conflated easily, so they are separated here:

* **Storable range** — what the GFF field's type can physically hold. Writing
  outside it does not break a game rule, it corrupts the save, so it is enforced
  in *both* modes. Free mode is for breaking rules, not files.
* **Rule range** — a limit from the game's own rules (a skill's maximum rank,
  current HP not exceeding maximum). Strict enforces these; Free allows them to
  be written verbatim, and the save dialog warns that the game may clamp or
  reject the result on load.

Only rules that can be justified from data actually in the save are encoded. There
is deliberately no cap on ability scores: NWN has no fixed ceiling once items,
levels and templates are involved, so inventing one would block legitimate edits.
"""

from __future__ import annotations

from dataclasses import dataclass

from vaultkeeper.core.formats.gff import GffType


@dataclass(frozen=True)
class Limits:
    """The range an editor should offer, and why it is bounded."""

    minimum: int
    maximum: int
    reason: str = ""

    def clamp(self, value: int) -> int:
        return max(self.minimum, min(self.maximum, value))


#: What each numeric GFF type can hold. Exceeding this corrupts the field.
_STORABLE: dict[GffType, tuple[int, int]] = {
    GffType.BYTE: (0, 255),
    GffType.CHAR: (-128, 127),
    GffType.WORD: (0, 65535),
    GffType.SHORT: (-32768, 32767),
    GffType.DWORD: (0, 4294967295),
    GffType.INT: (-2147483648, 2147483647),
}


def storable_range(gff_type: GffType) -> tuple[int, int] | None:
    """The physical range of a numeric GFF type, or ``None`` if it isn't numeric."""
    return _STORABLE.get(gff_type)


#: Character fields whose *semantic* range is narrower than their storage.
#: Alignment is a 0–100 axis held in a BYTE.
_SEMANTIC: dict[str, tuple[int, int, str]] = {
    "GoodEvil": (0, 100, "alignment runs 0–100"),
    "LawfulChaotic": (0, 100, "alignment runs 0–100"),
}


def skill_rank_limit(level: int) -> int:
    """The highest rank a *class* skill can reach at ``level`` — level + 3.

    Cross-class skills cap at half that, but a save does not record which skills
    are class skills for the character's particular class mix, so the generous
    bound is used: Strict should refuse the impossible, not guess at the merely
    unlikely.
    """
    return max(3, level + 3)


def limits_for(
    field: str,
    gff_type: GffType | None,
    *,
    strict: bool,
    level: int = 0,
    max_hit_points: int = 0,
) -> Limits:
    """The range to offer for a character field under the current rule mode."""
    # `is not None`, not truthiness: GffType.BYTE is 0 and would test as falsy,
    # silently widening every BYTE field to the INT range.
    low, high = (
        _STORABLE.get(gff_type, (0, 2_147_483_647))
        if gff_type is not None
        else (0, 2_147_483_647)
    )
    low = max(low, 0)  # none of the editable character fields are meaningfully negative

    if not strict:
        return Limits(low, high, "Free mode — only the field's storable range applies")

    if field in _SEMANTIC:
        semantic_low, semantic_high, reason = _SEMANTIC[field]
        return Limits(max(low, semantic_low), min(high, semantic_high), reason)
    if field == "CurrentHitPoints" and max_hit_points > 0:
        return Limits(low, min(high, max_hit_points), "current HP cannot exceed maximum HP")
    if field in {"Str", "Dex", "Con", "Int", "Wis", "Cha"}:
        # No rule ceiling exists; the storable range is the honest bound.
        return Limits(max(low, 1), high, "an ability score is at least 1")
    return Limits(low, high)


def skill_limits(*, strict: bool, level: int) -> Limits:
    """The rank range a skill editor should offer."""
    if not strict:
        return Limits(0, 255, "Free mode — only the field's storable range applies")
    cap = skill_rank_limit(level)
    return Limits(0, cap, f"a class skill caps at level + 3 (= {cap})")
