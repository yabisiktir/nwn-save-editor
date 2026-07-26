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

from vaultkeeper.core.formats.erf_reader import ErfReader
from vaultkeeper.core.formats.erf_writer import rewrite_erf
from vaultkeeper.core.formats.gff import Gff, GffType, read_gff, write_gff
from vaultkeeper.game.save_game import SaveGame

_GIT_RESTYPE = 2023


class SaveEditError(Exception):
    """A save could not be read, edited or written."""


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

    # -- write ------------------------------------------------------------ #
    def _dirty_areas(self) -> set[str]:
        """Area resrefs (lower) touched by at least one pending change."""
        return {change.key[0].lower() for change in self._changes.values()}

    def _overrides(self) -> dict[tuple[str, int], bytes]:
        return {(key, _GIT_RESTYPE): write_gff(self._areas[key]) for key in self._dirty_areas()}

    def save_as(self, dest_folder: Path) -> SaveGame:
        """Write the edited save to a new folder and return it (verified).

        Copies the original save folder's other files (``player.bic``,
        screenshots, ``savenfo.txt`` …) verbatim and writes the edited ``.sav``.
        """
        if not self.has_edits:
            raise SaveEditError("no edits to save")
        if dest_folder.exists():
            raise SaveEditError(f"destination already exists: {dest_folder}")
        src_sav = self._save.sav_path
        dest_folder.mkdir(parents=True)
        try:
            for item in self._save.folder.iterdir():
                if item.is_file() and item != src_sav:
                    shutil.copy2(item, dest_folder / item.name)
            dest_sav = dest_folder / src_sav.name
            rewrite_erf(src_sav, self._overrides(), dest_sav)
            new_save = SaveGame(folder=dest_folder)
            self._verify(new_save)
        except Exception:
            shutil.rmtree(dest_folder, ignore_errors=True)  # don't leave a half-save
            raise
        return new_save

    def _verify(self, new_save: SaveGame) -> None:
        """Confirm each edited resource in the new save matches what we wrote."""
        overrides = self._overrides()
        for (resref, res_type), expected in overrides.items():
            res = self._reader.find_resource(new_save.sav_path, resref, res_type=res_type)
            if res is None:
                raise SaveEditError(f"verify failed: {resref} missing from written save")
            if self._reader.read_resource_bytes(new_save.sav_path, res) != expected:
                raise SaveEditError(f"verify failed: {resref} bytes differ after write")
