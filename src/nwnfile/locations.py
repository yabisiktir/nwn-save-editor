"""Cross-platform discovery of Neverwinter Nights installations and user folders.

This replaces the VB app's Windows-registry / Beamdog-client heuristics
(``Paths.vb`` GetProgramPath / DetectExtended / Steam-GOG library scans) with a
platform-neutral scanner that understands:

* **Native** installs on Windows, macOS and Linux (Steam, GOG, Beamdog layouts).
* **Wine / CrossOver** prefixes — a first-class case for NWN on Linux/macOS.
  Windows-style paths (``C:\\...``) are resolved inside a prefix's ``drive_c``,
  and CrossOver "bottles" are scanned.
* **Network / UNC** locations — the caller may supply an explicit path (SMB
  mount, UNC ``\\\\host\\share``); these are validated but never auto-scanned.

Discovery is best-effort and returns *candidates*; the UI confirms or lets the
user locate manually (mirroring the original ``SolicitNwnExeFile`` fallback).
Nothing here writes to disk or mutates game files.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from nwnfile.editions import Edition

# Steam depot ids.
_STEAM_EE_APPID = "704450"

# Folder / executable markers that identify a real NWN install root.
_EE_DATA_MARKERS = ("data", "bin")
_EE_EXE_NAMES = ("nwmain", "nwmain.exe", "nwn.exe", "nwmain-x86", "nwmain_x64")


class HostOS(StrEnum):
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"

    @staticmethod
    def current() -> HostOS:
        if sys.platform.startswith("win"):
            return HostOS.WINDOWS
        if sys.platform == "darwin":
            return HostOS.MACOS
        return HostOS.LINUX


class InstallKind(StrEnum):
    STEAM = "steam"
    GOG = "gog"
    BEAMDOG = "beamdog"
    WINE = "wine"
    MANUAL = "manual"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GameInstall:
    """A discovered (or user-supplied) NWN installation candidate."""

    root: Path
    edition: Edition = Edition.ENHANCED
    kind: InstallKind = InstallKind.UNKNOWN
    #: Wine/CrossOver prefix this install lives inside, if any.
    wine_prefix: Path | None = None
    #: True when reached over a network mount / UNC path.
    is_network: bool = False

    @property
    def is_wine(self) -> bool:
        return self.wine_prefix is not None

    def exists(self) -> bool:
        try:
            return self.root.is_dir()
        except OSError:
            # Network paths can raise rather than return False when unreachable.
            return False


# --------------------------------------------------------------------------- #
# Path helpers
# --------------------------------------------------------------------------- #
def is_network_path(path: os.PathLike[str] | str) -> bool:
    """Heuristically detect a UNC or mounted-network location.

    Recognises Windows UNC (``\\\\host\\share``), and common Unix network mount
    roots (``/Volumes`` on macOS for SMB/AFP, ``/mnt`` and ``/media`` on Linux,
    ``/net`` autofs). This is advisory: used to skip auto-scanning and to warn
    about availability, not to block usage.
    """
    s = str(path)
    if s.startswith(("\\\\", "//")):  # Windows UNC
        return True
    # PurePosixPath, not PurePath: this asks whether a *string* looks like a POSIX
    # network mount, which does not depend on the machine asking. PurePath is
    # PureWindowsPath on Windows, where the root part is "\\" rather than "/" — so
    # the check below silently matched nothing there and every /Volumes, /mnt,
    # /media and /net path was reported as local.
    #
    # The separators are folded first because this accepts a Path as well as a
    # string, and a Path has already been normalised to the host's separator:
    # Path("/Volumes/NAS") stringifies as "\\Volumes\\NAS" on Windows, which the
    # POSIX parse reads as one long filename. Folding costs us nothing real — a
    # backslash is legal in a POSIX filename, but not in one of these four mount
    # roots, which is all this looks at.
    parts = PurePosixPath(s.replace("\\", "/")).parts
    # POSIX network mount roots: /Volumes (macOS SMB/AFP), /mnt & /media (Linux),
    # /net (autofs).
    network_roots = {"Volumes", "mnt", "media", "net"}
    return len(parts) >= 2 and parts[0] == "/" and parts[1] in network_roots


def resolve_wine_path(windows_path: str, prefix: Path) -> Path:
    """Map a Windows-style path (``C:\\Program Files\\...``) into a Wine prefix.

    ``prefix`` is the WINEPREFIX root (the directory containing ``drive_c``).
    Drive letters other than the prefix's mapped drives fall back to ``drive_c``.
    """
    win = windows_path.replace("\\", "/")
    drive = ""
    rest = win
    if len(win) >= 2 and win[1] == ":":
        drive = win[0].lower()
        rest = win[2:]
    rest = rest.lstrip("/")
    dosdevices = prefix / "dosdevices" / f"{drive}:"
    if drive and dosdevices.exists():
        return (dosdevices / rest).resolve()
    return (prefix / "drive_c" / rest)


# --------------------------------------------------------------------------- #
# Candidate roots per platform
# --------------------------------------------------------------------------- #
def _home() -> Path:
    return Path(os.path.expanduser("~"))


def steam_library_roots(host: HostOS) -> list[Path]:
    """Base Steam ``steamapps`` directories to search (default library only here).

    Parsing ``libraryfolders.vdf`` for extra libraries is added in a later phase;
    the format is identical across platforms, so it slots in here.
    """
    home = _home()
    if host is HostOS.MACOS:
        return [home / "Library/Application Support/Steam/steamapps"]
    if host is HostOS.LINUX:
        return [
            home / ".steam/steam/steamapps",
            home / ".local/share/Steam/steamapps",
            home / ".var/app/com.valvesoftware.Steam/data/Steam/steamapps",  # Flatpak
        ]
    # Windows
    return [
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Steam/steamapps"
    ]


def _steam_ee_common_path(steamapps: Path) -> Path:
    return steamapps / "common" / "Neverwinter Nights"


def wine_prefixes(host: HostOS) -> list[Path]:
    """Locate Wine/CrossOver prefixes worth scanning.

    Honours ``$WINEPREFIX``; adds the default ``~/.wine`` and CrossOver bottles
    (``~/Library/Application Support/CrossOver/Bottles`` on macOS,
    ``~/.cxoffice`` on Linux).
    """
    prefixes: list[Path] = []
    env_prefix = os.environ.get("WINEPREFIX")
    if env_prefix:
        prefixes.append(Path(env_prefix))
    home = _home()
    prefixes.append(home / ".wine")
    if host is HostOS.MACOS:
        bottles = home / "Library/Application Support/CrossOver/Bottles"
    else:
        bottles = home / ".cxoffice"
    if bottles.is_dir():
        for bottle in _safe_iterdir(bottles):
            if bottle.is_dir():
                prefixes.append(bottle)
    # De-duplicate, keep only existing.
    seen: set[Path] = set()
    out: list[Path] = []
    for p in prefixes:
        rp = p.expanduser()
        if rp not in seen and rp.is_dir():
            seen.add(rp)
            out.append(rp)
    return out


def user_documents_dir(host: HostOS, wine_prefix: Path | None = None) -> Path:
    """The NWN:EE per-user directory (``Documents/Neverwinter Nights``).

    This is where the game keeps ``nwn.ini``/``settings.tml``, ``saves``,
    ``localvault`` etc. This is read, never silently rewritten: it is the game's own
    configuration, not ours.
    """
    if wine_prefix is not None:
        # Inside a prefix the game uses the Windows Documents location.
        user_home = wine_prefix / "drive_c/users" / _wine_user(wine_prefix)
        return user_home / "Documents/Neverwinter Nights"
    home = _home()
    if host is HostOS.MACOS:
        return home / "Documents/Neverwinter Nights"
    if host is HostOS.LINUX:
        # EE on Linux uses ~/.local/share/Neverwinter Nights by default.
        return home / ".local/share/Neverwinter Nights"
    return home / "Documents/Neverwinter Nights"


def _wine_user(prefix: Path) -> str:
    users = prefix / "drive_c/users"
    for entry in _safe_iterdir(users):
        if entry.is_dir() and entry.name not in ("Public", "All Users"):
            return entry.name
    return os.environ.get("USER", "crossover")


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def looks_like_nwn_root(path: Path) -> bool:
    """True if ``path`` looks like a real NWN install root."""
    try:
        if not path.is_dir():
            return False
    except OSError:
        return False
    names = {p.name.lower() for p in _safe_iterdir(path)}
    if any(marker in names for marker in _EE_DATA_MARKERS):
        return True
    return any(exe.lower() in names for exe in _EE_EXE_NAMES)


def discover_installs(
    host: HostOS | None = None,
    *,
    include_wine: bool = True,
    extra_roots: Iterable[Path] = (),
) -> list[GameInstall]:
    """Return de-duplicated NWN install candidates for the current machine.

    ``extra_roots`` lets the caller inject known/network locations to validate.
    """
    host = host or HostOS.current()
    found: list[GameInstall] = []
    seen: set[Path] = set()

    def add(install: GameInstall) -> None:
        try:
            key = install.root.resolve()
        except OSError:
            key = install.root
        if key in seen:
            return
        seen.add(key)
        found.append(install)

    # Native Steam.
    for steamapps in steam_library_roots(host):
        root = _steam_ee_common_path(steamapps)
        if looks_like_nwn_root(root):
            add(GameInstall(root=root, kind=InstallKind.STEAM))

    # Native GOG / Beamdog common spots.
    for root in _native_gog_beamdog_roots(host):
        if looks_like_nwn_root(root):
            add(GameInstall(root=root, kind=InstallKind.GOG))

    # Wine / CrossOver.
    if include_wine and host is not HostOS.WINDOWS:
        for prefix in wine_prefixes(host):
            for root in _wine_candidate_roots(prefix):
                if looks_like_nwn_root(root):
                    add(
                        GameInstall(
                            root=root,
                            kind=InstallKind.WINE,
                            wine_prefix=prefix,
                            edition=Edition.ENHANCED,
                        )
                    )

    # Caller-supplied (network mounts, manual locations).
    for root in extra_roots:
        rp = Path(root)
        if looks_like_nwn_root(rp):
            add(
                GameInstall(
                    root=rp,
                    kind=InstallKind.MANUAL,
                    is_network=is_network_path(rp),
                )
            )

    return found


def _native_gog_beamdog_roots(host: HostOS) -> list[Path]:
    home = _home()
    if host is HostOS.MACOS:
        return [
            home / "Library/Application Support/GOG.com/Neverwinter Nights Enhanced Edition",
            Path("/Applications/Neverwinter Nights Enhanced Edition.app/Contents/Resources"),
        ]
    if host is HostOS.LINUX:
        return [
            home / "GOG Games/Neverwinter Nights Enhanced Edition",
            home / ".local/share/GOG.com/Neverwinter Nights Enhanced Edition",
        ]
    # Windows
    pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    return [
        pf / "GOG Galaxy/Games/Neverwinter Nights Enhanced Edition",
        Path(r"C:\GOG Games/Neverwinter Nights Enhanced Edition"),
    ]


def _wine_candidate_roots(prefix: Path) -> Iterator[Path]:
    """Windows-side install spots to probe inside a Wine prefix."""
    for win in (
        r"C:\Program Files (x86)\Steam\steamapps\common\Neverwinter Nights",
        r"C:\GOG Games\Neverwinter Nights Enhanced Edition",
        r"C:\Program Files\Neverwinter Nights",
        r"C:\NeverwinterNights\NWN",  # classic Diamond default
    ):
        yield resolve_wine_path(win, prefix)


def _safe_iterdir(path: Path) -> list[Path]:
    try:
        return list(path.iterdir())
    except OSError:
        return []
