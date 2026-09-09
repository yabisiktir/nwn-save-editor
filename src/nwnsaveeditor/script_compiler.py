"""Locate and drive an NWScript compiler (nwnsc) to turn ``.nss`` into ``.ncs``.

Optional and environment-specific. :func:`find_compiler` returns ``None`` when no
compiler is available, and callers degrade to exporting the ``.nss`` for the user
to compile. When one is found, its :meth:`Compiler.compile` writes the source and
its includes to a temp dir, runs the tool, and returns the compiled bytes.

Discovery order (first hit wins):

1. ``VK_NWNSC`` — an explicit path to a compiler executable (``.exe`` or native);
2. a native ``nwnsc`` / ``nwn_script_comp`` on ``PATH``;
3. a **native ``nwnsc`` bundled with the app** under ``tools/<os>/`` (``macos`` /
   ``linux`` / ``windows``) — shipped so the Tier-2 port works out of the box, with
   no wine and nothing to install (a cross-platform build, e.g. nwneetools/nwnsc);
4. on macOS, a Windows ``nwnsc.exe`` run through **CrossOver**'s bundled wine in a
   64-bit bottle (``VK_CX_BOTTLE``, default ``Steam``) — the slow last resort.

A native compiler (1–3) is far faster than the wine path (4): wine pays a multi-
second cold start on *every* invocation, and the port recompiles several times.

The base-game include/engine definitions come from the NWN install passed as
``game_root`` (nwnsc ``-n``); module/hak includes are supplied per-compile by the
caller (written next to the source). Everything here is best-effort and never
raises on a missing tool — it just reports it can't compile.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import weakref
from dataclasses import dataclass, field
from pathlib import Path


def _rmtrees(dirs: list) -> None:
    """Remove every temp include dir a Compiler wrote (its GC finaliser)."""
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


_NWNSC_NAMES = ("nwnsc", "nwn_script_comp")
#: Per-OS subdir + binary name of a bundled native nwnsc (see _find_bundled_nwnsc).
_BUNDLED_OS = "windows" if sys.platform.startswith("win") else (
    "macos" if sys.platform == "darwin" else "linux")
_BUNDLED_NWNSC = "nwnsc.exe" if sys.platform.startswith("win") else "nwnsc"
_CROSSOVER_WINE = (
    "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/"
    "CrossOver-Hosted Application/wine")
#: Where a project-local nwnsc.exe tends to live (PRC toolset), searched on macOS.
_NWNSC_EXE_HINTS = (
    "PRC8/nwn/nwnprc/trunk/tools/nwnsc.exe",
    "PRC8/nwn/nwnprc/trunk/CompiledResources/nwnsc.exe",
)


@dataclass
class Compiler:
    """A located NWScript compiler and how to invoke it."""

    exe: Path
    game_root: Path | None
    runner: list[str]  #: prefix argv (e.g. the wine binary), empty for a native exe
    env: dict[str, str]  #: extra environment (e.g. CX_BOTTLE, WINEDEBUG)
    wine: bool  #: whether paths must be translated to a wine drive
    #: cached include dir + the (id,len) of the library written into it (see
    #: :meth:`_library_dir`); ``_temp_dirs`` are cleaned when this Compiler is GC'd.
    _inc_dir: Path | None = field(default=None, compare=False, repr=False)
    _inc_key: tuple | None = field(default=None, compare=False, repr=False)
    _temp_dirs: list = field(default_factory=list, compare=False, repr=False)

    def __post_init__(self) -> None:
        # One finaliser removes every temp include dir this Compiler wrote.
        weakref.finalize(self, _rmtrees, self._temp_dirs)

    def _path(self, p: Path) -> str:
        """A path as the tool sees it — a ``Z:`` drive path under wine, else native."""
        if not self.wine:
            return str(p)
        return "Z:" + str(p).replace("/", "\\")

    def _library_dir(self, library: dict[str, str]) -> Path:
        """The include dir holding ``library`` on disk, written **once** and reused.

        The Tier-2 port recompiles the same source with more ``#include`` lines each
        pass (:func:`nwnsaveeditor.script_port.resolve_and_compile`), handing the
        *same* library dict every time. Writing its thousands of ``.nss`` files on
        every pass dominated a fast (native) compile, so we key on the dict's
        identity and write it only when it changes."""
        key = (id(library), len(library))
        if self._inc_key != key:
            inc = Path(tempfile.mkdtemp(prefix="vk_inc_"))
            self._temp_dirs.append(str(inc))
            for name, text in library.items():
                (inc / f"{name}.nss").write_text(
                    text, encoding="latin-1", errors="replace")
            self._inc_dir = inc
            self._inc_key = key
        return self._inc_dir

    def compile(
        self, nss_text: str, library: dict[str, str] | None = None,
    ) -> tuple[bytes | None, str]:
        """Compile ``nss_text`` (as ``main.nss``) with a ``{name: source}`` library.

        The whole ``library`` is written to the include dir so an ``#include`` in
        the source (and *its* transitive includes) can resolve; only what the
        source actually includes is compiled. The include dir is written **once**
        and reused across calls with the same library (see :meth:`_library_dir`) —
        the port recompiles the same source many times, so re-writing thousands of
        files each pass was pure overhead. Returns ``(ncs_bytes | None, output)`` —
        success is decided by the ``.ncs`` actually appearing, since nwnsc's exit
        code is unreliable under wine."""
        inc = self._library_dir(library or {})
        with tempfile.TemporaryDirectory(prefix="vk_compile_") as tmp:
            work = Path(tmp)
            src = work / "main.nss"
            src.write_text(nss_text, encoding="latin-1", errors="replace")

            argv = [*self.runner, str(self.exe), "-c", "-i", self._path(inc),
                    "-b", self._path(work)]
            if self.game_root is not None:
                argv += ["-n", self._path(Path(self.game_root))]
            argv.append(self._path(src))

            env = {**os.environ, **self.env}
            try:
                proc = subprocess.run(
                    argv, capture_output=True, text=True, env=env, timeout=120)
                output = (proc.stdout or "") + (proc.stderr or "")
            except (OSError, subprocess.SubprocessError) as exc:
                return None, f"failed to run compiler: {exc}"

            out = work / "main.ncs"
            if out.exists():
                return out.read_bytes(), output
            return None, output


def find_compiler(game_root: Path | None = None) -> Compiler | None:
    """Locate a usable NWScript compiler, or ``None``. See the module docstring."""
    env_debug = {"WINEDEBUG": "-all"}

    override = os.environ.get("VK_NWNSC", "").strip()
    if override:
        exe = Path(override).expanduser()
        if exe.is_file():
            if exe.suffix.lower() == ".exe":
                wine = _crossover_wine()
                if wine is not None:
                    return Compiler(exe, game_root, [str(wine)], {
                        **env_debug, "CX_BOTTLE": os.environ.get("VK_CX_BOTTLE", "Steam")},
                        wine=True)
            else:
                return Compiler(exe, game_root, [], {}, wine=False)

    for name in _NWNSC_NAMES:
        found = shutil.which(name)
        if found:
            return Compiler(Path(found), game_root, [], {}, wine=False)

    bundled = _find_bundled_nwnsc()
    if bundled is not None:
        return Compiler(bundled, game_root, [], {}, wine=False)

    wine = _crossover_wine()
    if wine is not None:
        exe = _find_nwnsc_exe()
        if exe is not None:
            return Compiler(exe, game_root, [str(wine)], {
                **env_debug, "CX_BOTTLE": os.environ.get("VK_CX_BOTTLE", "Steam")},
                wine=True)
    return None


def _crossover_wine() -> Path | None:
    path = Path(_CROSSOVER_WINE)
    return path if path.is_file() else None


#: Runnable copies staged from a read-only bundle, cached by source path.
_STAGED_EXE: dict[str, Path] = {}


def _bundled_tool_roots() -> list[Path]:
    """Where a bundled ``tools/`` tree may live: next to a frozen binary
    (``sys._MEIPASS``) and in the source checkout (repo-root ``tools/``)."""
    roots: list[Path] = []
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        roots.append(Path(frozen) / "tools")
    # src/nwnsaveeditor/script_compiler.py -> parents[2] is the repo root.
    roots.append(Path(__file__).resolve().parents[2] / "tools")
    return roots


def _find_bundled_nwnsc() -> Path | None:
    """A native ``nwnsc`` shipped under ``tools/<os>/``, made runnable, or ``None``.

    Absent by default (the binary is OS-specific and not committed); a build/dev that
    drops one in is picked up here so the compiler works with no wine and no install."""
    for root in _bundled_tool_roots():
        candidate = root / _BUNDLED_OS / _BUNDLED_NWNSC
        if candidate.is_file():
            return _ensure_executable(candidate)
    return None


def _ensure_executable(path: Path) -> Path:
    """``path`` made runnable. PyInstaller ships ``datas`` without the exec bit, so
    add it; if the location is read-only (a signed ``.app``), stage a runnable copy
    in a temp dir (cached) and return that."""
    if os.access(path, os.X_OK):
        return path
    try:
        path.chmod(path.stat().st_mode | 0o111)
        if os.access(path, os.X_OK):
            return path
    except OSError:
        pass
    cached = _STAGED_EXE.get(str(path))
    if cached is not None and cached.is_file() and os.access(cached, os.X_OK):
        return cached
    staged_dir = Path(tempfile.mkdtemp(prefix="vk_nwnsc_"))
    dest = staged_dir / path.name
    shutil.copy2(path, dest)
    with contextlib.suppress(OSError):
        dest.chmod(dest.stat().st_mode | 0o111)
    _STAGED_EXE[str(path)] = dest
    return dest


def _find_nwnsc_exe() -> Path | None:
    """A Windows ``nwnsc.exe`` to run under wine — the PRC toolset, if present.

    Checks the known relative locations directly under a couple of roots, then, one
    directory deeper (a project checkout like ``Downloads/<repo>/PRC8/…``), via a
    bounded glob."""
    roots = (Path.home() / "Downloads", Path.home() / "Documents", Path.home())
    for base in roots:
        for hint in _NWNSC_EXE_HINTS:
            if (base / hint).is_file():
                return base / hint
    for base in roots:
        if not base.is_dir():
            continue
        for hint in _NWNSC_EXE_HINTS:
            for candidate in base.glob(f"*/{hint}"):
                if candidate.is_file():
                    return candidate
    return None
