"""Edit a save game and write it back as a **new** save (read-only on the original).

The first, safest edit target: **store settings** (a merchant's pricing). A store
lives in its area's ``<area>.git`` (``StoreList``); this loads that resource's GFF
tree, mutates the store's scalar fields in place, and rewrites the ``.sav`` with the
edited ``.git`` swapped in — via the byte-faithful :mod:`vaultkeeper.core.formats.gff`
writer + :mod:`vaultkeeper.core.formats.erf_writer`, so everything untouched is
preserved exactly.

Safety model:

* **Never touch the original.** :meth:`SaveEditor.save_as` writes a brand-new save
  folder; the source save is the backup.
* **Verify after write.** The new ``.sav`` is re-read and each edited resource's
  bytes are checked against what was written.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from vaultkeeper.core.formats.bic_reader import ItemProperty
from vaultkeeper.core.formats.erf_reader import ErfReader
from vaultkeeper.core.formats.erf_writer import rewrite_erf
from vaultkeeper.core.formats.gff import Gff, GffField, GffStruct, GffType, read_gff, write_gff
from vaultkeeper.game.save_game import SaveGame

_GIT_RESTYPE = 2023
_IFO_RESTYPE = 2014
_PLAYER_LIST = "Mod_PlayerList"


class SaveEditError(Exception):
    """A save could not be read, edited or written."""


@dataclass
class EditableProperty:
    """A magical property on a player item, with its index for path-based editing."""

    index: int  #: position in the item's PropertiesList
    prop: ItemProperty  #: for describing/naming it (game.item_properties)
    uses_per_day: int  #: 255 = unlimited


@dataclass
class EditableSkill:
    """A player-character skill: its id, name and current rank."""

    index: int
    name: str
    rank: int


@dataclass
class EditableItem:
    """A player-character item located by its GFF path, for property editing."""

    path: tuple  #: ((field_label, index), …) from the player struct, e.g. (("Equip_ItemList", 0),)
    slot: int | None  #: equipment slot bit if equipped, else None (carried)
    name: str
    name_strref: int
    resref: str
    base_item: int
    model_part: int
    properties: list[EditableProperty]


@dataclass
class PendingChange:
    """One staged edit, for the viewer's pending-changes list + dirty markers."""

    kind: str  #: e.g. "store" — which editor produced it
    key: tuple  #: identifies the edited object (e.g. ``(area_resref, store_index)``)
    where: str  #: human label, e.g. "Nature Store — Beorunna's Well"
    summary: str  #: what changed, e.g. "buy markup 200%→120%; black market off→on"


def _fmt_pct(value: int) -> str:
    return f"{value}%"


def _fmt_gold(value: int) -> str:
    return "unlimited" if value < 0 else str(value)


def _fmt_bool(value: int) -> str:
    return "on" if value else "off"


def _fmt_uses(value: int) -> str:
    return "unlimited" if value >= 255 else str(value)


#: store edit key -> (GFF label, "int"|"bool", display name, value formatter).
_STORE_FIELDS: dict[str, tuple[str, str, str, object]] = {
    "markup": ("MarkUp", "int", "buy markup", _fmt_pct),
    "markdown": ("MarkDown", "int", "sell-back markdown", _fmt_pct),
    "store_gold": ("StoreGold", "int", "store gold", _fmt_gold),
    "identify_price": ("IdentifyPrice", "int", "identify price",
                       lambda v: "none" if v < 0 else str(v)),
    "max_buy_price": ("MaxBuyPrice", "int", "max buy price",
                      lambda v: "no limit" if v < 0 else str(v)),
    "black_market": ("BlackMarket", "bool", "black market", _fmt_bool),
}


