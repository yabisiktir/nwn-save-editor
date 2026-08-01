"""Read ``appearance.2da`` / ``portraits.2da`` for cosmetic character-look editing.

Provides the valid options for a character's ``Appearance_Type`` (the creature
model) and ``Portrait`` (the portrait base resref), so the editor can offer a
picker of real values. Reads the PRC/CEP hak in preference to the base game where
present (both tables are commonly extended by custom content).
"""

from __future__ import annotations

from pathlib import Path

from nwnfile.formats.erf_reader import ErfReader
from nwnfile.formats.key_bif_reader import KeyBifReader
from nwnfile.item_property_tables import parse_2da

_2DA_RESTYPE = 2017
#: haks (in the user hak folder) that commonly override appearance/portraits.
_LOOK_HAKS = ("prc8_2das.hak", "cep2_add_cc.hak", "cep2_core5.hak")


class LookTables:
    """Appearance + portrait option lists from the install (base + haks)."""

    def __init__(self, game_root: Path | None, hak_paths: list[Path] | None = None) -> None:
        self._kb = KeyBifReader.for_install(game_root)
        self._haks = [p for p in (hak_paths or []) if p.is_file()]
        self._erf = ErfReader()
        self._cache: dict[str, dict[int, dict[str, str]] | None] = {}
        self._appearance: dict[int, str] | None = None
        self._portraits: list[str] | None = None

    @classmethod
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
