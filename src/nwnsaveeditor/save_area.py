"""Decode the *contents* of a save's areas — stores, creatures, containers, factions.

The Save Game Viewer's :mod:`vaultkeeper.game.save_game` reads a ``.sav``'s
``module.ifo`` (module state) and each area's *name*. This module goes one level
deeper: for a given area it reads the ``<area>.git`` (the area's dynamic instance
state) and ``<area>.are`` (static metadata) to surface

* **stores / merchants** — pricing and every item for sale,
* **creatures** — NPCs/monsters with their equipped + carried gear and gold,
* **placeable containers** — chests/corpses/barrels and their loot,
* **area metadata** — tileset, size, interior/underground/natural flags, object counts,

plus the module-wide **faction** list (``repute.fac``). Every item is decoded with
the existing :class:`~nwnfile.formats.bic_reader.BicFileReader` item reader
(the ``.git`` item structs share the ``.bic`` item layout), so magical properties,
icons and ``dialog.tlk`` names all resolve exactly as they do for a character's own
inventory. Read-only, best-effort (missing/odd resources degrade to empty).

No ``.jrl`` (journal) support: none of the observed saves bundle one — the player's
quest state lives elsewhere — so there is nothing to decode here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from nwnfile.formats.bic_reader import (
    _GFF,
    BicFileReader,
    EquippedItem,
    InventoryItem,
    _GFFType,
)
from nwnfile.formats.erf_reader import ErfReader
from nwnfile.item_names import ItemNameResolver

_GIT_RESTYPE = 2023  # <area>.git — area instance (creatures, placeables, stores …)
_ARE_RESTYPE = 2012  # <area>.are — static area metadata
_FAC_RESTYPE = 2038  # repute.fac — faction table

#: ``.are`` ``Flags`` bit meanings (AREA_FLAG_*).
_AREA_INTERIOR = 0x1
_AREA_UNDERGROUND = 0x2
_AREA_NATURAL = 0x4

#: Creatures that are PRC/engine bookkeeping objects, not real inhabitants — hidden
#: from the listing (but counted). Matched on the instance's first name or tag.
_UTILITY_CREATURE_NAMES = {"prc_2da_cache"}
_UTILITY_CREATURE_TAGS = {"Bioware2DACache"}


@dataclass
class Store:
    """A merchant in an area — its pricing and stock (flattened across panels)."""

    tag: str = ""
    name: str = ""
    store_gold: int = -1
    markup: int = 0
    markdown: int = 0
    identify_price: int = -1
    max_buy_price: int = -1
    black_market: bool = False
    items: list[InventoryItem] = field(default_factory=list)
    #: the ``.git`` list new stock is appended to (its first category panel).
    git_path: tuple = ()


@dataclass
class CreatureRef:
    """A creature instance — its identity, gold and gear."""

    name: str = ""
    tag: str = ""
    gold: int = 0
    equipped: list[EquippedItem] = field(default_factory=list)
    carried: list[InventoryItem] = field(default_factory=list)
    #: the ``.git`` list an item given to this creature is appended to.
    git_path: tuple = ()

    @property
    def item_count(self) -> int:
        return len(self.equipped) + len(self.carried)


@dataclass
class Container:
    """A placeable that holds items (chest/corpse/barrel …)."""

    name: str = ""
    tag: str = ""
    items: list[InventoryItem] = field(default_factory=list)
    #: the ``.git`` list an item put into this container is appended to.
    git_path: tuple = ()


@dataclass
class AreaContents:
    """Everything decoded for one area of a save."""

    resref: str = ""
    name: str = ""
    tileset: str = ""
    width: int = 0
    height: int = 0
    interior: bool = False
    underground: bool = False
    natural: bool = False
    stores: list[Store] = field(default_factory=list)
    creatures: list[CreatureRef] = field(default_factory=list)
    containers: list[Container] = field(default_factory=list)
    #: utility/bookkeeping creatures filtered out of ``creatures``.
    hidden_creatures: int = 0
    #: counts of the remaining object kinds (for the area summary).
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def dimensions(self) -> str:
        return f"{self.width}×{self.height}" if self.width and self.height else ""

    @property
    def terrain(self) -> str:
        parts = [
            label
            for flag, label in (
                (self.interior, "interior"),
                (self.underground, "underground"),
                (self.natural, "natural"),
            )
            if flag
        ]
        return ", ".join(parts) or "exterior"


@dataclass
class Faction:
    """A faction in the module and (when known) its standing toward the player."""

    name: str = ""
    global_faction: bool = False
    reputation_to_pc: int | None = None


# --------------------------------------------------------------------------- #
# GFF helpers
# --------------------------------------------------------------------------- #
def _list(gff: _GFF, struct_id: int, label: str) -> list[int]:
    for name, ftype, raw in gff.iter_struct_fields(struct_id):
        if name == label and ftype == _GFFType.LIST:
            return gff.read_value(ftype, raw) or []
    return []


def _fields(gff: _GFF, struct_id: int) -> dict[str, tuple[int, bytes]]:
    return {name: (ftype, raw) for name, ftype, raw in gff.iter_struct_fields(struct_id)}


def _int(fields: dict, gff: _GFF, label: str, default: int = 0) -> int:
    if label in fields:
        value = gff.read_value(*fields[label])
        if isinstance(value, int):
            return value
    return default


def _locstring(fields: dict, gff: _GFF, label: str, resolver: ItemNameResolver | None) -> str:
    """A CExoLocString's inline text, or its ``dialog.tlk`` string, or ``""``."""
    if label not in fields:
        return ""
    ftype, raw = fields[label]
    text = (gff.read_value(ftype, raw) or "").strip()
    if text or resolver is None:
        return text
    strref = gff.read_locstring_strref(raw)
    return (resolver.name_for(strref) or "") if strref >= 0 else ""


