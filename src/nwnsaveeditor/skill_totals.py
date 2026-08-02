"""Work out what a skill actually comes to, not just its rank.

A save stores only **ranks**. Everything else the character sheet shows — the key
ability's modifier, bonuses from gear — the engine recomputes at runtime, so a
"total" has to be rebuilt here.

What is included is deliberately limited to what can be read straight out of the
save and the game's own tables:

* the **rank** stored in the character's ``SkillList``,
* the **key ability modifier** from ``skills.2da``'s ``KeyAbility`` column,
  taken from the ability's score **in play** rather than the one stored,
* **item bonuses** from Skill Bonus / Decreased Skill properties on *equipped*
  items (including the PRC skin, which is where PRC puts its own).

That second point is how race, class levels and PRC templates reach a skill at
all. Neither ``racialtypes.2da`` nor a class's ``cls_stat_*`` table has skill
columns; what they raise is the *ability*, and the skill follows from its
modifier. Using the stored score instead understates every skill of a character
whose abilities are adjusted — on a Bralani Red Dragon Disciple that is 21
points of Strength, so a Discipline of 60 showed as 39.

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
    #: ``(item name, amount)`` for each equipped item that moves this skill.
    sources: tuple[tuple[str, int], ...] = ()

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

    def detail(self) -> str:
        """Every part named, for a tooltip."""
        lines = [f"{self.name} {self.total}", f"    {self.rank}\trank, as stored in the save"]
        if self.ability:
            lines.append(
                f"    {self.ability_modifier:+d}\t{self.ability} modifier, "
                "from the score in play"
            )
        for name, amount in self.sources:
            lines.append(f"    {amount:+d}\t{name}")
        return "\n".join(lines)


def ability_modifier(score: int) -> int:
    """D&D's (score - 10) / 2, rounded down."""
    return (score - 10) // 2


def key_abilities(game_root, stack=None) -> dict[int, str]:
    """``skill index -> key ability`` ("STR", "DEX", …) from ``skills.2da``.

    Read through the save's hak stack where one is available: PRC adds skills
    beyond the base game's, and a skill missing from the table gets no ability
    modifier at all.
    """
    try:
        from nwnfile.item_property_tables import parse_2da

        if stack is not None:
            rows = stack.read_2da("skills")
            if rows:
                return _key_ability_column(rows)
        if game_root is None:
            return {}
        from nwnfile.formats.key_bif_reader import KeyBifReader

        text = KeyBifReader.for_install(game_root).read_2da_text("skills")
        if not text:
            return {}
        _headers, rows = parse_2da(text)
    except Exception:
        return {}
    return _key_ability_column(rows)


def _key_ability_column(rows) -> dict[int, str]:
    out: dict[int, str] = {}
    for index, row in rows.items():
        ability = (row.get("KeyAbility") or "").strip().upper()
        if ability and ability != "****":
            out[index] = ability
    return out


def item_skill_bonuses(items) -> dict[int, int]:
    """``skill index -> net bonus`` from the properties of *equipped* items."""
    return {
        skill: sum(amount for _name, amount in sources)
        for skill, sources in item_skill_sources(items).items()
    }


def item_skill_sources(items) -> dict[int, list[tuple[str, int]]]:
    """``skill index -> [(item name, amount), …]`` from *equipped* items.

    The PRC skin appears here like any other item: templates write their skill
    bonuses onto it as ordinary properties, so they are counted already.
    """
    out: dict[int, list[tuple[str, int]]] = {}
    for item in items:
        slot = getattr(item, "slot", None)
        if slot is None or slot in _WORN_SLOTS_EXCLUDED:
            continue  # carried items and ammunition grant nothing
        per_skill: dict[int, int] = {}
        for entry in getattr(item, "properties", []) or []:
            prop = getattr(entry, "prop", entry)
            pid = getattr(prop, "property_name", None)
            if pid not in (_SKILL_BONUS, _SKILL_PENALTY):
                continue
            amount = int(getattr(prop, "cost_value", 0) or 0)
            if pid == _SKILL_PENALTY:
                amount = -amount
            skill = int(getattr(prop, "subtype", -1))
            per_skill[skill] = per_skill.get(skill, 0) + amount
        name = _item_name(item)
        for skill, amount in per_skill.items():
            if amount:
                out.setdefault(skill, []).append((name, amount))
    return out


def _item_name(item) -> str:
    for attribute in ("name", "display_name", "tag"):
        value = getattr(item, attribute, None)
        if value:
            # The PRC skin is not something the player wears knowingly: it is
            # where templates and class features put their bonuses. Saying so
            # beats printing an internal tag nobody recognises.
            if "prc_skin" in str(value).lower():
                return "PRC skin (templates and class features)"
            return str(value)
    return "equipped item"


def compute(
    skills, abilities: dict[str, int], items, game_root, stack=None
) -> list[SkillTotal]:
    """Break every skill down into rank + key ability + gear.

    ``abilities`` must be the scores **in play** — base plus race, class levels
    and everything worn — because that is what the engine takes the modifier
    from. Passing the stored scores understates every skill the character has.
    """
    key = key_abilities(game_root, stack)
    gear = item_skill_sources(items)
    totals: list[SkillTotal] = []
    for skill in skills:
        ability = key.get(skill.index, "")
        score = abilities.get(_ABILITY_FIELDS.get(ability, ""), 10)
        sources = tuple(gear.get(skill.index, ()))
        totals.append(SkillTotal(
            index=skill.index,
            name=skill.name,
            rank=skill.rank,
            ability=ability,
            ability_modifier=ability_modifier(score) if ability else 0,
            item_bonus=sum(amount for _n, amount in sources),
            sources=sources,
        ))
    return totals


#: ``skills.2da`` KeyAbility -> the character record's ability field.
_ABILITY_FIELDS = {
    "STR": "Str", "DEX": "Dex", "CON": "Con",
    "INT": "Int", "WIS": "Wis", "CHA": "Cha",
}
