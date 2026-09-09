"""The nwnsc wrapper (nwnsaveeditor.script_compiler) — focused on the include-dir
reuse that keeps a Tier-2 port from re-writing thousands of files each pass.

Nothing here needs a real compiler; :meth:`Compiler._library_dir` is pure I/O.
"""
from __future__ import annotations

import gc
from pathlib import Path

from nwnsaveeditor.script_compiler import Compiler


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
