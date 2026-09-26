"""Find player items that lost magical properties, and what their blueprint had.

An item's powers are usually plain item properties (bonus feats, immunities, spell
slots…) stored *on the item*. If something strips them in-game — a module script,
an external editor, an engine quirk — the item keeps its name, tag and blueprint
resref but silently becomes a trinket, and nothing else in the save notices. (Found
on a Holy Symbol of Thoth: 18 properties in SoF3's blueprint, 1 left in the save.)

This module (Qt-free) compares each player item with its **original blueprint** in
the installed modules/haks:

* :func:`find_blueprints` — read only the ``.uti`` blueprints whose resref a player
  item was made from (one key-list read per archive, bytes only on a name hit);
* :func:`find_stripped` — an item is *stripped* when every property it still has is
  also on a blueprint with the same resref and tag, and that blueprint has more.
  An item carrying anything the blueprint lacks was changed on purpose (upgraded,
  crafted, re-enchanted) and is left alone — restoring it would be a guess.

Nothing is applied here: the caller offers each item's missing properties for the
user to pick, and stages them as ordinary property additions.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from nwnfile.formats.erf_reader import ErfReader
from nwnfile.formats.gff import GffStruct, GffType, read_gff

_UTI = 2025
#: Creature weapons/hides: engine- or PRC-managed (the PRC skin is rebuilt all the
#: time), never something to restore from a blueprint.
_SKIP_BASE_ITEMS = frozenset({69, 70, 71, 72, 73})
#: Properties that *limit* an item rather than empower it: use limitations
#: (alignment/class/race/specific alignment, spell-level, sneak attack, minimum
#: ability/skill) and drawbacks (penalties, decreases, vulnerability, weight,
#: movement, the cost-only rows). A player often strips these on purpose to use
#: an item, so a restore never re-adds them unless asked.
LIMITING_PROPERTIES = frozenset({
    62, 63, 64, 65, 88, 89, 90, 91, 95, 96,
    10, 21, 24, 27, 28, 29, 49, 50, 81, 134, *range(120, 128)})
#: The fields that make two properties "the same property".
_KEY_FIELDS = ("PropertyName", "Subtype", "CostTable", "CostValue", "Param1", "Param1Value")


@dataclass(frozen=True)
class PropFields:
    """One property's identifying values (hashable, so it can be counted)."""

    property_name: int
    subtype: int
    cost_table: int
    cost_value: int
    param1: int
    param1_value: int

    @classmethod
    def of(cls, struct: GffStruct) -> PropFields:
        return cls(*(int(struct.get(f) or 0) for f in _KEY_FIELDS))

    @property
    def limiting(self) -> bool:
        """A restriction or drawback, not a power (see :data:`LIMITING_PROPERTIES`)."""
        return self.property_name in LIMITING_PROPERTIES


@dataclass
class ItemFacts:
    """What the comparison needs to know about one player item."""

    path: tuple
    name: str
    tag: str
    resref: str
    base_item: int
    description: str  #: identified description text ("" when none)
    props: list[PropFields]

    @classmethod
    def of(cls, struct: GffStruct, path: tuple) -> ItemFacts:
        return cls(
            path=tuple(path), name=_loc_text(struct.get("LocalizedName")),
            tag=str(struct.get("Tag") or ""),
            resref=str(struct.get("TemplateResRef") or "").strip().lower(),
            base_item=int(struct.get("BaseItem") or 0),
            description=_loc_text(struct.get("DescIdentified")),
            props=_props(struct))


@dataclass
class Blueprint:
    """An item blueprint (``.uti``) found in an installed module or hak."""

    origin: str  #: the module/hak file name
    resref: str
    tag: str
    name: str
    description: str
    props: list[PropFields]


