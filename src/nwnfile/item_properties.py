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
#: PropertyName ids whose ``Subtype`` is an ability (iprp_abilities).
_ABILITY_PROPS = frozenset({0, 27})
#: PropertyName ids whose ``Subtype`` is a damage type (iprp_damagetype).
_DAMAGE_PROPS = frozenset({3, 16, 17, 18, 19, 20, 21, 23, 24, 33, 34})
#: Bonus Feat (iprp_feats), Cast Spell (iprp_spells), Skill Bonus (skills.2da id).
_FEAT_PROPS = frozenset({12})
_SPELL_PROPS = frozenset({15})
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
        # CostValue here indexes a dice/cost table, not a flat +N — omit it.
        subtype = DAMAGE_SUBTYPES.get(prop.subtype)
        return f"{name}: {subtype}" if subtype else name
    if pid in _FEAT_PROPS:
        subtype = _feats().get(prop.subtype)
        return f"{name}: {subtype}" if subtype else name
    if pid in _SPELL_PROPS:
        subtype = _spells().get(prop.subtype)
        return f"{name}: {subtype}" if subtype else name

    return with_cost(name)


def describe_properties(properties: list[ItemProperty]) -> list[str]:
    """Readable descriptions for an item's properties (bundled name table)."""
    names = default_property_names()
    return [describe_property(prop, names) for prop in properties]
