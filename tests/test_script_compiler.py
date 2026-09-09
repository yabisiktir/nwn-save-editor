"""The nwnsc wrapper (nwnsaveeditor.script_compiler) — focused on the include-dir
reuse that keeps a Tier-2 port from re-writing thousands of files each pass.

Nothing here needs a real compiler; :meth:`Compiler._library_dir` is pure I/O.
"""
from __future__ import annotations

import gc
import os
from pathlib import Path

from nwnsaveeditor import script_compiler as sc
from nwnsaveeditor.script_compiler import Compiler


def _place_bundled_nwnsc(tmp_path: Path) -> Path:
    """A fake native nwnsc under a tools/<os>/ tree, as a build would ship it."""
    tools = tmp_path / "tools"
    osdir = tools / sc._BUNDLED_OS
    osdir.mkdir(parents=True)
    exe = osdir / sc._BUNDLED_NWNSC
    exe.write_text("#!/bin/sh\ntrue\n")
    exe.chmod(0o644)  # datas-style: no exec bit yet
    return tools


def _compiler() -> Compiler:
    # exe/runner are irrelevant here — we only exercise the include-dir cache.
    return Compiler(exe=Path("/bin/echo"), game_root=None, runner=[], env={}, wine=False)


def test_library_dir_writes_once_and_reuses_for_the_same_library():
    c = _compiler()
    library = {"a": "void a(){}", "b": "void b(){}"}

    first = c._library_dir(library)
    assert sorted(p.name for p in first.iterdir()) == ["a.nss", "b.nss"]
    assert (first / "a.nss").read_text() == "void a(){}"

    # The port hands the SAME dict every pass — the dir is reused, not rewritten.
    again = c._library_dir(library)
    assert again == first
    assert len(c._temp_dirs) == 1


def test_library_dir_rewrites_when_the_library_changes():
    c = _compiler()
    first = c._library_dir({"a": "x"})
    second = c._library_dir({"a": "x", "b": "y"})  # a different dict/library
    assert second != first
    assert len(c._temp_dirs) == 2


def test_library_dirs_are_cleaned_up_when_the_compiler_is_gced():
    c = _compiler()
    c._library_dir({"a": "x"})
    c._library_dir({"a": "x", "b": "y"})
    dirs = [Path(p) for p in c._temp_dirs]
    assert all(d.exists() for d in dirs)

    del c
    gc.collect()
    assert all(not d.exists() for d in dirs), "temp include dirs must not leak"


# --- bundled native nwnsc discovery -----------------------------------------
def test_find_bundled_nwnsc_finds_and_makes_the_binary_runnable(tmp_path, monkeypatch):
    tools = _place_bundled_nwnsc(tmp_path)
    monkeypatch.setattr(sc, "_bundled_tool_roots", lambda: [tools])

    found = sc._find_bundled_nwnsc()
    assert found is not None
    assert found.name == sc._BUNDLED_NWNSC
    assert os.access(found, os.X_OK), "the bundled binary must be made executable"


def test_find_bundled_nwnsc_is_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "_bundled_tool_roots", lambda: [tmp_path / "tools"])
    assert sc._find_bundled_nwnsc() is None


def test_find_compiler_prefers_a_bundled_native_over_wine(tmp_path, monkeypatch):
    tools = _place_bundled_nwnsc(tmp_path)
    monkeypatch.delenv("VK_NWNSC", raising=False)
    monkeypatch.setattr(sc.shutil, "which", lambda _n: None)  # nothing on PATH
    monkeypatch.setattr(sc, "_bundled_tool_roots", lambda: [tools])
    monkeypatch.setattr(sc, "_crossover_wine", lambda: Path("/some/wine"))  # wine exists

    comp = sc.find_compiler(game_root=None)
    assert comp is not None
    assert comp.wine is False, "a native bundled nwnsc must win over the wine path"
    assert comp.runner == []
    assert comp.exe.name == sc._BUNDLED_NWNSC


def test_ensure_executable_adds_the_exec_bit_in_place(tmp_path):
    exe = tmp_path / "nwnsc"
    exe.write_text("#!/bin/sh\ntrue\n")
    exe.chmod(0o644)
    assert not os.access(exe, os.X_OK)

    out = sc._ensure_executable(exe)
    assert out == exe and os.access(out, os.X_OK)
