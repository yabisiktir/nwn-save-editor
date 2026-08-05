"""Resolve an item's inventory icon (a TGA) from the installed game data.

An item's picture is derived from its ``BaseItem`` (baseitems.2da row) and the
variant fields it carries. Most items name their icon ``i<ItemClass>_<ModelPart1>``.
Two kinds do not, and both used to fall through to the base item's ``DefaultIcon``
— a single per-*type* picture, which is why every suit of armour looked alike:

* **Armour** (``ModelType`` 3) has no ``ModelPart1`` at all. It is a set of body-part
  models, and the inventory picture is the torso as worn: ``ipm_chest029`` for a man,
  ``ipf_chest029`` for a woman, or ``ip?_robe0NN`` when the suit wears a robe.
* **Cloaks** number their variants inside ``DefaultIcon`` (``icloak_m_001``) rather
  than after the item class, so the number there is what has to be swapped.

The resources are TGA or PLT in the base game's BIF archives, read with
:class:`KeyBifReader` (so this needs the install; it degrades to "no icon" without
it).

Custom content (CEP/PRC) ships its own item-icon variants inside haks — also TGA.
When a ``hak_dir`` is given (opt-in, it is slower), those haks are indexed once and
searched as a fallback, so e.g. a ring's exact ``iit_ring_100`` from ``cep2_core5``
is used instead of the generic base ``iit_ring``.

Returns raw TGA bytes — the Qt conversion to a pixmap lives in the UI.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from nwnfile.cache import by_install
from nwnfile.formats.erf_reader import ErfReader, ErfResource
from nwnfile.formats.key_bif_reader import KeyBifReader

_TGA_RES_TYPE = 3
_MAX_RESREF = 16


class ItemIconSource:
    """Looks up item inventory icons (TGA bytes) from the install, cached."""

    def __init__(self, game_root: Path | None, hak_dir: Path | None = None) -> None:
        self._reader = KeyBifReader.for_install(game_root)
        #: base item id -> (ItemClass, DefaultIcon, ModelType)
        self._base_items: dict[int, tuple[str, str, int]] = {}
        self._cache: dict[tuple[int, int], bytes | None] = {}
        self._image_cache: dict[tuple[int, int], object] = {}
        self._palette_cache: dict[str, object] | None = None
        #: opt-in hak icon search: resref -> (hak path, resource), built lazily.
        self._hak_dir = hak_dir if hak_dir is not None and hak_dir.is_dir() else None
        self._hak_index: dict[str, tuple[Path, ErfResource]] | None = None
        self._erf = ErfReader()
        if self._reader is not None:
            self._load_base_items()

    @property
    def available(self) -> bool:
        return bool(self._base_items)

    def _load_base_items(self) -> None:
        text = self._reader.read_2da_text("baseitems") if self._reader else None
        if text is None:
            return
        lines = text.splitlines()
        start = next(n for n, line in enumerate(lines) if line.strip().startswith("2DA")) + 1
        while start < len(lines) and not lines[start].strip():
            start += 1
        header = lines[start].split()
        for line in lines[start + 1:]:
            if not line.strip():
                continue
            try:
                parts = shlex.split(line)
            except ValueError:
                parts = line.split()
            if not parts or not parts[0].isdigit():
                continue
            # parts[0] is the row index; the rest align with the header columns.
            row = dict(zip(header, parts[1:], strict=False))

            def cell(name: str, cols=row) -> str:
                value = cols.get(name, "****")
                return "" if value == "****" else value

            model_type = cell("ModelType")
            self._base_items[int(parts[0])] = (
                cell("ItemClass"), cell("DefaultIcon"),
                int(model_type) if model_type.isdigit() else -1,
            )

    #: Tintable parts (cloaks, robes) ship a PLT rather than a TGA: it stores no
    #: colour, only a palette index per pixel. See nwnfile.formats.plt_reader.
    PLT_RES_TYPE = 6

    #: ``ModelType`` 3 in baseitems.2da — armour, which is not one model but a set
    #: of body parts. Its inventory picture is the *torso* part, drawn on the
    #: wearer's body: ``ipm_chest029`` / ``ipf_chest029``. Nothing about that is
    #: reachable from ``ItemClass`` (``AArCl``) or ``DefaultIcon`` (``iit_chest``,
    #: one generic breastplate for every suit in the game).
    _ARMOUR_MODEL_TYPE = 3

    #: ``ModelType`` 0 (simple) and 1 (layered) are one model with one variant
    #: number, so ``i<ItemClass>_<ModelPart1>`` names their icon. Composite weapons
    #: (2) are not: theirs is assembled from three pieces and named for all of them
    #: (``iwswss_b_011``), which nothing here attempts — they keep the generic
    #: per-type picture they have always had.
    _SINGLE_PART_TYPES = (0, 1)

    #: A trailing variant number on a ``DefaultIcon``, e.g. ``icloak_m_001``.
    _TRAILING_NUMBER = re.compile(r"(\d+)$")

    def _candidates(
        self,
        base_item: int,
        model_part: int,
        *,
        armor_torso: int = 0,
        armor_robe: int = 0,
        female: bool = False,
    ) -> list[str]:
        """Icon resrefs to try for an item, best guess first.

        Every one of these is a per-variant picture; ``DefaultIcon`` comes last and
        is a per-*type* one. Falling back to it is why every suit of armour showed
        the same breastplate and every cloak the same red cloak.
        """
        row = self._base_items.get(base_item)
        if row is None:
            return []
        item_class, default_icon, model_type = row
        candidates: list[str] = []

        if model_type == self._ARMOUR_MODEL_TYPE:
            # Both genders, ours first: the picture is the armour as worn, and a
            # suit whose own gender's part is missing still has the other's.
            part = ("robe", armor_robe) if armor_robe else ("chest", armor_torso)
            for prefix in (("ipf", "ipm") if female else ("ipm", "ipf")):
                candidates.append(f"{prefix}_{part[0]}{part[1]:03d}")
        elif model_type in self._SINGLE_PART_TYPES and item_class:
            # Simple (0) and layered (1) alike: i<ItemClass>_<variant>. Helms are
            # layered, and were falling through to the generic ``ihelm`` for it.
            candidates.append(f"i{item_class}_{model_part:03d}")

        # Cloaks are numbered inside their DefaultIcon (``icloak_m_001``) rather
        # than after the item class, so swapping that number is what finds them —
        # and it costs nothing for the base items whose icon carries no number.
        if default_icon and model_type != self._ARMOUR_MODEL_TYPE:
            swapped = self._TRAILING_NUMBER.sub(f"{model_part:03d}", default_icon)
            if swapped != default_icon:
                candidates.append(swapped)

        if default_icon:
            candidates.append(default_icon)
        return [c[:_MAX_RESREF] for c in dict.fromkeys(candidates)]

    def _build_hak_index(self) -> None:
        """Index every ``i*`` TGA icon across the hak folder (once, ~0.5s)."""
        index: dict[str, tuple[Path, ErfResource]] = {}
        if self._hak_dir is not None:
            for hak in sorted(self._hak_dir.glob("*.hak")):
                try:
                    info = self._erf.read_info(hak)
                    if info is None or not info.is_valid:
                        continue
                    for res in self._erf.list_resources(hak):
                        if res.res_type == _TGA_RES_TYPE and res.resref.startswith("i"):
                            index.setdefault(res.resref.lower(), (hak, res))
                except Exception:  # noqa: BLE001 — a bad hak just contributes no icons
                    continue
        self._hak_index = index

    def _hak_bytes(self, resref: str) -> bytes | None:
        if self._hak_dir is None:
            return None
        if self._hak_index is None:
            self._build_hak_index()
        entry = self._hak_index.get(resref.lower()) if self._hak_index else None
        if entry is None:
            return None
        hak, res = entry
        try:
            return self._erf.read_resource_bytes(hak, res)
        except Exception:  # noqa: BLE001
            return None

    def icon_image(self, base_item: int, model_part: int, **variant):
        """An item's icon as a decoded ``TGAImage``, or ``None``.

        ``variant`` carries what distinguishes one suit of armour from another —
        see :meth:`_candidates`.

        **Each candidate is tried in both formats before moving on to the next.**
        The game stores some icons as TGA and some as PLT, and which one a picture
        uses says nothing about how good a match it is: the *right* icon for a suit
        of armour (``ipm_chest028``) is a PLT while the generic fallback
        (``iit_chest``) is a TGA. Asking for every TGA first therefore handed back
        the fallback every time, and the correct icon was never reached — which
        looked exactly like the resrefs being wrong.
        """
        key = self._key(base_item, model_part, variant)
        if key not in self._image_cache:
            self._image_cache[key] = self._first_image(
                self._candidates(base_item, model_part, **variant)
            )
        return self._image_cache[key]

    @staticmethod
    def _key(base_item: int, model_part: int, variant: dict) -> tuple:
        """A cache key. The variant has to be in it, or every suit of armour after
        the first would be served the first one's picture."""
        return (base_item, model_part, tuple(sorted(variant.items())))

    def _first_image(self, candidates: list[str]):
        """The first candidate that resolves, as either a TGA or a PLT."""
        from nwnfile.formats.tga_reader import TGAReader

        for resref in candidates:
            data = self._resource(resref, _TGA_RES_TYPE)
            image = TGAReader().read_bytes(data) if data is not None else None
            if image is not None:
                return image
            image = self._plt_image(resref)
            if image is not None:
                return image
        return None

    def _plt_image(self, resref: str):
        """Decode and colour one PLT icon, if that resref is a PLT."""
        from nwnfile.formats.plt_reader import (
            LAYER_PALETTES,
            colour_plt,
            read_plt,
        )

        raw = self._resource(resref, self.PLT_RES_TYPE)
        plt = read_plt(raw) if raw else None
        if plt is None:
            return None
        return colour_plt(plt, self._palettes(LAYER_PALETTES))

    def _resource(self, resref: str, res_type: int) -> bytes | None:
        """One resource from the base game, falling back to the haks."""
        data = self._reader.read(resref, res_type) if self._reader is not None else None
        if data is None and res_type == _TGA_RES_TYPE:
            data = self._hak_bytes(resref)
        return data

    def _palettes(self, names) -> dict:
        """The palette textures a PLT needs, decoded once."""
        from nwnfile.formats.tga_reader import TGAReader

        if self._palette_cache is None:
            self._palette_cache = {}
            for name in set(names):
                raw = self._reader.read(name, _TGA_RES_TYPE) if self._reader else None
                self._palette_cache[name] = TGAReader().read_bytes(raw) if raw else None
        return self._palette_cache

    def icon_bytes(self, base_item: int, model_part: int, **variant) -> bytes | None:
        """Raw TGA bytes for an item's icon (cached), or ``None`` if not found.

        Each candidate resref is tried in the base game first, then (if a hak
        folder was supplied) in the haks — so a custom per-variant icon beats the
        generic base fallback.
        """
        key = self._key(base_item, model_part, variant)
        if key not in self._cache:
            data = None
            for resref in self._candidates(base_item, model_part, **variant):
                data = self._resource(resref, _TGA_RES_TYPE)
                if data is not None:
                    break
            self._cache[key] = data
        return self._cache[key]


@by_install
def icon_source_for(game_root, hak_dir=None) -> ItemIconSource:
    """An :class:`ItemIconSource` for an install, shared between callers.

    Keyed on the install for the same reason the tables are: it indexes the
    game's KEY/BIF (and optionally every hak), which is far too slow to redo per
    window, and holding it anywhere else means something has to remember to
    throw it away when the folders change.
    """
    return ItemIconSource(game_root, hak_dir=hak_dir)
