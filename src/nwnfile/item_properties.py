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

Only these two (most common) subtype categories are resolved by name. Other
subtypes (bonus-feat, cast-spell, skill, class, racial) reference large,
PRC-specific ``iprp_*`` tables and are left unresolved rather than guessed, so the
property still shows by type (e.g. ``"Bonus Feat"``). ``CostValue`` is appended as a
``+N`` magnitude except for damage properties, where it indexes a dice/cost table
rather than a flat bonus.
"""

from __future__ import annotations

import json
from pathlib import Path

from vaultkeeper.core.formats.bic_reader import ItemProperty

_DATA_DIR = Path(__file__).resolve().parent / "data"
PROPERTY_NAMES_FILE = "Item Property Names.json"

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


def load_property_names(path: Path) -> dict[int, str]:
    """Parse ``Item Property Names.json`` (``{"<id>": "name"}``) into ``{id: name}``."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[int, str] = {}
    for key, name in raw.items():
        try:
            result[int(key)] = name
        except (TypeError, ValueError):
            continue
    return result


_cached: dict[int, str] | None = None


def default_property_names() -> dict[int, str]:
    """The bundled property-name table (cached after first load)."""
    global _cached
    if _cached is None:
        path = _DATA_DIR / PROPERTY_NAMES_FILE
        _cached = load_property_names(path) if path.is_file() else {}
    return _cached


def describe_property(prop: ItemProperty, names: dict[int, str] | None = None) -> str:
    """A readable one-line description of an item property (name + subtype + magnitude)."""
    names = default_property_names() if names is None else names
    name = names.get(prop.property_name, f"Property {prop.property_name}")

    if prop.property_name in _ABILITY_PROPS:
        subtype = ABILITY_SUBTYPES.get(prop.subtype)
        base = f"{name}: {subtype}" if subtype else name
        return f"{base} +{prop.cost_value}" if prop.cost_value else base
    if prop.property_name in _DAMAGE_PROPS:
        subtype = DAMAGE_SUBTYPES.get(prop.subtype)
        # CostValue here indexes a dice/cost table, not a flat +N — omit it.
        return f"{name}: {subtype}" if subtype else name

    return f"{name} +{prop.cost_value}" if prop.cost_value else name


def describe_properties(properties: list[ItemProperty]) -> list[str]:
    """Readable descriptions for an item's properties (bundled name table)."""
    names = default_property_names()
    return [describe_property(prop, names) for prop in properties]
