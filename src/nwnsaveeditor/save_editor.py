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
from pathlib import Path

from vaultkeeper.core.formats.erf_reader import ErfReader
from vaultkeeper.core.formats.erf_writer import rewrite_erf
from vaultkeeper.core.formats.gff import Gff, GffType, read_gff, write_gff
from vaultkeeper.game.save_game import SaveGame

_GIT_RESTYPE = 2023


class SaveEditError(Exception):
    """A save could not be read, edited or written."""


class SaveEditor:
    """Accumulates edits to a save's resources and writes them to a new save.

    Edits are staged in memory (the source is never modified); :meth:`save_as`
    materialises them into a new save folder and verifies the result.
    """

    #: editable store field -> (GFF label, "int" | "bool").
    STORE_FIELDS: dict[str, tuple[str, str]] = {
        "markup": ("MarkUp", "int"),
        "markdown": ("MarkDown", "int"),
        "store_gold": ("StoreGold", "int"),
        "identify_price": ("IdentifyPrice", "int"),
        "max_buy_price": ("MaxBuyPrice", "int"),
        "black_market": ("BlackMarket", "bool"),
    }

    def __init__(self, save: SaveGame) -> None:
        if save.sav_path is None:
            raise SaveEditError("save has no .sav file")
        self._save = save
        self._reader = ErfReader()
        self._areas: dict[str, Gff] = {}  # area resref (lower) -> loaded .git tree
        self._dirty: set[str] = set()

    @property
    def has_edits(self) -> bool:
        return bool(self._dirty)

    # -- store editing ---------------------------------------------------- #
    def set_store_fields(self, area_resref: str, store_index: int, **values) -> None:
        """Stage edits to a store's scalar settings (only non-``None`` values apply)."""
        store = self._store_struct(area_resref, store_index)
        changed = False
        for key, value in values.items():
            if value is None:
                continue
            if key not in self.STORE_FIELDS:
                raise SaveEditError(f"unknown store field {key!r}")
            label, kind = self.STORE_FIELDS[key]
            gfield = store.fields.get(label)
            if gfield is None:
                raise SaveEditError(f"store has no {label!r} field to edit")
            gfield.value = int(value) if kind == "int" else (1 if value else 0)
            changed = True
        if changed:
            self._dirty.add(area_resref.lower())

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
    def _overrides(self) -> dict[tuple[str, int], bytes]:
        return {(key, _GIT_RESTYPE): write_gff(self._areas[key]) for key in self._dirty}

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
