"""Resolve game resources the way the engine does: the module's haks, then base.

A saved game records the haks its module was built with, in priority order, in
``module.ifo``'s ``Mod_HakList`` — and different saves list different haks. That
list is the only correct way to read a table for *this* save: guessing a hak by
name gets the wrong answer for anyone whose install differs, and reading the base
game alone gets the wrong answer for anyone running custom content at all.

The practical consequence is large. PRC's ``racialtypes.2da`` — 255 rows against
the base game's 30 — lives in ``prc8_race.hak``, while ``prc8_2das.hak`` has no
copy. Reading only the latter reports that a PRC race does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nwnfile.formats.erf_reader import ErfReader
from nwnfile.formats.key_bif_reader import KeyBifReader
from nwnfile.item_property_tables import parse_2da
from nwnfile.log import get_logger

logger = get_logger(__name__)

_2DA_RESTYPE = 2017
_NSS_RESTYPE = 2009


@dataclass(frozen=True)
class HakStack:
    """The hak search path for one module, plus the base game underneath it.

    Earlier entries win, matching the toolset's custom-content list where the
    topmost hak overrides those below it.
    """

    haks: tuple[Path, ...] = ()
    game_root: Path | None = None

    @classmethod
    def for_module(
        cls, hak_names, hak_dir: Path | None, game_root: Path | None = None
    ) -> HakStack:
        """Build the stack from ``Mod_HakList`` names, keeping the recorded order.

        Names that are not installed are dropped rather than raising: a save may
        list a hak the player has since removed, and the tables that *are*
        present still give better answers than the base game alone.
        """
        found: list[Path] = []
        for name in hak_names or ():
            if hak_dir is None:
                break
            path = hak_dir / f"{str(name).strip()}.hak"
            if path.is_file():
                found.append(path)
            else:
                logger.debug("save lists hak %r, which is not installed", name)
        return cls(tuple(found), game_root)

    def read_2da(self, name: str) -> dict[int, dict[str, str]] | None:
        """``{row index: {column: value}}`` for the winning copy of a 2DA."""
        text = self.read_text(name, _2DA_RESTYPE)
        return parse_2da(text)[1] if text else None

    def read_base_2da(self, name: str) -> dict[int, dict[str, str]] | None:
        """The base game's copy of a 2DA (from KEY/BIF), ignoring the haks.

        The only way to tell base content from custom when a hak ships a full
        replacement: PRC's ``feat.2da`` shadows the base one, so reading the stack
        cannot say which feats are base and which PRC added.
        """
        reader = KeyBifReader.for_install(self.game_root)
        if reader is None:
            return None
        text = reader.read_2da_text(name)
        return parse_2da(text)[1] if text else None

    def read_script(self, name: str) -> str | None:
        """An ``.nss`` source file. PRC ships 5,415 of them, so its rules are readable."""
        return self.read_text(name, _NSS_RESTYPE, base=False)

    def read_text(self, name: str, res_type: int, *, base: bool = True) -> str | None:
        for hak in self.haks:
            try:
                res = ErfReader().find_resource(hak, name, res_type=res_type)
            except Exception:  # a corrupt or unreadable hak must not stop the search
                logger.debug("could not search %s", hak.name, exc_info=True)
                continue
            if res is not None:
                return ErfReader().read_resource_bytes(hak, res).decode("latin-1")
        if base and res_type == _2DA_RESTYPE:
            reader = KeyBifReader.for_install(self.game_root)
            if reader is not None:
                return reader.read_2da_text(name)
        return None


def hak_names_from_module(module) -> tuple[str, ...]:
    """``Mod_HakList`` entries from a decoded ``module.ifo``, in priority order."""
    field = module.fields.get("Mod_HakList") if hasattr(module, "fields") else None
    if field is None or not hasattr(field.value, "structs"):
        return ()
    names = []
    for struct in field.value.structs:
        value = struct.get("Mod_Hak")
        if value:
            names.append(str(value))
    return tuple(names)
