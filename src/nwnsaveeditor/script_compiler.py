"""Locate and drive an NWScript compiler (nwnsc) to turn ``.nss`` into ``.ncs``.

Optional and environment-specific. :func:`find_compiler` returns ``None`` when no
compiler is available, and callers degrade to exporting the ``.nss`` for the user
to compile. When one is found, its :meth:`Compiler.compile` writes the source and
its includes to a temp dir, runs the tool, and returns the compiled bytes.

Discovery order (first hit wins):

1. ``VK_NWNSC`` — an explicit path to a compiler executable (``.exe`` or native);
2. a native ``nwnsc`` / ``nwn_script_comp`` on ``PATH``;
3. on macOS, a Windows ``nwnsc.exe`` run through **CrossOver**'s bundled wine in a
   64-bit bottle (``VK_CX_BOTTLE``, default ``Steam``) — the setup verified on this
   developer's machine.

The base-game include/engine definitions come from the NWN install passed as
``game_root`` (nwnsc ``-n``); module/hak includes are supplied per-compile by the
caller (written next to the source). Everything here is best-effort and never
raises on a missing tool — it just reports it can't compile.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_NWNSC_NAMES = ("nwnsc", "nwn_script_comp")
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

    def _path(self, p: Path) -> str:
        """A path as the tool sees it — a ``Z:`` drive path under wine, else native."""
        if not self.wine:
            return str(p)
        return "Z:" + str(p).replace("/", "\\")

    def compile(
        self, nss_text: str, library: dict[str, str] | None = None,
    ) -> tuple[bytes | None, str]:
        """Compile ``nss_text`` (as ``main.nss``) with a ``{name: source}`` library.

        The whole ``library`` is written to the include dir so an ``#include`` in
        the source (and *its* transitive includes) can resolve; only what the
        source actually includes is compiled. Returns ``(ncs_bytes | None,
        output)`` — success is decided by the ``.ncs`` actually appearing, since
        nwnsc's exit code is unreliable under wine."""
        with tempfile.TemporaryDirectory(prefix="vk_compile_") as tmp:
            work = Path(tmp)
            inc = work / "inc"
            inc.mkdir()
            for name, text in (library or {}).items():
                (inc / f"{name}.nss").write_text(text, encoding="latin-1", errors="replace")
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
