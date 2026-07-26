"""Human-readable item magical properties (NWN itempropdef + iprp_* subtypes).

A ``.bic`` stores each item property as a ``PropertyName`` id (itempropdef.2da row)
plus ``Subtype`` / ``CostTable`` / ``CostValue``. :func:`describe_property` renders
one as a readable line, e.g. ``"Ability Bonus: Dexterity +8"`` or ``"Bonus Feat"``.

Data sources (grounded):

* **Property names** — bundled ``game/data/Item Property Names.json``, built from the
  Leto-PRC editor's ``PropertyName.html`` (see ``docs/prc_feats/build_item_properties.py``).
* **Ability / Damage-type subtypes** — the small standard NWN reference tables
  below (``iprp_abilities`` / ``iprp_damagetype``); the ability table is the same
  Str..Cha order as :data:`bic_reader.ABILITY_LABELS`.

* **Bonus-Feat / Cast-Spell subtypes** — bundled ``Item Property {Feat,Spell}
  Subtypes.json.gz`` (gzipped ``{subtype: name}``), built from the installed PRC hak's
  ``iprp_feats`` / ``iprp_spells`` 2da (see
  ``docs/prc_feats/build_item_property_subtypes.py``). Those subtypes are an
  indirection (``iprp_*`` row -> feat.2da/spells.2da), resolved to names at build time.
* **Skill subtypes** — the bundled skill tables (subtype == skill id).

``CostValue`` is appended as a ``+N`` magnitude for the bonus-style properties
(ability/AC/enhancement/skill/generic) but not for damage/feat/spell, where it
indexes a dice/uses table rather than a flat bonus.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from vaultkeeper.core.formats.bic_reader import ItemProperty

_DATA_DIR = Path(__file__).resolve().parent / "data"
PROPERTY_NAMES_FILE = "Item Property Names.json"
FEAT_SUBTYPES_FILE = "Item Property Feat Subtypes.json.gz"
SPELL_SUBTYPES_FILE = "Item Property Spell Subtypes.json.gz"
SPELL_LEVELS_FILE = "Item Property Spell Levels.json"
ONHIT_SPELL_SUBTYPES_FILE = "Item Property OnHit Spell Subtypes.json.gz"

#: iprp_abilities.2da subtype -> ability name (used by Ability Bonus / Decreased).
ABILITY_SUBTYPES: dict[int, str] = {
    0: "Strength", 1: "Dexterity", 2: "Constitution",
    3: "Intelligence", 4: "Wisdom", 5: "Charisma",
}
#: iprp_damagetype.2da subtype -> damage type (used by the Damage * properties).
DAMAGE_SUBTYPES: dict[int, str] = {
    0: "Bludgeoning", 1: "Piercing", 2: "Slashing", 4: "Physical", 5: "Magical",
    6: "Acid", 7: "Cold", 8: "Divine", 9: "Electrical", 10: "Fire",
    11: "Negative Energy", 12: "Positive Energy", 13: "Sonic",
}
#: iprp_chargecost.2da CostValue -> uses/day (from base_2da.bif; Cast Spell charges).
SPELL_USES: dict[int, str] = {
    1: "single use", 2: "5 charges/use", 3: "4 charges/use", 4: "3 charges/use",
    5: "2 charges/use", 6: "1 charge/use", 7: "0 charges/use", 8: "1 use/day",
    9: "2 uses/day", 10: "3 uses/day", 11: "4 uses/day", 12: "5 uses/day",
    13: "unlimited use",
}
#: Small standard subtype charts (Leto ``Subtype.html`` iprp_* tables), by anchor.
_SUBTYPE_CHARTS: dict[str, dict[int, str]] = {
    "immun_misc": {0: "Sneak Attack", 1: "Level/Ability Drain",
        2: "Mind-Affecting Spells", 3: "Poison", 4: "Disease", 5: "Fear",
        6: "Knockdown", 7: "Paralysis", 8: "Critical Hit", 9: "Death Magic"},
    "on_hit": {0: "Sleep", 1: "Stun", 2: "Hold", 3: "Confusion", 5: "Daze",
        6: "Doom", 7: "Fear", 8: "Knock", 9: "Slow", 10: "Lesser Dispel",
        11: "Dispel Magic", 12: "Greater Dispel", 13: "Mordenkainen's Disjunction",
        14: "Silence", 15: "Deafness", 16: "Blindness", 17: "Level Drain",
        18: "Ability Drain", 19: "Item Poison", 20: "Disease",
        21: "Slay Racial Group", 22: "Slay Alignment Group", 23: "Slay Alignment",
        24: "Vorpal", 25: "Wounding"},
    "immun_school": {0: "General", 1: "Abjuration", 2: "Conjuration",
        3: "Divination", 4: "Enchantment", 5: "Evocation", 6: "Illusion",
        7: "Necromancy", 8: "Transmutation"},
    "vfx": {0: "Acid", 1: "Cold", 2: "Electrical", 3: "Fire", 4: "Sonic", 5: "Evil"},
    "bonus_save": {0: "Universal", 1: "Acid", 3: "Cold", 4: "Death", 5: "Disease",
        6: "Divine", 7: "Electrical", 8: "Fear", 9: "Fire", 11: "Mind-Affecting",
        12: "Negative", 13: "Poison", 14: "Positive", 15: "Sonic"},
    "bonus_savespec": {0: "Fortitude", 1: "Will", 2: "Reflex"},
    "use_align_grp": {1: "Neutral", 2: "Lawful", 3: "Chaotic", 4: "Good", 5: "Evil"},
    "use_alignment": {0: "Lawful Good", 1: "Lawful Neutral", 2: "Lawful Evil",
        3: "Neutral Good", 4: "True Neutral", 5: "Neutral Evil", 6: "Chaotic Good",
        7: "Chaotic Neutral", 8: "Chaotic Evil"},
    "use_race": {0: "Dwarf", 1: "Elf", 2: "Gnome", 3: "Halfling", 4: "Half-Elf",
        5: "Half-Orc", 6: "Human", 7: "Aberration", 8: "Animal", 9: "Beast",
        10: "Construct", 11: "Dragon", 12: "Goblinoid", 13: "Monstrous", 14: "Orc",
        15: "Reptilian", 16: "Elemental", 17: "Fey", 18: "Giant",
        19: "Magical Beast", 20: "Outsider", 23: "Shapechanger", 24: "Undead",
        25: "Vermin", 29: "Ooze"},
    "acmodtype": {0: "Dodge", 1: "Natural", 2: "Armor", 3: "Shield", 4: "Deflection"},
}
#: PropertyName -> (subtype chart, whether to append "+CostValue").
_CHART_PROPS: dict[int, tuple[str, bool]] = {
    37: ("immun_misc", False), 48: ("on_hit", False),
    54: ("immun_school", False), 83: ("vfx", False),
    40: ("bonus_save", True), 49: ("bonus_save", False),
    41: ("bonus_savespec", True), 50: ("bonus_savespec", False),
    2: ("use_align_grp", True), 7: ("use_align_grp", True),
    57: ("use_align_grp", True), 17: ("use_align_grp", False),
    62: ("use_align_grp", False),
    5: ("use_alignment", True), 9: ("use_alignment", True),
    59: ("use_alignment", True), 19: ("use_alignment", False),
    65: ("use_alignment", False),
    4: ("use_race", True), 8: ("use_race", True), 58: ("use_race", True),
    18: ("use_race", False), 64: ("use_race", False),
    28: ("acmodtype", False),
}
#: iprp_immuncost/iprp_damvulcost.2da CostValue -> percentage (Damage Immunity /
#: Vulnerability); iprp_resistcost.2da CostValue -> soak amount (Damage Resistance).
_IMMUNITY_PCT: dict[int, str] = {
    1: "5%", 2: "10%", 3: "25%", 4: "50%", 5: "75%", 6: "90%", 7: "100%",
}
_RESIST_AMOUNT: dict[int, str] = {row: f"{row * 5}/-" for row in range(1, 11)}
_DAMAGE_PCT_PROPS = frozenset({20, 24})  # Damage Immunity / Vulnerability
_DAMAGE_RESIST_PROP = 23  # Damage Resistance
#: PropertyName ids whose ``Subtype`` is an ability (iprp_abilities).
_ABILITY_PROPS = frozenset({0, 27})
#: PropertyName ids whose ``Subtype`` is a damage type (iprp_damagetype).
_DAMAGE_PROPS = frozenset({3, 16, 20, 21, 23, 24, 33, 34})
#: Bonus Feat (iprp_feats), Cast Spell (iprp_spells), Skill Bonus (skills.2da id).
_FEAT_PROPS = frozenset({12})
_SPELL_PROP = 15  # Cast Spell -> iprp_spells subtype + innate level + uses/day
_ONHIT_SPELL_PROP = 82  # On Hit Cast Spell -> iprp_onhitspell subtype
_SKILL_PROPS = frozenset({52, 29})  # 52 Skill Bonus, 29 Decreased Skill
_CLASS_PROPS = frozenset({63})  # Use Limitation Class -> subtype is a class id
_SPELL_SLOT_PROP = 13  # Bonus Spell Slot of Level: subtype = class, CostValue = level
#: Names end "... Level"; CostValue is the spell level, not a flat bonus.
_SPELL_LEVEL_PROPS = frozenset({78, 88, 89, 90})


def _coerce(raw: dict) -> dict[int, str]:
    result: dict[int, str] = {}
    for key, name in raw.items():
        try:
            result[int(key)] = name
        except (TypeError, ValueError):
            continue
    return result


def load_property_names(path: Path) -> dict[int, str]:
    """Parse ``Item Property Names.json`` (``{"<id>": "name"}``) into ``{id: name}``."""
    return _coerce(json.loads(path.read_text(encoding="utf-8")))


def _load_gz(path: Path) -> dict[int, str]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return _coerce(json.load(fh))


_cached: dict[int, str] | None = None
_feat_subtypes: dict[int, str] | None = None
_spell_subtypes: dict[int, str] | None = None
_onhit_spell_subtypes: dict[int, str] | None = None
_spell_level_map: dict[int, str] | None = None
_skill_subtypes: dict[int, str] | None = None


def default_property_names() -> dict[int, str]:
    """The bundled property-name table (cached after first load)."""
    global _cached
    if _cached is None:
        path = _DATA_DIR / PROPERTY_NAMES_FILE
        _cached = load_property_names(path) if path.is_file() else {}
    return _cached


def _feats() -> dict[int, str]:
    global _feat_subtypes
    if _feat_subtypes is None:
        path = _DATA_DIR / FEAT_SUBTYPES_FILE
        _feat_subtypes = _load_gz(path) if path.is_file() else {}
    return _feat_subtypes


def _spells() -> dict[int, str]:
    global _spell_subtypes
    if _spell_subtypes is None:
        path = _DATA_DIR / SPELL_SUBTYPES_FILE
        _spell_subtypes = _load_gz(path) if path.is_file() else {}
    return _spell_subtypes


def _onhit_spells() -> dict[int, str]:
    global _onhit_spell_subtypes
    if _onhit_spell_subtypes is None:
        path = _DATA_DIR / ONHIT_SPELL_SUBTYPES_FILE
        _onhit_spell_subtypes = _load_gz(path) if path.is_file() else {}
    return _onhit_spell_subtypes


def _spell_levels() -> dict[int, str]:
    global _spell_level_map
    if _spell_level_map is None:
        path = _DATA_DIR / SPELL_LEVELS_FILE
        _spell_level_map = load_property_names(path) if path.is_file() else {}
    return _spell_level_map


def _class_name(class_id: int) -> str:
    """Class name for a Use-Limitation/Bonus-Spell-Slot subtype (base -> PRC -> Class N)."""
    from vaultkeeper.game.character import class_name

    return class_name(class_id)


def _skills() -> dict[int, str]:
    global _skill_subtypes
    if _skill_subtypes is None:
        from vaultkeeper.game.character_reference import default_reference

        ref = default_reference()
        skills = dict(enumerate(ref.skill_names))
        skills.update(ref.prc_skill_names)
        _skill_subtypes = skills
    return _skill_subtypes


def describe_property(prop: ItemProperty, names: dict[int, str] | None = None) -> str:
    """A readable one-line description of an item property (name + subtype + magnitude)."""
    names = default_property_names() if names is None else names
    name = names.get(prop.property_name, f"Property {prop.property_name}")
    pid = prop.property_name

    def with_cost(text: str) -> str:
        return f"{text} +{prop.cost_value}" if prop.cost_value else text

    if pid in _CLASS_PROPS:
        return f"{name}: {_class_name(prop.subtype)}"
    if pid == _SPELL_SLOT_PROP:  # Bonus Spell Slot of Level <n>: <class>
        return f"{name} {prop.cost_value}: {_class_name(prop.subtype)}"
    if pid in _SPELL_LEVEL_PROPS:  # name ends "... Level" -> append the level
        return f"{name} {prop.cost_value}"
    if pid in _ABILITY_PROPS:
        subtype = ABILITY_SUBTYPES.get(prop.subtype)
        return with_cost(f"{name}: {subtype}" if subtype else name)
    if pid in _SKILL_PROPS:
        subtype = _skills().get(prop.subtype)
        return with_cost(f"{name}: {subtype}" if subtype else name)
    if pid in _DAMAGE_PROPS:
        subtype = DAMAGE_SUBTYPES.get(prop.subtype)
        base = f"{name}: {subtype}" if subtype else name
        if pid in _DAMAGE_PCT_PROPS:  # Damage Immunity / Vulnerability -> percentage
            pct = _IMMUNITY_PCT.get(prop.cost_value)
            return f"{base} {pct}" if pct else base
        if pid == _DAMAGE_RESIST_PROP:  # Damage Resistance -> soak amount
            amount = _RESIST_AMOUNT.get(prop.cost_value)
            return f"{base} {amount}" if amount else base
        # Other damage props: CostValue indexes a dice table, not a flat +N — omit.
        return base
    if pid in _FEAT_PROPS:
        subtype = _feats().get(prop.subtype)
        return f"{name}: {subtype}" if subtype else name
    if pid == _SPELL_PROP:  # Cast Spell: <spell> (level N, uses/day)
        spell = _spells().get(prop.subtype)
        if not spell:
            return name
        level = _spell_levels().get(prop.subtype)
        detail = ", ".join(
            part for part in (
                f"level {level}" if level is not None else "",
                SPELL_USES.get(prop.cost_value, ""),
            ) if part
        )
        return f"{name}: {spell}" + (f" ({detail})" if detail else "")
    if pid == _ONHIT_SPELL_PROP:  # On Hit Cast Spell: <spell>
        spell = _onhit_spells().get(prop.subtype)
        return f"{name}: {spell}" if spell else name
    if pid in _CHART_PROPS:
        chart, is_bonus = _CHART_PROPS[pid]
        subtype = _SUBTYPE_CHARTS[chart].get(prop.subtype)
        base = f"{name}: {subtype}" if subtype is not None and prop.subtype != 0xFFFF else name
        return with_cost(base) if is_bonus else base

    return with_cost(name)


def describe_properties(properties: list[ItemProperty]) -> list[str]:
    """Readable descriptions for an item's properties (bundled name table)."""
    names = default_property_names()
    return [describe_property(prop, names) for prop in properties]
