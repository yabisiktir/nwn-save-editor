"""Where each ability score comes from: base, race, templates, worn items.

A saved game stores base scores. The number the game's character sheet shows is
that base plus the racial adjustment from ``racialtypes.2da`` plus what the
character is wearing — including PRC's invisible skin, which carries every
template's contribution as ordinary item properties.

This assembles those parts and shows its working, so a total that disagrees with
the game disagrees *visibly*, at a named row, rather than as one wrong number.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from nwnfile import prc_bonuses
from nwnfile.class_tables import ClassTable, character_classes
from nwnfile.races import ABILITY_FIELDS, RaceTable

#: ``PropertyName`` 0 is Ability Bonus; its ``Subtype`` indexes ABILITY_FIELDS.
_ABILITY_BONUS = 0

_KIND_ORDER = {"race": 0, "class": 1, "template": 2, "item": 3}


@dataclass(frozen=True)
class Component:
    """One named contribution to an ability score."""

    source: str
    amount: int
    kind: str  # "race" | "template" | "item"


@dataclass(frozen=True)
class AbilityTotal:
    """A base score and everything added to it."""

    field: str
    base: int
    components: tuple[Component, ...] = ()
    #: True when the skin's properties could be attributed to named templates.
    attributed: bool = True

    @property
    def added(self) -> int:
        return sum(c.amount for c in self.components)

    @property
    def total(self) -> int:
        return self.base + self.added

    def of_kind(self, kind: str) -> tuple[Component, ...]:
        return tuple(c for c in self.components if c.kind == kind)


@dataclass
class _Accumulator:
    components: list[Component] = dataclass_field(default_factory=list)
    attributed: bool = True


def ability_breakdown(
    player,
    races: RaceTable | None = None,
    name_of=None,
    classes: ClassTable | None = None,
) -> list[AbilityTotal]:
    """Per-ability totals for a character struct from ``Mod_PlayerList[0]``.

    ``races`` and ``classes`` supply the adjustments the engine re-applies on
    load; without either, that row is simply absent rather than assumed to be
    zero, because a missing table and a genuine nothing are different claims.
    """
    acc = {f: _Accumulator() for f in ABILITY_FIELDS}

    race_id = player.get("Race")
    if races is not None and race_id is not None and races.has_race(race_id):
        label = races.label(race_id) or f"Race {race_id}"
        for ability, amount in races.adjustments(race_id).items():
            acc[ability].components.append(Component(label, amount, "race"))

    if classes is not None:
        for class_id, level in character_classes(player):
            label = classes.label(class_id) or f"Class {class_id}"
            for ability, amount in classes.gains(class_id, level).items():
                acc[ability].components.append(
                    Component(f"{label} {level}", amount, "class")
                )

    for item in _equipped(player):
        _add_item(item, acc, name_of)

    return [
        AbilityTotal(
            f,
            player.get(f) or 0,
            tuple(sorted(acc[f].components, key=lambda c: (_KIND_ORDER.get(c.kind, 9), c.source))),
            acc[f].attributed,
        )
        for f in ABILITY_FIELDS
    ]


def _add_item(item, acc: dict[str, _Accumulator], name_of) -> None:
    bonuses = _ability_bonuses(item)
    if not bonuses:
        return
    # PRC's skin carries every template's work. Credit the templates by name
    # where its own registry accounts for the whole amount; otherwise show the
    # item, because a partial attribution would lose points silently.
    registry = prc_bonuses.ability_sources(item)
    label = _item_label(item, name_of)
    for ability, amount in bonuses.items():
        named = registry.get(ability, [])
        if named and sum(v for _, v in named) == amount:
            for source, value in named:
                acc[ability].components.append(Component(source, value, "template"))
        else:
            if named:
                acc[ability].attributed = False
            acc[ability].components.append(Component(label, amount, "item"))


def _ability_bonuses(item) -> dict[str, int]:
    """``{ability field: total}`` from one item's Ability Bonus properties."""
    field = getattr(item, "fields", {}).get("PropertiesList")
    if field is None or not hasattr(field.value, "structs"):
        return {}
    out: dict[str, int] = {}
    for prop in field.value.structs:
        if prop.get("PropertyName") != _ABILITY_BONUS:
            continue
        subtype = prop.get("Subtype")
        amount = prop.get("CostValue")
        if subtype is None or amount is None or not 0 <= subtype < len(ABILITY_FIELDS):
            continue
        out[ABILITY_FIELDS[subtype]] = out.get(ABILITY_FIELDS[subtype], 0) + int(amount)
    return out


def _equipped(player):
    field = getattr(player, "fields", {}).get("Equip_ItemList")
    if field is None or not hasattr(field.value, "structs"):
        return ()
    return field.value.structs


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
    return str(text or item.get("Tag") or "item")