@dataclass
class StrippedItem:
    """A player item missing properties its blueprint has."""

    item: ItemFacts
    blueprint: Blueprint
    missing: list[PropFields]  #: in blueprint order
    #: other blueprints that would also fit (same resref+tag), for an honest note
    alternatives: list[Blueprint] = field(default_factory=list)

    @property
    def lost_powers(self) -> list[PropFields]:
        return [p for p in self.missing if not p.limiting]


def find_blueprints(
    resrefs: Iterable[str], sources: Iterable[Path], *, reader=None,
) -> dict[str, list[Blueprint]]:
    """``{resref: [Blueprint, …]}`` for each wanted resref, in ``sources`` order.

    The same resref can differ between modules (SoF2's Holy Symbol has 14
    properties, SoF3's 18), so every copy is kept for :func:`find_stripped` to
    choose between."""
    reader = reader or ErfReader()
    wanted = {r.lower() for r in resrefs if r}
    found: dict[str, list[Blueprint]] = {}
    if not wanted:
        return found
    for src in (Path(s) for s in sources):
        if not src.exists():
            continue
        try:
            resources = reader.list_resources(src)
        except Exception:  # noqa: BLE001 — unreadable archive, skip
            continue
        for r in resources:
            if r.res_type != _UTI or r.resref.lower() not in wanted:
                continue
            try:
                root = read_gff(reader.read_resource_bytes(src, r)).root
            except Exception:  # noqa: BLE001 — malformed blueprint, skip
                continue
            found.setdefault(r.resref.lower(), []).append(Blueprint(
                origin=src.name, resref=r.resref.lower(),
                tag=str(root.get("Tag") or ""),
                name=_loc_text(root.get("LocalizedName")),
                description=_loc_text(root.get("DescIdentified")),
                props=_props(root)))
    return found


def find_stripped(
    items: Iterable[ItemFacts], blueprints: dict[str, list[Blueprint]],
) -> list[StrippedItem]:
    """Every item whose properties are a strict subset of a matching blueprint's.

    A blueprint matches on resref + tag (case-insensitive). Among matches the one
    with the same identified description wins, then the same name, then the one
    needing the fewest additions — the conservative pick when nothing tells them
    apart. The others are reported as ``alternatives``.

    An item missing only restrictions/drawbacks is not reported: that is what a
    player unlocking an item looks like, not lost power."""
    out: list[StrippedItem] = []
    for item in items:
        if item.base_item in _SKIP_BASE_ITEMS:
            continue
        fits = [bp for bp in blueprints.get(item.resref, ())
                if bp.tag.lower() == item.tag.lower() and _missing(item, bp)]
        if not fits:
            continue
        fits.sort(key=lambda bp: (
            not (item.description and bp.description == item.description),
            not (item.name and bp.name == item.name),
            len(_missing(item, bp))))
        best = fits[0]
        if not any(not p.limiting for p in _missing(item, best)):
            continue
        out.append(StrippedItem(
            item=item, blueprint=best, missing=_missing(item, best),
            alternatives=fits[1:]))
    return out


def _missing(item: ItemFacts, bp: Blueprint) -> list[PropFields]:
    """What ``bp`` has that ``item`` lacks — or ``[]`` when the item has anything
    ``bp`` doesn't (a deliberately changed item) or lacks nothing."""
    have, want = Counter(item.props), Counter(bp.props)
    if have - want:  # carries something the blueprint never had
        return []
    lacking = want - have
    out: list[PropFields] = []
    for p in bp.props:  # keep blueprint order, honour duplicates
        if lacking[p] > 0:
            out.append(p)
            lacking[p] -= 1
    return out


def _props(struct: GffStruct) -> list[PropFields]:
    plist = struct.fields.get("PropertiesList")
    if plist is None or plist.type != GffType.LIST:
        return []
    return [PropFields.of(s) for s in plist.value.structs]


def _loc_text(loc) -> str:
    if loc is None:
        return ""
    try:
        return (loc.text() or "").strip()
    except Exception:  # noqa: BLE001 — not a LocString
        return str(loc).strip()
