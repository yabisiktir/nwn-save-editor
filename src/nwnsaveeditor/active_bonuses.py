"""Where a character's numbers come from — as far as a save can actually say.

The raw ``EffectList`` answers "what is running"; it does not answer "why is my
Strength 29 + something". This module answers the second question by walking the
sources a save *does* record and attributing each one, rather than by
reimplementing the game's rules.

What is attributed:

* **Equipped items** — every magical property on an item in a worn slot,
  routed to what it affects (ability, AC, save, skill, regeneration, immunity…)
  and named by :func:`~vaultkeeper.game.item_properties.describe_property`. The
  PRC skin (slot ``131072``) is one of those items and is labelled as such,
  because on a PRC character most granted bonuses live there.
* **Feats granted by gear** — Bonus Feat properties, credited to the item.
* **Classes** — the class/level line, plus the base attack bonus and the three
  base saving throws, which the record stores outright.
* **Ongoing spell effects** — an ``EffectList`` entry that carries a real
  ``SpellId`` is named from the spell tables.

What is **not** attributed, and is said so in as many words rather than left to
look like a zero:

* **What each feat contributes.** The save stores *which* feats a character has,
  never what any of them does; working that out means running the rules engine.
* **Class abilities beyond the stored base numbers** — same reason.
* **What an untagged effect modifies.** The magnitude lives in the effect's
  ``IntList``, keyed by the engine's *internal* effect enum, which is not the
  ``EFFECT_TYPE_*`` enum scripts see (see the Effects view). Decoding it would
  mean guessing at the numbering, so the effect is listed and left unexplained.

Nothing here is a character-sheet total. NWN does not stack same-type bonuses
from items — the engine applies the largest and drops the rest — so a group
reports both its **largest** contribution and the **sum** of them, labelled, and
lets the reader decide. Quietly printing one of the two as "your bonus" would be
the kind of confidently-wrong number this module exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vaultkeeper.game.item_properties import (
    ABILITY_SUBTYPES,
    DAMAGE_SUBTYPES,
    describe_property,
)

#: Equipment slot bits whose items are worn but grant nothing (ammunition).
_WORN_SLOTS_EXCLUDED = frozenset({2048, 4096, 8192})
#: The creature-skin slot: PRC hangs its granted bonuses here, so it is labelled.
SKIN_SLOT = 131072

#: Categories, in the order the view shows them.
CATEGORY_ORDER: tuple[str, ...] = (
    "Ability scores",
    "Armour class",
    "Attack & damage",
    "Saving throws",
    "Skills",
    "Regeneration",
    "Immunities & resistances",
    "Feats granted by gear",
    "Other gear properties",
)

#: Item property ids whose ``CostValue`` really is the literal bonus, so it can be
#: compared and added up. This is deliberately stricter than
#: :func:`item_properties.editable_magnitude`, which asks only whether a value is
#: *safe to edit*: Spell Resistance, Damage Reduction, Massive Criticals and
#: Immunity Specific Spell all store a table row or a spell id there, and a view
#: that adds those up would print a number that means nothing. Those properties
#: still appear — just as their description, with no arithmetic done to them.
_NUMERIC_PROPS = frozenset({0, 27, 1, 28, 6, 56, 52, 29, 40, 41, 49, 50, 51, 67})
#: Item property ids whose magnitude is a penalty (``CostValue`` is unsigned).
_PENALTY_PROPS = frozenset({27, 28, 29, 49, 50})

#: ``property id -> (category, fixed subject)``; ``None`` subject == derive it.
_ROUTING: dict[int, tuple[str, str | None]] = {
    0: ("Ability scores", None), 27: ("Ability scores", None),
    1: ("Armour class", "Armour class"), 28: ("Armour class", None),
    6: ("Attack & damage", "Enhancement bonus"),
    56: ("Attack & damage", "Attack bonus"),
    74: ("Attack & damage", "Massive criticals"),
    77: ("Attack & damage", "Monster damage"),
    40: ("Saving throws", None), 49: ("Saving throws", None),
    41: ("Saving throws", None), 50: ("Saving throws", None),
    52: ("Skills", None), 29: ("Skills", None),
    51: ("Regeneration", "Regeneration"),
    67: ("Regeneration", "Vampiric regeneration"),
    20: ("Immunities & resistances", None), 24: ("Immunities & resistances", None),
    23: ("Immunities & resistances", None), 22: ("Immunities & resistances", "Damage reduction"),
    37: ("Immunities & resistances", "Immunity"),
    54: ("Immunities & resistances", "Spell school immunity"),
    53: ("Immunities & resistances", "Spell immunity"),
    39: ("Immunities & resistances", "Spell resistance"),
    12: ("Feats granted by gear", "Feats granted by gear"),
}
#: Damage properties whose subject names the damage type.
_DAMAGE_SUBJECTS: dict[int, str] = {
    20: "Damage immunity", 24: "Damage vulnerability", 23: "Damage resistance",
}
#: ``acmodtype`` rows, for "AC Bonus vs." subjects (see item_properties).
_AC_TYPES: dict[int, str] = {
    0: "Dodge", 1: "Natural", 2: "Armour", 3: "Shield", 4: "Deflection",
}
#: Saving-throw subjects: specific (``iprp_savingthrow``) and by element.
_SAVE_KINDS: dict[int, str] = {0: "Fortitude", 1: "Will", 2: "Reflex"}
_SAVE_ELEMENTS: dict[int, str] = {
    1: "Acid", 3: "Cold", 4: "Death", 5: "Disease", 6: "Divine", 7: "Electrical",
    8: "Fear", 9: "Fire", 11: "Mind-Affecting", 12: "Negative", 13: "Poison",
    14: "Positive", 15: "Sonic",
}

#: Ability display order, so "Ability scores" reads Str..Cha not alphabetically.
_ABILITY_ORDER = tuple(ABILITY_SUBTYPES[i] for i in sorted(ABILITY_SUBTYPES))


@dataclass(frozen=True)
class Contribution:
    """One attributable line: a source, what it grants, and how much."""

    source: str  #: the item, feat or spell it comes from
    detail: str  #: the property as :func:`describe_property` renders it
    amount: int | None = None  #: the magnitude, when it is a plain ``+N``
    repeats: int = 1  #: identical copies collapsed into this line

    @property
    def label(self) -> str:
        return f"{self.repeats}×  {self.detail}" if self.repeats > 1 else self.detail


@dataclass
class BonusGroup:
    """Everything that feeds one number, e.g. Strength or Fortitude saves."""

    category: str
    subject: str
    contributions: list[Contribution] = field(default_factory=list)

    @property
    def amounts(self) -> list[int]:
        """Every numeric contribution, a collapsed ``N×`` line counted N times."""
        return [
            c.amount for c in self.contributions
            if c.amount is not None for _ in range(c.repeats)
        ]

    @property
    def count(self) -> int:
        """How many properties feed this group (collapsed copies counted each)."""
        return sum(c.repeats for c in self.contributions)

    @property
    def largest(self) -> int | None:
        """The biggest single contribution — what NWN applies for same-type gear."""
        amounts = self.amounts
        return max(amounts, key=abs) if amounts else None

    @property
    def total(self) -> int | None:
        """Every contribution added up — shown only alongside :attr:`largest`."""
        amounts = self.amounts
        return sum(amounts) if amounts else None

    @property
    def summary(self) -> str:
        """A short header value; a plain count when nothing here is a number."""
        largest, total = self.largest, self.total
        if largest is None:
            return f"{self.count} properties" if self.count > 1 else "1 property"
        if total == largest:
            return _signed(largest)
        return f"largest {_signed(largest)} · sum {_signed(total)}"


@dataclass
class SpellEffect:
    """An ``EffectList`` entry, as far as it can be attributed."""

    name: str  #: spell name, custom tag, or "" when the save names it nothing
    caster_level: int
    duration: float
    attributed: bool  #: False == the save does not say what this one modifies


@dataclass
class ActiveBonuses:
    """The computed view: attributed groups plus an honest statement of scope."""

    groups: list[BonusGroup] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)  #: "Fighter 8", …
    class_facts: list[tuple[str, str]] = field(default_factory=list)
    feat_count: int = 0
    spell_effects: list[SpellEffect] = field(default_factory=list)

    def by_category(self) -> list[tuple[str, list[BonusGroup]]]:
        """Groups bucketed into :data:`CATEGORY_ORDER`, empty buckets dropped."""
        out: list[tuple[str, list[BonusGroup]]] = []
        for category in CATEGORY_ORDER:
            groups = [g for g in self.groups if g.category == category]
            if groups:
                out.append((category, groups))
        return out


def _signed(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


def _source_label(item, name: str) -> str:
    """What to credit a property to — the skin is named for what it is."""
    if getattr(item, "slot", None) == SKIN_SLOT:
        return "Creature skin (PRC)"
    return name or "(unnamed item)"


def _subject(prop) -> str | None:
    """What a property affects, or ``None`` when it is not routed to a group."""
    pid = prop.property_name
    route = _ROUTING.get(pid)
    if route is None:
        return None
    _category, fixed = route
    if fixed is not None:
        return fixed
    if pid in (0, 27):
        return ABILITY_SUBTYPES.get(prop.subtype, "Ability")
    if pid == 28:
        return f"Armour class ({_AC_TYPES.get(prop.subtype, 'other')})"
    if pid in (40, 49):  # universal / element-specific saving throws
        if prop.subtype in (0, 0xFFFF):
            return "Saving throws"
        element = _SAVE_ELEMENTS.get(prop.subtype)
        return f"Saving throws vs. {element}" if element else "Saving throws (specific)"
    if pid in (41, 50):
        return f"{_SAVE_KINDS.get(prop.subtype, 'Saving throw')} save"
    if pid in (52, 29):
        from vaultkeeper.game.item_properties import _skills

        return _skills().get(prop.subtype, f"Skill {prop.subtype}")
    if pid in _DAMAGE_SUBJECTS:
        kind = _DAMAGE_SUBJECTS[pid]
        damage = DAMAGE_SUBTYPES.get(prop.subtype)
        return f"{kind}: {damage}" if damage else kind
    return None


def _amount(prop) -> int | None:
    """The property's magnitude, or ``None`` when ``CostValue`` is not one."""
    if prop.property_name not in _NUMERIC_PROPS:
        return None
    value = int(prop.cost_value or 0)
    return -value if prop.property_name in _PENALTY_PROPS else value


