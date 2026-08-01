"""Read the contents of an NWN save game.

A save folder (``saves/<NNNNNN - name>/``) holds ``player.bic``, screenshots,
``savenfo.txt`` (the in-module location) and a ``.sav`` file. The ``.sav`` is an
ERF archive containing ``module.ifo`` (module state as GFF) plus the area files
(``.are`` static + ``.git`` instance). This decodes the useful bits — module name,
in-game date/time, XP scale and the area list — using the existing ERF + GFF
readers (like Leto's advanced view, read-only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from nwnfile.formats.bic_reader import _GFF, _GFFType
from nwnfile.formats.erf_reader import ErfReader

_IFO_RESTYPE = 2014  # module.ifo
_ARE_RESTYPE = 2012  # <area>.are (static area data — small; holds the Name)
_SCREENSHOTS = ("screen.tga", "portrait.tga")


#: The file inside a save folder naming where in the module the party is.
SAVE_INFO_FILE = "savenfo.txt"
#: Reported when that file is missing or unreadable.
GAME_LOCATION_FAILED = "Location in game unavailable"


def _read_text_lenient(path: Path) -> str:
    """Read a small text file, tolerating either UTF-8 or Latin-1 (savenfo etc.)."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def get_location_in_game_save(save_folder: Path) -> tuple[str, str | None]:
    """Read the in-module location from ``savenfo.txt``.

    Returns ``(location, error)`` where ``error`` is ``None`` on success. Leading
    dots and whitespace are stripped, matching ``Defs.GetLocationInGameSave``.
    """
    save_info = save_folder / SAVE_INFO_FILE
    if not save_info.is_file():
        return GAME_LOCATION_FAILED, f"{SAVE_INFO_FILE} does not exist"
    try:
        text = _read_text_lenient(save_info)
        return text.lstrip(".").lstrip(), None
    except OSError as ex:
        return GAME_LOCATION_FAILED, str(ex)


@dataclass
class ModuleSaveInfo:
    """The module state decoded from a save's ``module.ifo``."""

    name: str = ""
    description: str = ""
    tag: str = ""
    entry_area: str = ""
    min_game_version: str = ""
    xp_scale: int = 0
    year: int = 0
    month: int = 0
    day: int = 0
    hour: int = 0
    minute: int = 0
    minutes_per_hour: int = 0
    dawn_hour: int = 0
    dusk_hour: int = 0
    #: (area resref, area name) for every area in the module, name-resolved.
    areas: list[tuple[str, str]] = field(default_factory=list)
    player_count: int = 0

    @property
    def game_time(self) -> str:
        """The in-game date/time, e.g. ``"1372/10/01 13:00"`` (empty if unknown)."""
        if not self.year:
            return ""
        return f"{self.year}/{self.month:02d}/{self.day:02d} {self.hour:02d}:{self.minute:02d}"


@dataclass
class SaveGame:
    """A save-game folder — its paths + (lazily read) module info."""

    folder: Path
    location: str = ""
    saved: datetime | None = None

    @property
    def name(self) -> str:
        return self.folder.name

    @property
    def sav_path(self) -> Path | None:
        return next(iter(sorted(self.folder.glob("*.sav"))), None)

    @property
    def player_bic(self) -> Path | None:
        bic = self.folder / "player.bic"
        return bic if bic.is_file() else None

    @property
    def screenshot(self) -> Path | None:
        for name in _SCREENSHOTS:
            shot = self.folder / name
            if shot.is_file():
                return shot
        return None

    def module_info(self) -> ModuleSaveInfo | None:
        """Decode this save's ``module.ifo`` (reads the ``.sav`` — call on demand)."""
        return read_module_info(self.sav_path) if self.sav_path else None


def scan_save_games(saves_dir: Path | None) -> list[SaveGame]:
    """Every save folder under ``saves_dir`` (each with a ``.sav``), newest first."""
    if saves_dir is None or not saves_dir.is_dir():
        return []
    saves: list[SaveGame] = []
    for folder in saves_dir.iterdir():
        if not folder.is_dir() or not any(folder.glob("*.sav")):
            continue
        location, _module = get_location_in_game_save(folder)
        try:
            saved = datetime.fromtimestamp(folder.stat().st_mtime)
        except OSError:
            saved = None
        saves.append(SaveGame(folder=folder, location=location, saved=saved))
    saves.sort(key=lambda s: s.saved or datetime.min, reverse=True)
    return saves


def read_module_info(sav_path: Path, *, read_area_names: bool = True) -> ModuleSaveInfo | None:
    """Decode ``module.ifo`` (+ area names) from a ``.sav`` ERF; ``None`` if unreadable."""
    reader = ErfReader()
    ifo = reader.find_resource(sav_path, "module", res_type=_IFO_RESTYPE)
    if ifo is None:
        return None
    try:
        gff = _GFF(reader.read_resource_bytes(sav_path, ifo))
    except Exception:
        return None

    info = ModuleSaveInfo()
    scalars = {
        "Mod_XPScale": "xp_scale", "Mod_StartYear": "year", "Mod_StartMonth": "month",
        "Mod_StartDay": "day", "Mod_StartHour": "hour", "Mod_StartMinute": "minute",
        "Mod_MinPerHour": "minutes_per_hour", "Mod_DawnHour": "dawn_hour",
        "Mod_DuskHour": "dusk_hour",
    }
    strings = {
        "Mod_Name": "name", "Mod_Description": "description", "Mod_Tag": "tag",
        "Mod_Entry_Area": "entry_area", "Mod_MinGameVer": "min_game_version",
    }
    area_resrefs: list[str] = []
    for label, ftype, raw in gff.iter_struct_fields(0):
        if label in scalars:
            value = gff.read_value(ftype, raw)
            if isinstance(value, int):
                setattr(info, scalars[label], value)
        elif label in strings:
            setattr(info, strings[label], (gff.read_value(ftype, raw) or "").strip())
        elif label == "Mod_Area_list" and ftype == _GFFType.LIST:
            for struct_id in gff.read_value(ftype, raw):
                for l2, t2, r2 in gff.iter_struct_fields(struct_id):
                    if l2 == "Area_Name":
                        area_resrefs.append(gff.read_value(t2, r2) or "")
        elif label == "Mod_PlayerList" and ftype == _GFFType.LIST:
            info.player_count = len(gff.read_value(ftype, raw))

    for resref in area_resrefs:
        name = _read_area_name(reader, sav_path, resref) if read_area_names else None
        info.areas.append((resref, name or resref))
    return info


def _read_area_name(reader: ErfReader, sav_path: Path, resref: str) -> str | None:
    """The localized ``Name`` of an area (``<resref>.are``) inside the ``.sav``."""
    resource = reader.find_resource(sav_path, resref, res_type=_ARE_RESTYPE)
    if resource is None:
        return None
    try:
        gff = _GFF(reader.read_resource_bytes(sav_path, resource))
    except Exception:
        return None
    for label, ftype, raw in gff.iter_struct_fields(0):
        if label == "Name" and ftype == _GFFType.CEXOLOCSTRING:
            return (gff.read_value(ftype, raw) or "").strip() or None
    return None
