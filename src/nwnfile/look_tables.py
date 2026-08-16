"""Read ``appearance.2da`` / ``portraits.2da`` for cosmetic character-look editing.

Provides the valid options for a character's ``Appearance_Type`` (the creature
model) and ``Portrait`` (the portrait base resref), so the editor can offer a
picker of real values. Reads the PRC/CEP hak in preference to the base game where
present (both tables are commonly extended by custom content).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nwnfile.cache import by_install
from nwnfile.formats.erf_reader import ErfReader
from nwnfile.formats.key_bif_reader import KeyBifReader
from nwnfile.item_property_tables import PRC_2DAS_HAK_NAMES, parse_2da

_2DA_RESTYPE = 2017
#: haks (in the user hak folder) that commonly override appearance/portraits.
#: PRC's 2DAs hak is named per-version (see :data:`PRC_2DAS_HAK_NAMES`); missing
#: ones are dropped, so listing every known name just widens what is found.
_LOOK_HAKS = (*PRC_2DAS_HAK_NAMES, "cep2_add_cc.hak", "cep2_core5.hak")

#: ``portraits.2da`` Sex codes. 4 is the catch-all the table gives creatures
#: and placeables — 1,318 of the base game's 1,594 rows.
SEX_MALE, SEX_FEMALE = 0, 1


@dataclass(frozen=True)
class PortraitEntry:
    """One portrait: its base resref and who ``portraits.2da`` says it is for."""

    resref: str
    sex: int | None = None
    race: int | None = None

    @property
    def humanoid(self) -> bool:
        """Whether this is a portrait for a person rather than a beast or a barrel."""
        return self.sex in (SEX_MALE, SEX_FEMALE)


def _as_int(raw) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class LookTables:
    """Appearance + portrait option lists from the install (base + haks)."""

    def __init__(self, game_root: Path | None, hak_paths: list[Path] | None = None) -> None:
        self._kb = KeyBifReader.for_install(game_root)
        self._haks = [p for p in (hak_paths or []) if p.is_file()]
        self._erf = ErfReader()
        self._cache: dict[str, dict[int, dict[str, str]] | None] = {}
        self._appearance: dict[int, str] | None = None
        self._portraits: list[str] | None = None
        self._portrait_entries: list[PortraitEntry] | None = None

    @classmethod
    @by_install
    def for_install(cls, game_root: Path | None, hak_dir: Path | None = None) -> LookTables:
        haks = [hak_dir / name for name in _LOOK_HAKS] if hak_dir is not None else []
        return cls(game_root, haks)

    @property
    def available(self) -> bool:
        return bool(self.appearance_options()) or bool(self.portrait_resrefs())

    def appearance_options(self) -> dict[int, str]:
        """``{Appearance_Type id -> label}`` for models with a name."""
        if self._appearance is None:
            table = self._read("appearance")
            self._appearance = {
                index: row.get("LABEL", "").replace("_", " ")
                for index, row in (table or {}).items()
                if row.get("LABEL", "****") not in ("", "****")
            }
        return self._appearance

    def appearance_name(self, appearance_id: int) -> str:
        return self.appearance_options().get(appearance_id, f"#{appearance_id}")

    def portrait_entries(self) -> list[PortraitEntry]:
        """Every portrait with the two things worth narrowing 1,594 of them by.

        ``portraits.2da`` carries a ``Sex`` and a ``Race`` per row, and they matter
        more than they look: of the base game's 1,594 portraits only **275** are
        humanoid at all (``Sex`` 0 or 1) — the other 1,318 are creatures and
        placeables, which nobody is picking for a player character. Offering the
        raw list makes the useful ones a needle in the rest.
        """
        if self._portrait_entries is None:
            table = self._read("portraits")
            seen: set[str] = set()
            out: list[PortraitEntry] = []
            for row in (table or {}).values():
                ref = row.get("BaseResRef", "****")
                if ref in ("", "****") or ref.lower() in seen:
                    continue
                seen.add(ref.lower())
                out.append(PortraitEntry(
                    resref=ref, sex=_as_int(row.get("Sex")), race=_as_int(row.get("Race"))
                ))
            self._portrait_entries = out
        return self._portrait_entries

    def portrait_resrefs(self) -> list[str]:
        """Distinct portrait ``BaseResRef`` values (a valid portrait list)."""
        if self._portraits is None:
            table = self._read("portraits")
            seen: set[str] = set()
            out: list[str] = []
            for row in (table or {}).values():
                ref = row.get("BaseResRef", "****")
                if ref not in ("", "****") and ref.lower() not in seen:
                    seen.add(ref.lower())
                    out.append(ref)
            self._portraits = out
        return self._portraits

    def _read(self, name: str) -> dict[int, dict[str, str]] | None:
        if name not in self._cache:
            text: str | None = None
            for hak in self._haks:
                res = self._erf.find_resource(hak, name, res_type=_2DA_RESTYPE)
                if res is not None:
                    text = self._erf.read_resource_bytes(hak, res).decode("latin-1")
                    break
            if text is None and self._kb is not None:
                text = self._kb.read_2da_text(name)
            self._cache[name] = parse_2da(text)[1] if text else None
        return self._cache[name]