def item_contributions(items, name_of=None) -> list[BonusGroup]:
    """Group every property of every *equipped* item by what it affects."""
    groups: dict[tuple[str, str], BonusGroup] = {}
    for item in items:
        slot = getattr(item, "slot", None)
        if slot is None or slot in _WORN_SLOTS_EXCLUDED:
            continue  # carried items and ammunition grant nothing
        name = name_of(item) if name_of is not None else getattr(item, "name", "")
        source = _source_label(item, name)
        for entry in getattr(item, "properties", []) or []:
            prop = getattr(entry, "prop", entry)
            subject = _subject(prop)
            category = _ROUTING.get(prop.property_name, ("Other gear properties", None))[0]
            if subject is None:
                subject = "Other gear properties"
            key = (category, subject)
            group = groups.setdefault(key, BonusGroup(category=category, subject=subject))
            group.contributions.append(Contribution(
                source=source, detail=describe_property(prop, None), amount=_amount(prop),
            ))
    return [_collapse(group) for group in groups.values()]


def _collapse(group: BonusGroup) -> BonusGroup:
    """Fold identical ``(source, detail)`` lines into one ``N×`` line.

    The PRC skin carries the same property over and over — thirteen copies of
    "Damage Immunity: Fire 100%" on the owner's character. Thirteen identical
    rows read as a decoding bug; one "13×" row reads as the fact it is.
    """
    seen: dict[tuple[str, str], Contribution] = {}
    order: list[tuple[str, str]] = []
    for c in group.contributions:
        key = (c.source, c.detail)
        if key in seen:
            previous = seen[key]
            seen[key] = Contribution(c.source, c.detail, c.amount, previous.repeats + 1)
        else:
            seen[key] = c
            order.append(key)
    group.contributions = [seen[key] for key in order]
    group.contributions.sort(key=lambda c: (-(abs(c.amount or 0)), c.source.lower()))
    return group