class SaveEditor:
    """Accumulates edits to a save's resources and writes them to a new save.

    Edits are staged in memory (the source is never modified); :meth:`save_as`
    materialises them into a new save folder and verifies the result.
    """

    #: editable store field names (the public keyword args of set_store_fields).
    STORE_FIELDS = tuple(_STORE_FIELDS)

    def __init__(self, save: SaveGame) -> None:
        if save.sav_path is None:
            raise SaveEditError("save has no .sav file")
        self._save = save
        self._reader = ErfReader()
        self._areas: dict[str, Gff] = {}  # area resref (lower) -> loaded .git tree
        #: original store field values, per (area, index), captured on first touch.
        self._store_originals: dict[tuple[str, int], dict[str, object]] = {}
        #: staged changes keyed by (kind, key) so re-editing an object replaces it.
        self._changes: dict[tuple[str, tuple], PendingChange] = {}
        #: the player character's module.ifo tree + its player.bic mirror (lazy).
        self._module: Gff | None = None
        self._bic: Gff | None = None
        self._bic_loaded = False
        self._char_dirty = False
        #: original property (cost, uses) per (item_path, prop_index), first touch.
        self._prop_originals: dict[tuple[tuple, int], tuple[int, int]] = {}
        self._max_obj_id: int | None = None  # for handing out fresh item ObjectIds
        self._add_seq = 0  # distinguishes each "add item" pending entry
        #: original skill rank per skill index, captured on first touch.
        self._skill_originals: dict[int, int] = {}
        #: the character's feat ids at load, captured on the first feat op.
        self._feat_originals: set[int] | None = None

    @property
    def has_edits(self) -> bool:
        return bool(self._changes)

    def pending_changes(self) -> list[PendingChange]:
        """The staged edits, in the order they were first made."""
        return list(self._changes.values())

    def discard(self) -> None:
        """Drop every staged edit (re-reads happen fresh afterwards)."""
        self._areas.clear()
        self._store_originals.clear()
        self._changes.clear()
        self._module = None
        self._bic = None
        self._bic_loaded = False
        self._char_dirty = False
        self._prop_originals.clear()
        self._max_obj_id = None
        self._add_seq = 0
        self._skill_originals.clear()
        self._feat_originals = None

    # -- store editing ---------------------------------------------------- #
    def set_store_fields(
        self, area_resref: str, store_index: int, *, where: str | None = None, **values
    ) -> None:
        """Stage edits to a store's scalar settings (only non-``None`` values apply).

        ``where`` is a display label for the pending-changes list. Re-editing the
        same store updates its single pending entry; reverting every field to its
        original value removes it.
        """
        store = self._store_struct(area_resref, store_index)
        tkey = (area_resref.lower(), store_index)
        if tkey not in self._store_originals:
            self._store_originals[tkey] = {
                label: store.fields[label].value
                for label, _kind, _disp, _fmt in _STORE_FIELDS.values()
                if label in store.fields
            }
        for key, value in values.items():
            if value is None:
                continue
            if key not in _STORE_FIELDS:
                raise SaveEditError(f"unknown store field {key!r}")
            label, kind, _disp, _fmt = _STORE_FIELDS[key]
            gfield = store.fields.get(label)
            if gfield is None:
                raise SaveEditError(f"store has no {label!r} field to edit")
            gfield.value = int(value) if kind == "int" else (1 if value else 0)
        self._record_store_change(area_resref, store_index, store, where)

    def _record_store_change(self, area_resref, store_index, store, where) -> None:
        tkey = (area_resref.lower(), store_index)
        original = self._store_originals[tkey]
        parts = []
        for _key, (label, _kind, disp, fmt) in _STORE_FIELDS.items():
            if label not in store.fields:
                continue
            now = store.fields[label].value
            was = original.get(label)
            if now != was:
                parts.append(f"{disp} {fmt(was)}→{fmt(now)}")
        change_key = ("store", tkey)
        if parts:
            self._changes[change_key] = PendingChange(
                kind="store", key=(area_resref, store_index),
                where=where or (store.get("Tag") or f"Store {store_index}"),
                summary="; ".join(parts),
            )
        else:  # reverted to original -> no longer a pending change
            self._changes.pop(change_key, None)

    def _area_tree(self, area_resref: str) -> Gff:
        key = area_resref.lower()
        if key not in self._areas:
            res = self._reader.find_resource(
                self._save.sav_path, area_resref, res_type=_GIT_RESTYPE
            )
            if res is None:
                raise SaveEditError(f"area {area_resref!r} is not in this save")
            self._areas[key] = read_gff(
                self._reader.read_resource_bytes(self._save.sav_path, res)
            )
        return self._areas[key]

    def _store_struct(self, area_resref: str, store_index: int):
        field = self._area_tree(area_resref).root.fields.get("StoreList")
        if field is None or field.type != GffType.LIST:
            raise SaveEditError(f"area {area_resref!r} has no stores")
        stores = field.value.structs
        if not 0 <= store_index < len(stores):
            raise SaveEditError(f"store index {store_index} out of range for {area_resref!r}")
        return stores[store_index]

    # -- player-item property editing ------------------------------------ #
    def player_items(self) -> list[EditableItem]:
        """Every item on the player character (equipped + carried, incl. bags).

        Read from ``module.ifo`` ``Mod_PlayerList[0]`` — the copy the engine loads
        for a saved game — each tagged with the GFF path used to edit it.
        """
        player = self._player_struct(self._module_tree())
        items: list[EditableItem] = []
        equip = player.fields.get("Equip_ItemList")
        if equip is not None and equip.type == GffType.LIST:
            for i, struct in enumerate(equip.value.structs):
                path = (("Equip_ItemList", i),)
                items.append(self._editable_item(struct, path, struct.struct_type))
        self._walk_carried(player, (), items)
        return items

    def _walk_carried(self, container: GffStruct, base: tuple, out: list) -> None:
        field = container.fields.get("ItemList")
        if field is None or field.type != GffType.LIST:
            return
        for i, struct in enumerate(field.value.structs):
            path = (*base, ("ItemList", i))
            out.append(self._editable_item(struct, path, None))
            self._walk_carried(struct, path, out)  # a bag's own contents

    @staticmethod
    def _editable_item(struct: GffStruct, path: tuple, slot: int | None) -> EditableItem:
        loc = struct.get("LocalizedName")
        name = loc.text() if loc is not None else ""
        name_strref = loc.strref if loc is not None else -1
        resref = (struct.get("TemplateResRef") or "").strip()
        props: list[EditableProperty] = []
        plist = struct.fields.get("PropertiesList")
        if plist is not None and plist.type == GffType.LIST:
            for j, ps in enumerate(plist.value.structs):
                props.append(EditableProperty(
                    index=j,
                    prop=ItemProperty(
                        property_name=ps.get("PropertyName") or 0,
                        subtype=ps.get("Subtype") or 0,
                        cost_table=ps.get("CostTable") or 0,
                        cost_value=ps.get("CostValue") or 0,
                        param1=ps.get("Param1") or 0,
                        param1_value=ps.get("Param1Value") or 0,
                    ),
                    uses_per_day=ps.get("UsesPerDay") if ps.get("UsesPerDay") is not None else 255,
                ))
        return EditableItem(
            path=path, slot=slot,
            name=name or (f"(unnamed: {resref})" if resref else "(item)"),
            name_strref=name_strref, resref=resref,
            base_item=struct.get("BaseItem") or -1,
            model_part=struct.get("ModelPart1") or 0,
            properties=props,
        )

    def set_property_cost(
        self, item_path: tuple, prop_index: int, *,
        cost_value: int | None = None, uses_per_day: int | None = None,
        where: str = "", prop_label: str = "property",
    ) -> None:
        """Stage a change to one property's magnitude (and optionally uses/day).

        Applied to ``module.ifo`` (authoritative) and mirrored into ``player.bic``.
        Reverting to the original magnitude removes the pending entry.
        """
        okey = (tuple(item_path), prop_index)
        base_ps = self._property_struct(self._module_tree(), item_path, prop_index)
        if okey not in self._prop_originals:
            self._prop_originals[okey] = (
                base_ps.get("CostValue") or 0,
                base_ps.get("UsesPerDay") if base_ps.get("UsesPerDay") is not None else 255,
            )
        for tree in self._targets():
            self._apply_property(tree, item_path, prop_index, cost_value, uses_per_day)
        self._char_dirty = True
        self._record_property_change(item_path, prop_index, base_ps, where, prop_label)

    def _targets(self) -> list[Gff]:
        trees = [self._module_tree()]
        bic = self._bic_tree()
        if bic is not None:
            trees.append(bic)
        return trees

    def _apply_property(self, tree, item_path, prop_index, cost_value, uses_per_day) -> None:
        try:
            ps = self._property_struct(tree, item_path, prop_index)
        except SaveEditError:
            return  # player.bic structure diverged from module.ifo; ifo is authoritative
        if cost_value is not None and "CostValue" in ps.fields:
            ps.fields["CostValue"].value = int(cost_value)
        if uses_per_day is not None and "UsesPerDay" in ps.fields:
            ps.fields["UsesPerDay"].value = int(uses_per_day)

    def _record_property_change(self, item_path, prop_index, ps, where, prop_label) -> None:
        was_cost, was_uses = self._prop_originals[(tuple(item_path), prop_index)]
        now_cost = ps.get("CostValue") or 0
        now_uses = ps.get("UsesPerDay") if ps.get("UsesPerDay") is not None else 255
        parts = []
        if now_cost != was_cost:
            parts.append(f"+{was_cost}→+{now_cost}")
        if now_uses != was_uses:
            parts.append(f"{_fmt_uses(was_uses)}→{_fmt_uses(now_uses)}/day")
        change_key = ("property", (tuple(item_path), prop_index))
        if parts:
            self._changes[change_key] = PendingChange(
                kind="property", key=(item_path, prop_index),
                where=where or "item", summary=f"{prop_label}: {', '.join(parts)}",
            )
        else:
            self._changes.pop(change_key, None)

    def _module_tree(self) -> Gff:
        if self._module is None:
            res = self._reader.find_resource(self._save.sav_path, "module", res_type=_IFO_RESTYPE)
            if res is None:
                raise SaveEditError("save has no module.ifo")
            self._module = read_gff(self._reader.read_resource_bytes(self._save.sav_path, res))
        return self._module

    def _bic_tree(self) -> Gff | None:
        if not self._bic_loaded:
            self._bic_loaded = True
            bic = self._save.player_bic
            if bic is not None:
                try:
                    self._bic = read_gff(bic.read_bytes())
                except Exception:
                    self._bic = None
        return self._bic

    @staticmethod
    def _player_struct(tree: Gff) -> GffStruct:
        # module.ifo wraps the character in Mod_PlayerList; player.bic *is* the character.
        field = tree.root.fields.get(_PLAYER_LIST)
        if field is not None and field.type == GffType.LIST and field.value.structs:
            return field.value.structs[0]
        if tree.root.fields.keys() & {"Equip_ItemList", "ItemList", "FeatList"}:
            return tree.root
        raise SaveEditError("save has no player character")

    def _item_struct(self, tree: Gff, item_path: tuple) -> GffStruct:
        struct = self._player_struct(tree)
        for label, index in item_path:
            field = struct.fields.get(label)
            if field is None or field.type != GffType.LIST:
                raise SaveEditError(f"item path {item_path} does not resolve")
            if not 0 <= index < len(field.value.structs):
                raise SaveEditError(f"item path {item_path} does not resolve")
            struct = field.value.structs[index]
        return struct

    def _property_struct(self, tree: Gff, item_path: tuple, prop_index: int) -> GffStruct:
        plist = self._item_struct(tree, item_path).fields.get("PropertiesList")
        if plist is None or plist.type != GffType.LIST:
            raise SaveEditError(f"property {prop_index} out of range")
        if not 0 <= prop_index < len(plist.value.structs):
            raise SaveEditError(f"property {prop_index} out of range")
        return plist.value.structs[prop_index]

    # -- add items -------------------------------------------------------- #
    def add_item_copy(self, source_path: tuple, *, where: str = "") -> None:
        """Append a copy of an existing player item to the carried inventory.

        Cloning a known-good item is the safe way to "add an item": it is already
        valid for this character/module. The clone gets ``struct_type`` 0 (carried)
        and a fresh unique ``ObjectId`` so it can't collide with the original, and
        is appended to both ``module.ifo`` and the ``player.bic`` mirror.
        """
        import copy

        source = self._item_struct(self._module_tree(), source_path)
        clone = copy.deepcopy(source)
        clone.struct_type = 0  # a carried item (equipped items carry a slot bit)
        new_id = self._next_object_id()
        if "ObjectId" in clone.fields:
            clone.fields["ObjectId"].value = new_id
        for tree in self._targets():
            carried = self._player_struct(tree).fields.get("ItemList")
            if carried is not None and carried.type == GffType.LIST:
                carried.value.structs.append(copy.deepcopy(clone))
        self._char_dirty = True
        self._add_seq += 1
        name = where or (clone.get("TemplateResRef") or "item")
        self._changes[("add-item", self._add_seq)] = PendingChange(
            kind="add-item", key=("add-item", self._add_seq),
            where=name, summary="added a copy to inventory",
        )

    def _next_object_id(self) -> int:
        """A fresh ObjectId above every real (< OBJECT_INVALID) id in module.ifo."""
        if self._max_obj_id is None:
            ids: list[int] = []
            self._collect_object_ids(self._module_tree().root, ids)
            valid = [i for i in ids if i < 0x7F000000]
            self._max_obj_id = max(valid) if valid else 0
        self._max_obj_id += 1
        return self._max_obj_id

    def _collect_object_ids(self, struct: GffStruct, out: list[int]) -> None:
        for field in struct.fields.values():
            if field.type == GffType.STRUCT:
                self._collect_object_ids(field.value, out)
            elif field.type == GffType.LIST:
                for child in field.value.structs:
                    self._collect_object_ids(child, out)
        oid = struct.fields.get("ObjectId")
        if oid is not None:
            out.append(oid.value)

    # -- skill editing ---------------------------------------------------- #
    def player_skills(self) -> list[EditableSkill]:
        """The player character's skills (id, name, rank), in skill-id order."""
        from vaultkeeper.game.character_reference import default_reference

        ref = default_reference()
        skills = self._player_struct(self._module_tree()).fields.get("SkillList")
        if skills is None or skills.type != GffType.LIST:
            return []
        return [
            EditableSkill(i, ref.skill_name(i), struct.get("Rank") or 0)
            for i, struct in enumerate(skills.value.structs)
        ]

    def set_skill_rank(self, skill_index: int, rank: int, *, where: str = "") -> None:
        """Stage a change to a skill's rank (reverting to its original removes it)."""
        if skill_index not in self._skill_originals:
            self._skill_originals[skill_index] = (
                self._skill_struct(self._module_tree(), skill_index).get("Rank") or 0
            )
        for tree in self._targets():
            try:
                self._skill_struct(tree, skill_index).fields["Rank"].value = int(rank)
            except SaveEditError:
                continue  # player.bic diverged; module.ifo is authoritative
        self._char_dirty = True
        was, now = self._skill_originals[skill_index], int(rank)
        change_key = ("skill", skill_index)
        if now != was:
            self._changes[change_key] = PendingChange(
                kind="skill", key=skill_index,
                where=where or f"Skill {skill_index}", summary=f"rank {was}→{now}",
            )
        else:
            self._changes.pop(change_key, None)

    def _skill_struct(self, tree: Gff, skill_index: int) -> GffStruct:
        skills = self._player_struct(tree).fields.get("SkillList")
        if skills is None or skills.type != GffType.LIST:
            raise SaveEditError("character has no skills")
        if not 0 <= skill_index < len(skills.value.structs):
            raise SaveEditError(f"skill {skill_index} out of range")
        return skills.value.structs[skill_index]

    # -- feat editing ----------------------------------------------------- #
    def player_feats(self) -> list[tuple[int, str, bool]]:
        """The character's feats as ``(feat_id, name, is_base)`` (name-sorted).

        ``is_base`` is False for PRC feats — those are regenerated by PRC's scripts
        so editing them via ``FeatList`` may not persist in-game (warn the user).
        """
        from vaultkeeper.game.character_reference import default_reference

        ref = default_reference()
        feats = self._feat_list(self._module_tree())
        if feats is None:
            return []
        rows = [
            (fid, ref.feat_name(fid), ref.is_base_feat(fid))
            for fid in sorted({s.get("Feat") for s in feats.structs if s.get("Feat") is not None})
        ]
        rows.sort(key=lambda r: r[1].lower())
        return rows

    def add_feat(self, feat_id: int) -> None:
        """Stage adding a feat id to the character's FeatList (both trees)."""
        self._ensure_feat_originals()
        for tree in self._targets():
            feats = self._feat_list(tree)
            if feats is not None and feat_id not in self._feat_ids(feats):
                struct_type = feats.structs[0].struct_type if feats.structs else 1
                feats.structs.append(GffStruct(
                    struct_type=struct_type,
                    fields={"Feat": GffField(GffType.WORD, feat_id)},
                ))
        self._char_dirty = True
        self._recompute_feat_changes()

    def remove_feat(self, feat_id: int) -> None:
        """Stage removing a feat id from the character's FeatList (both trees)."""
        self._ensure_feat_originals()
        for tree in self._targets():
            feats = self._feat_list(tree)
            if feats is not None:
                feats.structs[:] = [s for s in feats.structs if s.get("Feat") != feat_id]
        self._char_dirty = True
        self._recompute_feat_changes()

    def _feat_list(self, tree: Gff):
        field = self._player_struct(tree).fields.get("FeatList")
        return field.value if field is not None and field.type == GffType.LIST else None

    @staticmethod
    def _feat_ids(feat_list) -> set[int]:
        return {s.get("Feat") for s in feat_list.structs if s.get("Feat") is not None}

    def _ensure_feat_originals(self) -> None:
        if self._feat_originals is None:
            feats = self._feat_list(self._module_tree())
            self._feat_originals = self._feat_ids(feats) if feats is not None else set()

    def _recompute_feat_changes(self) -> None:
        """Derive pending feat add/removes from the tree vs the original feat set."""
        from vaultkeeper.game.character_reference import default_reference

        ref = default_reference()
        feats = self._feat_list(self._module_tree())
        current = self._feat_ids(feats) if feats is not None else set()
        original = self._feat_originals or set()
        for key in [k for k in self._changes if k[0] == "feat"]:
            del self._changes[key]
        for verb, ids in (("add", current - original), ("remove", original - current)):
            for fid in sorted(ids):
                note = "" if ref.is_base_feat(fid) else " (PRC — may not persist)"
                self._changes[("feat", (verb, fid))] = PendingChange(
                    kind="feat", key=(verb, fid),
                    where=ref.feat_name(fid), summary=f"{verb} feat{note}",
                )

    # -- write ------------------------------------------------------------ #
    def _dirty_areas(self) -> set[str]:
        """Area resrefs (lower) touched by at least one pending *store* change."""
        return {
            change.key[0].lower()
            for change in self._changes.values()
            if change.kind == "store"
        }

    def _overrides(self) -> dict[tuple[str, int], bytes]:
        out = {(key, _GIT_RESTYPE): write_gff(self._areas[key]) for key in self._dirty_areas()}
        if self._char_dirty and self._module is not None:
            out[("module", _IFO_RESTYPE)] = write_gff(self._module)  # authoritative character
        return out

    def _file_overrides(self) -> dict[str, bytes]:
        """Non-ERF sibling files to write instead of copy (the edited player.bic)."""
        if self._char_dirty and self._bic is not None:
            return {"player.bic": write_gff(self._bic)}  # keep the mirror in sync
        return {}

    def save_as(self, dest_folder: Path) -> SaveGame:
        """Write the edited save to a new folder and return it (verified).

        Copies the original save folder's other files (screenshots, ``savenfo.txt``
        …) verbatim, writes the edited ``.sav`` and any edited sibling (player.bic).
        """
        if not self.has_edits:
            raise SaveEditError("no edits to save")
        if dest_folder.exists():
            raise SaveEditError(f"destination already exists: {dest_folder}")
        src_sav = self._save.sav_path
        file_overrides = self._file_overrides()
        dest_folder.mkdir(parents=True)
        try:
            for item in self._save.folder.iterdir():
                if item.is_file() and item != src_sav and item.name not in file_overrides:
                    shutil.copy2(item, dest_folder / item.name)
            for name, data in file_overrides.items():
                (dest_folder / name).write_bytes(data)
            rewrite_erf(src_sav, self._overrides(), dest_folder / src_sav.name)
            new_save = SaveGame(folder=dest_folder)
            self._verify(new_save)
        except Exception:
            shutil.rmtree(dest_folder, ignore_errors=True)  # don't leave a half-save
            raise
        return new_save

    def _verify(self, new_save: SaveGame) -> None:
        """Confirm each edited resource/file in the new save matches what we wrote."""
        for (resref, res_type), expected in self._overrides().items():
            res = self._reader.find_resource(new_save.sav_path, resref, res_type=res_type)
            if res is None:
                raise SaveEditError(f"verify failed: {resref} missing from written save")
            if self._reader.read_resource_bytes(new_save.sav_path, res) != expected:
                raise SaveEditError(f"verify failed: {resref} bytes differ after write")
        for name, expected in self._file_overrides().items():
            path = new_save.folder / name
            if not path.is_file() or path.read_bytes() != expected:
                raise SaveEditError(f"verify failed: {name} differs after write")
