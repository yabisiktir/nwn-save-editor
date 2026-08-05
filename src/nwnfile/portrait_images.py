"""Find a portrait's picture, wherever the install happens to keep it.

Three places, in this order, because they answer different questions:

* **Loose files** in ``portraits/`` and ``override/`` — where a custom portrait
  someone downloaded lives, and where the owner's own ``adreannamale78_`` is.
  Named ``<resref><size>.tga``.
* **The base game's KEY/BIF** — where all 1,594 stock portraits live. Named
  ``po_<resref><size>``, *with* a ``po_`` prefix the loose-file convention does
  not use. That difference is the whole reason the stock portraits looked
  unavailable: searching only the folders finds none of them.
* **Haks** — custom content's own, same ``po_`` naming.

Returns raw TGA bytes; turning those into a pixmap is the UI's business.
"""

from __future__ import annotations

from pathlib import Path

from nwnfile.cache import by_install
from nwnfile.formats.erf_reader import ErfReader
from nwnfile.formats.key_bif_reader import KeyBifReader

_TGA_RES_TYPE = 3

#: Portrait sizes, smallest first. ``m`` is 64x128 — the one worth showing in a
#: grid; ``t`` is 16x32 and far too small to recognise a face in.
SIZES = ("t", "s", "m", "l", "h")
GRID_SIZE = "m"

#: A portrait's art is 25 units tall for every 16 wide; the file is padded taller.
#:
#: Every portrait ships on a power-of-two canvas — the 64x100 picture sits in a
#: 64x128 TGA, and the ~28 rows underneath are one flat colour. The game crops
#: them; anything that does not gets a coloured shelf under every face. Measured
#: as exactly 27-28 uniform bottom rows on every stock portrait and on the owner's
#: own custom one.
ART_RATIO = 25 / 16


def art_height(width: int, height: int) -> int:
    """How much of a portrait of this size is picture rather than padding."""
    art = round(width * ART_RATIO)
    return art if 0 < art < height else height


class PortraitSource:
    """Reads portrait TGAs from the install, cached per resref+size."""

    def __init__(
        self,
        game_root: Path | None,
        portrait_dirs: list[Path] | None = None,
        hak_dir: Path | None = None,
    ) -> None:
        self._reader = KeyBifReader.for_install(game_root)
        self._dirs = [Path(d) for d in (portrait_dirs or []) if Path(d).is_dir()]
        self._hak_dir = hak_dir if hak_dir is not None and hak_dir.is_dir() else None
        self._hak_index: dict[str, tuple[Path, object]] | None = None
        self._erf = ErfReader()
        self._cache: dict[tuple[str, str], bytes | None] = {}

    @property
    def available(self) -> bool:
        return self._reader is not None or bool(self._dirs)

    def image_bytes(self, resref: str, size: str = GRID_SIZE) -> bytes | None:
        """The portrait's TGA bytes, or ``None`` when nothing has it."""
        if not resref:
            return None
        key = (resref.lower(), size)
        if key not in self._cache:
            self._cache[key] = self._find(resref, size)
        return self._cache[key]

    def _find(self, resref: str, size: str) -> bytes | None:
        # Try the asked-for size everywhere before falling back to another size,
        # so a portrait is never silently shown at a wildly different resolution
        # while the right one sits in the next folder along.
        for candidate in (size, *[s for s in SIZES if s != size]):
            data = self._at_size(resref, candidate)
            if data is not None:
                return data
        return None

    def _at_size(self, resref: str, size: str) -> bytes | None:
        loose = f"{resref}{size}.tga"
        for folder in self._dirs:
            path = folder / loose
            if path.is_file():
                try:
                    return path.read_bytes()
                except OSError:
                    continue
        packed = f"po_{resref}{size}"[:16]
        if self._reader is not None:
            data = self._reader.read(packed, _TGA_RES_TYPE)
            if data is not None:
                return data
        return self._from_haks(packed)

    def _from_haks(self, resref: str) -> bytes | None:
        if self._hak_dir is None:
            return None
        if self._hak_index is None:
            self._build_hak_index()
        entry = (self._hak_index or {}).get(resref.lower())
        if entry is None:
            return None
        hak, res = entry
        try:
            return self._erf.read_resource_bytes(hak, res)
        except Exception:  # noqa: BLE001 — a bad hak just contributes no portrait
            return None

    def _build_hak_index(self) -> None:
        index: dict[str, tuple[Path, object]] = {}
        for hak in sorted((self._hak_dir or Path()).glob("*.hak")):
            try:
                info = self._erf.read_info(hak)
                if info is None or not info.is_valid:
                    continue
                for res in self._erf.list_resources(hak):
                    if res.res_type == _TGA_RES_TYPE and res.resref.startswith("po_"):
                        index.setdefault(res.resref.lower(), (hak, res))
            except Exception:  # noqa: BLE001
                continue
        self._hak_index = index


@by_install
def portrait_source_for(
    game_root, portrait_dirs=None, hak_dir=None
) -> PortraitSource:
    """A :class:`PortraitSource` for an install, shared between callers."""
    return PortraitSource(game_root, list(portrait_dirs or []), hak_dir)
