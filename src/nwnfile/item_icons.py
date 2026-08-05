"""Resolve an item's inventory icon (a TGA) from the installed game data.

An item's picture comes from its ``BaseItem`` (a baseitems.2da row) and the variant
fields it carries, and **the naming depends on the row's ``ModelType``** — there is
no one rule. Each kind that has its own rule used to fall through to the base item's
``DefaultIcon``, which is a single per-*type* picture: that is why every suit of
armour looked alike, and every potion, and every pair of boots.

* **Simple (0) and layered (1)** — rings, potions' cousins, helms:
  ``i<ItemClass>_<ModelPart1:03d>``, e.g. ``ihelm_013``.
* **Composite (2)** — not only weapons: potions, boots, rods, staves and keys. The
  item carries *three* part numbers and the picture is the three drawn over one
  another: ``iit_potion_b_012`` + ``iit_potion_m_011`` + ``iit_potion_t_021``.
* **Armour (3)** has no ``ModelPart1`` at all. It is a set of body-part models, and
  the picture is the torso as worn — so it is gendered: ``ipm_chest029`` for a man,
  ``ipf_chest029`` for a woman, ``ip?_robeNNN`` when the suit wears a robe.
* **Cloaks** number their variants inside ``DefaultIcon`` (``icloak_m_001``) rather
  than after the item class, so the number there is what has to be swapped.

The resources are TGA **or PLT** in the base game's BIF archives, read with
:class:`KeyBifReader` (so this needs the install; it degrades to "no icon" without
it). Which format an icon uses says nothing about how good a match it is — the right
icon for a suit of armour is a PLT while the generic fallback is a TGA — so **every
candidate is tried in both formats before the next candidate is considered**.

Custom content (CEP/PRC) ships its own icons inside haks, in either format. When a
``hak_dir`` is given (opt-in, it is slower), those haks are indexed once and searched
as a fallback, which is the only place a custom item's picture exists: the Robes of
Sesustris are ``ipm_robe171``, a PLT in ``cep2_core3.hak``.

``exact=False`` turns all of that off and gives every item of a type that type's one
``DefaultIcon`` — uniform pictures, nothing worked out.

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

    def __init__(
        self,
        game_root: Path | None,
        hak_dir: Path | None = None,
        *,
        exact: bool = True,
    ) -> None:
        self._reader = KeyBifReader.for_install(game_root)
        #: With this off, no per-variant icon is looked for at all and every item
        #: of a type shows that type's ``DefaultIcon``. Cheap and uniform — the
        #: state this module was in before it learned the naming rules.
        self._exact = exact
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
    #: number, so ``i<ItemClass>_<ModelPart1>`` names their icon.
    _SINGLE_PART_TYPES = (0, 1)

    #: ``ModelType`` 2 — composite. Not just weapons: potions, boots, rods, staves
    #: and keys are all built this way. The item carries three part numbers and the
    #: picture is the three drawn over one another, bottom first:
    #: ``iit_potion_b_012`` + ``iit_potion_m_011`` + ``iit_potion_t_021``.
    _COMPOSITE_MODEL_TYPE = 2
    _COMPOSITE_LAYERS = ("b", "m", "t")

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
        **_composite_parts,  # consumed by _composite_image, not by naming
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
        if not self._exact:
            return [default_icon[:_MAX_RESREF]] if default_icon else []
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
        """Index every ``i*`` icon across the hak folder (once, ~0.5s).

        **Both formats.** Custom content ships plenty of icons as PLT — CEP's
        ``ipm_robe171``, the picture for the Robes of Sesustris, is one — and an
        index of TGAs only cannot see them however well the resref is worked out.
        Keyed by ``(resref, type)`` because the same name can exist as either.
        """
        index: dict[tuple[str, int], tuple[Path, ErfResource]] = {}
        wanted = (_TGA_RES_TYPE, self.PLT_RES_TYPE)
        if self._hak_dir is not None:
            for hak in sorted(self._hak_dir.glob("*.hak")):
                try:
                    info = self._erf.read_info(hak)
                    if info is None or not info.is_valid:
                        continue
                    for res in self._erf.list_resources(hak):
                        if res.res_type in wanted and res.resref.startswith("i"):
                            index.setdefault((res.resref.lower(), res.res_type), (hak, res))
                except Exception:  # noqa: BLE001 — a bad hak just contributes no icons
                    continue
        self._hak_index = index

    def _hak_bytes(self, resref: str, res_type: int = _TGA_RES_TYPE) -> bytes | None:
        if self._hak_dir is None:
            return None
        if self._hak_index is None:
            self._build_hak_index()
        entry = self._hak_index.get((resref.lower(), res_type)) if self._hak_index else None
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
            image = self._composite_image(base_item, model_part, variant)
            if image is None:
                image = self._first_image(
                    self._candidates(base_item, model_part, **variant)
                )
            self._image_cache[key] = image
        return self._image_cache[key]

    def _composite_image(self, base_item: int, model_part: int, variant: dict):
        """A composite item's picture: its three parts drawn over one another.

        ``None`` for anything that is not composite, and for a composite item whose
        parts cannot all be found — the caller then falls back to the generic
        per-type icon, which is the honest answer when the pieces are missing.
        """
        row = self._base_items.get(base_item)
        if not self._exact or row is None:
            return None
        if row[2] != self._COMPOSITE_MODEL_TYPE or not row[0]:
            return None
        item_class = row[0]
        parts = (
            model_part,
            variant.get("model_part2", 0),
            variant.get("model_part3", 0),
        )
        layers = []
        for letter, number in zip(self._COMPOSITE_LAYERS, parts, strict=True):
            if not number:
                continue
            image = self._first_image([f"i{item_class}_{letter}_{number:03d}"[:_MAX_RESREF]])
            if image is not None:
                layers.append(image)
        return _stack(layers)

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
        """One resource from the base game, falling back to the haks.

        The fallback covers PLT as well as TGA: a custom robe's icon is a PLT and
        exists nowhere else, so restricting this to TGA left it unreachable.
        """
        data = self._reader.read(resref, res_type) if self._reader is not None else None
        if data is None:
            data = self._hak_bytes(resref, res_type)
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


def _stack(layers: list):
    """Draw a composite item's parts over one another, bottom first.

    Straight source-over alpha compositing. The parts are separate images of the
    same size — a potion's glass, its liquid and its stopper — and the game draws
    all three; showing only one is why a shelf of different potions all looked the
    same. Returns ``None`` for no layers, and the layer itself for exactly one, so
    nothing is copied needlessly.
    """
    from nwnfile.formats.tga_reader import TGAImage

    layers = [layer for layer in layers if layer is not None and layer.width > 0]
    if not layers:
        return None
    if len(layers) == 1:
        return layers[0]

    base = bytearray(layers[0].to_rgba())
    width, height = layers[0].width, layers[0].height
    for layer in layers[1:]:
        if layer.width != width or layer.height != height:
            continue  # a part of another size cannot be lined up; skip it
        over = layer.to_rgba()
        for i in range(0, len(base), 4):
            alpha = over[i + 3]
            if alpha == 0:
                continue
            if alpha == 255:
                base[i:i + 4] = over[i:i + 4]
                continue
            inv = 255 - alpha
            for channel in range(3):
                base[i + channel] = (
                    over[i + channel] * alpha + base[i + channel] * inv
                ) // 255
            base[i + 3] = alpha + base[i + 3] * inv // 255
    return TGAImage(width, height, bytes(base), True)


@by_install
def icon_source_for(game_root, hak_dir=None, exact=True) -> ItemIconSource:
    """An :class:`ItemIconSource` for an install, shared between callers.

    Keyed on the install for the same reason the tables are: it indexes the
    game's KEY/BIF (and optionally every hak), which is far too slow to redo per
    window, and holding it anywhere else means something has to remember to
    throw it away when the folders change.
    """
    return ItemIconSource(game_root, hak_dir=hak_dir, exact=exact)