# --------------------------------------------------------------------------- #
# area contents
# --------------------------------------------------------------------------- #
def read_area_contents(
    sav_path: Path, resref: str, *, resolver: ItemNameResolver | None = None
) -> AreaContents | None:
    """Decode one area's ``.git`` (+ ``.are``) from a ``.sav``; ``None`` if unreadable."""
    reader = ErfReader()
    git_res = reader.find_resource(sav_path, resref, res_type=_GIT_RESTYPE)
    if git_res is None:
        return None
    try:
        git = _GFF(reader.read_resource_bytes(sav_path, git_res))
    except Exception:
        return None

    area = AreaContents(resref=resref, name=resref)
    _read_area_meta(reader, sav_path, resref, area, resolver)

    for index, sid in enumerate(_list(git, 0, "StoreList")):
        area.stores.append(_read_store(git, sid, resolver, (("StoreList", index),)))
    for index, sid in enumerate(_list(git, 0, "Creature List")):
        creature = _read_creature(git, sid, resolver, (("Creature List", index),))
        if creature is None:
            area.hidden_creatures += 1
        else:
            area.creatures.append(creature)
    for index, sid in enumerate(_list(git, 0, "Placeable List")):
        container = _read_container(git, sid, resolver, (("Placeable List", index),))
        if container is not None:
            area.containers.append(container)

    area.counts = {
        "placeables": len(_list(git, 0, "Placeable List")),
        "doors": len(_list(git, 0, "Door List")),
        "triggers": len(_list(git, 0, "TriggerList")),
        "encounters": len(_list(git, 0, "Encounter List")),
        "waypoints": len(_list(git, 0, "WaypointList")),
        "sounds": len(_list(git, 0, "SoundList")),
    }
    return area


def _read_area_meta(
    reader: ErfReader,
    sav_path: Path,
    resref: str,
    area: AreaContents,
    resolver: ItemNameResolver | None,
) -> None:
    are_res = reader.find_resource(sav_path, resref, res_type=_ARE_RESTYPE)
    if are_res is None:
        return
    try:
        are = _GFF(reader.read_resource_bytes(sav_path, are_res))
    except Exception:
        return
    fields = _fields(are, 0)
    name = _locstring(fields, are, "Name", resolver)
    if name:
        area.name = name
    if "Tileset" in fields:
        area.tileset = (are.read_value(*fields["Tileset"]) or "").strip()
    area.width = _int(fields, are, "Width")
    area.height = _int(fields, are, "Height")
    flags = _int(fields, are, "Flags")
    area.interior = bool(flags & _AREA_INTERIOR)
    area.underground = bool(flags & _AREA_UNDERGROUND)
    area.natural = bool(flags & _AREA_NATURAL)


def _with_paths(
    items: list[InventoryItem], owner: tuple, list_field: str
) -> list[InventoryItem]:
    """Record where each item sits in the ``.git``, so it can be edited in place.

    Nested container contents are addressed through their holder's own
    ``ItemList``, which is how the item structs actually nest on disk.
    """
    for index, item in enumerate(items):
        item.git_path = (*owner, (list_field, index))
        _with_paths(item.contents, item.git_path, "ItemList")
    return items