def spell_effects(effects, spell_name=None) -> list[SpellEffect]:
    """Turn raw ``EffectList`` rows into named ongoing effects where possible.

    ``effects`` are the dicts the Effects view already reads. Only a row that
    carries a real spell (or at least a custom tag) can be attributed; the rest
    are reported as unattributed rather than dropped.
    """
    out: list[SpellEffect] = []
    for effect in effects:
        spell = effect.get("spell") or ""
        tag = effect.get("tag") or ""
        if not spell and spell_name is not None:
            spell = spell_name(effect.get("spell_id")) or ""
        out.append(SpellEffect(
            name=spell or tag,
            caster_level=int(effect.get("caster_level") or 0),
            duration=float(effect.get("duration") or 0.0),
            attributed=bool(spell),
        ))
    return out


def compute(items, feats, info, effects=(), name_of=None) -> ActiveBonuses:
    """Build the whole view from what the save records.

    ``items`` are :meth:`SaveEditor.player_items` rows, ``feats`` the
    ``(id, name, is_base)`` rows, ``info`` the parsed character record and
    ``effects`` the Effects view's dicts. ``name_of`` resolves an item's display
    name (strrefs), matching what the rest of the editor shows.
    """
    result = ActiveBonuses()
    result.groups = _ordered(item_contributions(items, name_of))
    result.feat_count = len(feats or ())
    result.spell_effects = spell_effects(effects)

    if info is not None:
        from vaultkeeper.game.character import class_name

        result.classes = [
            f"{class_name(cid)} {level}" for cid, level in getattr(info, "classes", ())
        ]
        # These four the record stores outright — they are the only class-derived
        # numbers that can be quoted without running the rules.
        # Labelled the way the Details tab labels the same fields, so the two
        # screens can't be read as quoting two different numbers.
        result.class_facts = [
            ("Base attack bonus", _signed(getattr(info, "base_attack_bonus", 0))),
            ("Base Fortitude save", _signed(getattr(info, "save_fortitude", 0))),
            ("Base Reflex save", _signed(getattr(info, "save_reflex", 0))),
            ("Base Will save", _signed(getattr(info, "save_will", 0))),
        ]
    return result


def _ordered(groups: list[BonusGroup]) -> list[BonusGroup]:
    """Category order first, then a sensible order inside each category."""
    def sort_key(group: BonusGroup):
        category = (
            CATEGORY_ORDER.index(group.category)
            if group.category in CATEGORY_ORDER else len(CATEGORY_ORDER)
        )
        if group.category == "Ability scores" and group.subject in _ABILITY_ORDER:
            return (category, _ABILITY_ORDER.index(group.subject), "")
        return (category, 99, group.subject.lower())

    return sorted(groups, key=sort_key)


def gear_bonus_for_save(groups, kind: str) -> int | None:
    """The largest gear bonus that applies to one saving throw, or ``None``.

    Both the throw's own group ("Fortitude save") and the universal one
    ("Saving throws") count. *Largest*, not sum: NWN applies only the biggest of
    several same-type bonuses, and this module refuses to add table-row values
    together — see the module docstring.
    """
    wanted = {f"{kind} save".lower(), "saving throws"}
    amounts = [
        group.largest for group in groups
        if group.subject.lower() in wanted and group.largest is not None
    ]
    return max(amounts, key=abs) if amounts else None
