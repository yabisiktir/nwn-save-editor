"""A character's spell resistance, and where it comes from.

Spell resistance is a number the caster has to beat: they roll
``d20 + caster level + spell penetration`` against it, and the spell simply
fails if the roll is lower. A level-40 caster with epic spell penetration tops
out at 66, so **67 makes a character immune** to any spell a player can cast
that checks resistance.

**It does not stack.** Several sources may each grant resistance and only the
greatest is used — adding them up would overstate a character badly, and is the
single most likely mistake here. (Reductions do not stack either, and cannot
take resistance below zero.)

What the save can be read for:

* **item properties** — ``ImprovedMagicResist`` (property 39) on anything
  equipped. This is also how PRC delivers *racial and template* resistance: its
  scripts write the property onto the invisible skin
  (``RemoveSpecificProperty(oSkin, ITEM_PROPERTY_SPELL_RESISTANCE, …)``), and the
  skin is equipped, so one rule catches gear, race and template alike.
* **feats** — PRC records granted resistance as feats literally named
  "Spell Resistance 22", and a monk's Diamond Soul gives 10 + monk level.

What it cannot: resistance from the *spell* of the same name (12 + caster
level), which is temporary and lives in an effect the save does not describe
well enough to read. A character under that spell has more than is shown here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: ``itempropdef.2da`` row 39, "ImprovedMagicResist" — spell resistance.
SR_PROPERTY = 39
#: Its cost table: rows labelled ``Bonus_10`` … PRC extends this well past
#: vanilla's 32, so the value is read from the label rather than assumed.
SR_COST_TABLE = "iprp_srcost"

#: The highest roll a player-castable spell can make: d20 + 40 + epic penetration.
MAX_CASTER_ROLL = 66

_BONUS_LABEL = re.compile(r"Bonus_(\d+)", re.IGNORECASE)
#: PRC grants resistance as feats named exactly this.
_SR_FEAT = re.compile(r"^Spell Resistance (\d+)$", re.IGNORECASE)
#: A monk's Diamond Soul: 10 + monk level, raised by Improved Spell Resistance.
_DIAMOND_SOUL = "diamond soul"
_IMPROVED_SR = "improved spell resistance"


@dataclass(frozen=True)
class Source:
    """One thing granting spell resistance."""

    label: str
    value: int
    kind: str  # "item" | "feat"


@dataclass(frozen=True)
class SpellResistance:
    """Every source found, and the one that actually applies."""

    sources: tuple[Source, ...] = ()

    @property
    def effective(self) -> int:
        """The greatest source. Resistance does not stack, so never the sum."""
        return max((s.value for s in self.sources), default=0)

    @property
    def applies(self) -> Source | None:
        """The source the engine will use, or ``None`` if there is no resistance."""
        return max(self.sources, key=lambda s: s.value, default=None)

    @property
    def overridden(self) -> tuple[Source, ...]:
        """Sources present but doing nothing, because a greater one exists."""
        winner = self.applies
        return tuple(s for s in self.sources if s is not winner)

    @property
    def immune_to_player_casters(self) -> bool:
        """True when no player-castable spell can get through."""
        return self.effective > MAX_CASTER_ROLL


def spell_resistance(
    player, stack=None, name_of=None, feat_name=None, monk_level: int = 0
) -> SpellResistance:
    """Read every source of spell resistance the save records.

    ``stack`` resolves the cost table that turns a stored row into a number;
    without it item resistance cannot be valued and is left out rather than
    guessed at.
    """
    values = _cost_table(stack)
    sources: list[Source] = []

    for item in _equipped(player):
        row = _sr_row(item)
        if row is None:
            continue
        value = values.get(row)
        if value:
            sources.append(Source(_item_label(item, name_of), value, "item"))

    if feat_name is not None:
        sources.extend(_feat_sources(player, feat_name, monk_level))

    return SpellResistance(tuple(sorted(sources, key=lambda s: -s.value)))


def _feat_sources(player, feat_name, monk_level: int) -> list[Source]:
    names: list[str] = []
    for feat_id in _feats(player):
        try:
            name = feat_name(feat_id)
        except Exception:
            name = None
        if name:
            names.append(str(name))

    out: list[Source] = []
    improved = sum(1 for n in names if n.lower().startswith(_IMPROVED_SR))
    for name in names:
        match = _SR_FEAT.match(name.strip())
        if match:
            out.append(Source(name.strip(), int(match.group(1)), "feat"))
        elif name.strip().lower() == _DIAMOND_SOUL and monk_level:
            out.append(Source(
                f"Diamond Soul (monk {monk_level})", 10 + monk_level + improved, "feat"
            ))
    return out


def _cost_table(stack) -> dict[int, int]:
    """``row -> resistance`` from ``iprp_srcost``'s ``Bonus_NN`` labels."""
    if stack is None:
        return {}
    try:
        rows = stack.read_2da(SR_COST_TABLE)
    except Exception:
        return {}
    out: dict[int, int] = {}
    for index, row in (rows or {}).items():
        match = _BONUS_LABEL.search(row.get("Label", "") or "")
        if match:
            out[index] = int(match.group(1))
    return out


def _sr_row(item) -> int | None:
    field = getattr(item, "fields", {}).get("PropertiesList")
    if field is None or not hasattr(field.value, "structs"):
        return None
    best: int | None = None
    for prop in field.value.structs:
        if prop.get("PropertyName") != SR_PROPERTY:
            continue
        row = prop.get("CostValue")
        if row is not None and (best is None or row > best):
            best = int(row)
    return best


def _equipped(player):
    field = getattr(player, "fields", {}).get("Equip_ItemList")
    if field is None or not hasattr(field.value, "structs"):
        return ()
    return field.value.structs


def _feats(player) -> list[int]:
    field = getattr(player, "fields", {}).get("FeatList")
    if field is None or not hasattr(field.value, "structs"):
        return []
    out = []
    for struct in field.value.structs:
        value = struct.get("Feat")
        if value is not None:
            out.append(int(value))
    return out


def _item_label(item, name_of) -> str:
    if name_of is not None:
        try:
            name = name_of(item)
        except Exception:
            name = None
        if name:
            return str(name)
    localized = item.get("LocalizedName")
    text = localized.text() if hasattr(localized, "text") else None
    return str(text or item.get("Tag") or "equipped item")
