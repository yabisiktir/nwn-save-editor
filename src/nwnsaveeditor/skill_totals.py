"""Work out what a skill actually comes to, not just its rank.

A save stores only **ranks**. Everything else the character sheet shows — the key
ability's modifier, bonuses from gear — the engine recomputes at runtime, so a
"total" has to be rebuilt here.

What is included is deliberately limited to what can be read straight out of the
save and the game's own tables:

* the **rank** stored in the character's ``SkillList``,
* the **key ability modifier** from ``skills.2da``'s ``KeyAbility`` column,
* **item bonuses** from Skill Bonus / Decreased Skill properties on *equipped*
  items (including the PRC skin, which is where PRC puts its own).

Feat and spell effects are **not** included: reproducing them means running the
game's rules, and a number that is silently short is worse than one that says what
it covers. The UI labels the total accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Item property ids that move a skill (see game.item_properties).
_SKILL_BONUS = 52
_SKILL_PENALTY = 29
#: Equipment slot bits whose items are actually worn — everything but the
#: quiver-style ammunition slots, which do not grant their properties.
_WORN_SLOTS_EXCLUDED = frozenset({2048, 4096, 8192})


@dataclass
class SkillTotal:
    """One skill, broken down the way a character sheet would show it."""

    index: int
    name: str
    rank: int
    ability: str  #: the key ability's short name, e.g. "DEX"
    ability_modifier: int
    item_bonus: int

    @property
    def total(self) -> int:
        return self.rank + self.ability_modifier + self.item_bonus

    @property
    def breakdown(self) -> str:
        parts = [f"{self.rank} rank"]
        if self.ability:
            parts.append(f"{self.ability_modifier:+d} {self.ability}")
        if self.item_bonus:
            parts.append(f"{self.item_bonus:+d} gear")
        return "  ".join(parts)


def ability_modifier(score: int) -> int:
    """D&D's (score - 10) / 2, rounded down."""
    return (score - 10) // 2


def key_abilities(game_root) -> dict[int, str]:
    """``skill index -> key ability`` ("STR", "DEX", …) from ``skills.2da``."""
    if game_root is None:
        return {}
    try:
        from nwnfile.formats.key_bif_reader import KeyBifReader
        from nwnfile.item_property_tables import parse_2da

        text = KeyBifReader.for_install(game_root).read_2da_text("skills")
        if not text:
            return {}
        _headers, rows = parse_2da(text)
    except Exception:
        return {}
    out: dict[int, str] = {}
    for index, row in rows.items():
        ability = (row.get("KeyAbility") or "").strip().upper()
        if ability and ability != "****":
            out[index] = ability
    return out


def item_skill_bonuses(items) -> dict[int, int]:
    """``skill index -> net bonus`` from the properties of *equipped* items."""
    bonuses: dict[int, int] = {}
    for item in items:
        slot = getattr(item, "slot", None)
        if slot is None or slot in _WORN_SLOTS_EXCLUDED:
            continue  # carried items and ammunition grant nothing
        for entry in getattr(item, "properties", []) or []:
            prop = getattr(entry, "prop", entry)
            pid = getattr(prop, "property_name", None)
            if pid not in (_SKILL_BONUS, _SKILL_PENALTY):
                continue
            amount = int(getattr(prop, "cost_value", 0) or 0)
            if pid == _SKILL_PENALTY:
                amount = -amount
            skill = int(getattr(prop, "subtype", -1))
            bonuses[skill] = bonuses.get(skill, 0) + amount
    return bonuses


def compute(skills, abilities: dict[str, int], items, game_root) -> list[SkillTotal]:
    """Break every skill down into rank + key ability + gear."""
    key = key_abilities(game_root)
    gear = item_skill_bonuses(items)
    totals: list[SkillTotal] = []
    for skill in skills:
        ability = key.get(skill.index, "")
        score = abilities.get(_ABILITY_FIELDS.get(ability, ""), 10)
        totals.append(SkillTotal(
            index=skill.index,
            name=skill.name,
            rank=skill.rank,
            ability=ability,
            ability_modifier=ability_modifier(score) if ability else 0,
            item_bonus=gear.get(skill.index, 0),
        ))
    return totals


#: ``skills.2da`` KeyAbility -> the character record's ability field.
_ABILITY_FIELDS = {
    "STR": "Str", "DEX": "Dex", "CON": "Con",
    "INT": "Int", "WIS": "Wis", "CHA": "Cha",
}