def _read_store(
    git: _GFF, struct_id: int, resolver: ItemNameResolver | None, path: tuple = ()
) -> Store:
    fields = _fields(git, struct_id)
    store = Store(
        tag=(git.read_value(*fields["Tag"]) if "Tag" in fields else "") or "",
        name=_locstring(fields, git, "LocName", resolver),
        store_gold=_int(fields, git, "StoreGold", -1),
        markup=_int(fields, git, "MarkUp"),
        markdown=_int(fields, git, "MarkDown"),
        identify_price=_int(fields, git, "IdentifyPrice", -1),
        max_buy_price=_int(fields, git, "MaxBuyPrice", -1),
        black_market=bool(_int(fields, git, "BlackMarket")),
    )
    if not store.name:
        store.name = store.tag or "Store"
    # A store's stock is split across category panels, each with its own ItemList.
    items: list[InventoryItem] = []
    for panel_index, panel in enumerate(_list(git, struct_id, "StoreList")):
        panel_path = (*path, ("StoreList", panel_index))
        items.extend(_with_paths(
            [BicFileReader._read_item(git, iid) for iid in _list(git, panel, "ItemList")],
            panel_path, "ItemList",
        ))
    if resolver is not None:
        resolver.resolve_items(items)
    store.items = items
    # New stock goes into the first category panel; a store always has one.
    store.git_path = (*path, ("StoreList", 0), ("ItemList", None))
    return store


def _read_creature(
    git: _GFF, struct_id: int, resolver: ItemNameResolver | None, path: tuple = ()
) -> CreatureRef | None:
    fields = _fields(git, struct_id)
    first = _locstring(fields, git, "FirstName", resolver)
    last = _locstring(fields, git, "LastName", resolver)
    tag = (git.read_value(*fields["Tag"]) if "Tag" in fields else "") or ""
    if first in _UTILITY_CREATURE_NAMES or tag in _UTILITY_CREATURE_TAGS:
        return None
    name = " ".join(part for part in (first, last) if part).strip()
    equipped = BicFileReader._read_equipped(git, _list(git, struct_id, "Equip_ItemList"))
    _with_paths([e.item for e in equipped], path, "Equip_ItemList")
    carried = _with_paths(
        [BicFileReader._read_item(git, iid) for iid in _list(git, struct_id, "ItemList")],
        path, "ItemList",
    )
    if resolver is not None:
        resolver.resolve_items([e.item for e in equipped])
        resolver.resolve_items(carried)
    return CreatureRef(
        name=name or tag or "(creature)",
        tag=tag,
        gold=_int(fields, git, "Gold"),
        equipped=equipped,
        carried=carried,
        git_path=(*path, ("ItemList", None)),
    )


def _read_container(
    git: _GFF, struct_id: int, resolver: ItemNameResolver | None, path: tuple = ()
) -> Container | None:
    """A placeable with items; ``None`` for the (many) plain scenery placeables."""
    item_ids = _list(git, struct_id, "ItemList")
    if not item_ids:
        return None
    fields = _fields(git, struct_id)
    items = _with_paths(
        [BicFileReader._read_item(git, iid) for iid in item_ids], path, "ItemList"
    )
    if resolver is not None:
        resolver.resolve_items(items)
    return Container(
        name=_locstring(fields, git, "LocName", resolver)
        or (git.read_value(*fields["Tag"]) if "Tag" in fields else "")
        or "Container",
        tag=(git.read_value(*fields["Tag"]) if "Tag" in fields else "") or "",
        items=items,
        git_path=(*path, ("ItemList", None)),
    )


# --------------------------------------------------------------------------- #
# factions
# --------------------------------------------------------------------------- #
def read_factions(sav_path: Path) -> list[Faction]:
    """The module's factions and their reputation toward the player (best-effort)."""
    reader = ErfReader()
    res = reader.find_resource(sav_path, "repute", res_type=_FAC_RESTYPE)
    if res is None:
        res = next(
            (r for r in reader.list_resources(sav_path) if r.res_type == _FAC_RESTYPE), None
        )
    if res is None:
        return []
    try:
        fac = _GFF(reader.read_resource_bytes(sav_path, res))
    except Exception:
        return []

    names: list[str] = []
    globals_: list[bool] = []
    for sid in _list(fac, 0, "FactionList"):
        fields = _fields(fac, sid)
        name = (fac.read_value(*fields["FactionName"]) if "FactionName" in fields else "") or ""
        names.append(name)
        globals_.append(bool(_int(fields, fac, "FactionGlobal")))

    # RepList holds pairwise standings; row toward the PC faction (index 0) is the
    # interesting one for a viewer.
    rep_to_pc: dict[int, int] = {}
    for sid in _list(fac, 0, "RepList"):
        fields = _fields(fac, sid)
        f1 = _int(fields, fac, "FactionID1", -1)
        f2 = _int(fields, fac, "FactionID2", -1)
        rep = _int(fields, fac, "FactionRep", -1)
        if f2 == 0 and f1 >= 0:
            rep_to_pc[f1] = rep
        elif f1 == 0 and f2 >= 0:
            rep_to_pc.setdefault(f2, rep)

    factions: list[Faction] = []
    for index, name in enumerate(names):
        factions.append(
            Faction(
                name=name or f"Faction {index}",
                global_faction=globals_[index] if index < len(globals_) else False,
                reputation_to_pc=rep_to_pc.get(index),
            )
        )
    return factions
