"""Read the contents of an NWN save game.

A save folder (``saves/<NNNNNN - name>/``) holds ``player.bic``, screenshots,
``savenfo.txt`` (the in-module location) and a ``.sav`` file. The ``.sav`` is an
ERF archive containing ``module.ifo`` (module state as GFF) plus the area files
(``.are`` static + ``.git`` instance). This decodes the useful bits — module name,
in-game date/time, XP scale and the area list — using the existing ERF + GFF
readers (like Leto's advanced view, read-only).
"""

from __future__ import annotations

import os
import re
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
    #: ``module_info`` memo: ``(identity, info, whether area names were read)``.
    #: Not part of the save's identity, so it stays out of ``==`` and ``repr``.
    _info_cache: tuple | None = field(
        default=None, repr=False, compare=False
    )

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

    def module_info(self, *, read_area_names: bool = True) -> ModuleSaveInfo | None:
        """Decode this save's ``module.ifo`` (reads the ``.sav`` — call on demand).

        Pass ``read_area_names=False`` when only the module's own fields are
        wanted: naming the areas costs one extra archive lookup *per area*, and a
        caller that just wants the module name should not pay for it.

        The result is memoized against the ``.sav``'s size and mtime, so repeated
        calls (the Open dialog, then the party and area screens) read the archive
        once — while a save rewritten on disk is still re-read rather than served
        stale.
        """
        sav = self.sav_path
        if sav is None:
            return None
        try:
            stat = sav.stat()
            key = (str(sav), stat.st_size, stat.st_mtime_ns)
        except OSError:
            key = None

        cached = self._info_cache
        if key is not None and cached is not None:
            cached_key, cached_info, has_areas = cached
            # An entry read *with* area names answers either question; one read
            # without them cannot answer a caller that wants them.
            if cached_key == key and (has_areas or not read_area_names):
                return cached_info

        info = read_module_info(sav, read_area_names=read_area_names)
        if key is not None:
            self._info_cache = (key, info, read_area_names)
        return info


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


#: A drive-letter or UNC path (``C:\`` / ``C:/`` / ``\\server``) — Windows-absolute.
_WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
#: A leading slash — POSIX-absolute.
_POSIX_ABSOLUTE = re.compile(r"^/")


def _alias_target(value: str, user_dir: Path) -> Path | None:
    """Resolve an ``nwn.ini`` alias value the way the game does.

    Absolute native paths are used as-is; a **relative** value is joined onto the
    user directory (VB ``CombinePath``), not the current working directory — the
    naïve ``Path(value).is_dir()`` checked the cwd, so a relative ``SAVES`` never
    resolved. A path written by the *other* operating system is dropped rather than
    mangled: on Windows a POSIX ``/Users/…`` is *rooted, not absolute*, so joining
    it silently splices it onto the current drive and finds nothing — the very
    reason this misbehaved on Windows. Foreign → ``None`` → the caller falls back
    to the default ``<user_dir>/saves``.
    """
    value = value.strip().strip('"')
    if not value:
        return None
    looks_windows = bool(_WINDOWS_ABSOLUTE.match(value))
    looks_posix = bool(_POSIX_ABSOLUTE.match(value))
    if looks_windows or looks_posix:
        native = looks_windows if os.name == "nt" else looks_posix
        return Path(value) if native else None
    return Path(user_dir) / value


def saves_alias_from_ini(user_dir: Path) -> Path | None:
    """The ``SAVES=`` entry from ``<user_dir>/nwn.ini``'s ``[Alias]`` section.

    That entry is where NWN actually writes saves, and it need not be the default
    ``<user_dir>/saves`` — the player can point it elsewhere, absolutely or relative
    to the user directory. Returns the path only if it resolves to a real folder on
    *this* machine (see :func:`_alias_target` for the cross-platform handling); a
    ``SAVES`` written by another operating system is ignored so the caller falls
    back to the default.
    """
    ini = user_dir / "nwn.ini"
    try:
        lines = ini.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    in_alias = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_alias = line[1:-1].strip().lower() == "alias"
        elif in_alias and "=" in line:
            key, _, value = line.partition("=")
            if key.strip().lower() == "saves":
                target = _alias_target(value, user_dir)
                return target if target is not None and target.is_dir() else None
    return None


def primary_saves_dir(user_dir: Path | None) -> Path | None:
    """The current saves directory: the ``nwn.ini`` ``SAVES`` alias if it resolves
    here, else the default ``<user_dir>/saves``."""
    if user_dir is None:
        return None
    return saves_alias_from_ini(user_dir) or (user_dir / "saves")


def has_saves_directory(
    user_dir: Path | None, extra_dirs: list[Path] | tuple[Path, ...] = ()
) -> bool:
    """Whether a real saves directory exists to scan — even if it holds no saves.

    Distinguishes "the folders are set up, there just aren't any saves" (a resolved
    ``nwn.ini`` ``SAVES`` alias, an existing ``<user_dir>/saves``, or a configured
    extra folder) from "nothing is pointed at yet". The launcher uses it to say
    "no save games found" instead of the first-run *setup* dialog, which misleads
    when the folders are in fact correct.
    """
    primary = primary_saves_dir(user_dir)
    if primary is not None and primary.is_dir():
        return True
    return any(Path(directory).is_dir() for directory in extra_dirs)


def scan_all_saves(
    user_dir: Path | None, extra_dirs: list[Path] | tuple[Path, ...] = ()
) -> list[SaveGame]:
    """Saves from the install's current saves directory *and* every extra folder.

    The **primary** location is where the game actually writes saves — the
    ``nwn.ini`` ``SAVES`` alias when set, otherwise ``<user_dir>/saves`` (see
    :func:`primary_saves_dir`). The extra folders are secondary: each is one that
    itself holds save sub-folders (a second ``saves`` directory, a backup drive).
    Results are de-duplicated by folder path — the same save reached two ways is
    listed once, the primary winning — and stay newest-first across all sources.
    """
    dirs: list[Path] = []
    primary = primary_saves_dir(user_dir)
    if primary is not None:
        dirs.append(primary)
    dirs.extend(extra_dirs)
    seen: set[Path] = set()
    out: list[SaveGame] = []
    for saves_dir in dirs:
        for save in scan_save_games(saves_dir):
            try:
                key = save.folder.resolve()
            except OSError:
                key = save.folder
            if key not in seen:
                seen.add(key)
                out.append(save)
    out.sort(key=lambda s: s.saved or datetime.min, reverse=True)
    return out


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
