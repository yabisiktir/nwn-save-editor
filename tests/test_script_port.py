"""Porting a Tier-2 dispatcher branch into a compilable tag-script.

The unit tests use a fake compiler (no toolchain needed). One opt-in test does a
real end-to-end compile of the Robe of Sesustris branch, skipped unless a compiler
and the real Sands of Time module are present.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from nwnsaveeditor import orphan_powers as op
from nwnsaveeditor import script_port as sp

_ROBE_BRANCH = (
    'if (GetTag(item)=="robesofsesustris")\n'
    '    {\n'
    '    PRCForceRest(oPC);\n'
    '    effect visual=EffectVisualEffect(VFX_FNF_MYSTICAL_EXPLOSION);\n'
    '    ApplyEffectToObject(DURATION_TYPE_INSTANT,visual,oPC);\n'
    '    return;\n'
    '    }')


def test_generate_wrapper_restores_activate_locals():
    wrapper = sp.generate_wrapper(_ROBE_BRANCH, ["prc_inc_util"])
    assert '#include "prc_inc_util"' in wrapper
    assert "GetItemActivator()" in wrapper and "GetItemActivated()" in wrapper
    assert _ROBE_BRANCH in wrapper


def test_build_symbol_index_maps_functions_and_constants():
    sources = {
        "prc_inc_util": "void PRCForceRest(object oPC) { }\nint FOO = 3;",
        "other": "void Unused() { }",
    }
    index = sp.build_symbol_index(sources)
    assert index["PRCForceRest"] == "prc_inc_util"
    assert index["FOO"] == "prc_inc_util"
    assert index["Unused"] == "other"


def test_undeclared_symbols_parses_nwnsc_output():
    out = ('main.nss(9): Error: NSC1020: Undeclared identifier "PRCForceRest"\n'
           'main.nss(9): Error: NSC1020: Undeclared identifier "PRCForceRest"\n'
           'main.nss(12): Error: NSC1020: Undeclared identifier "FOO"\n')
    assert sp.undeclared_symbols(out) == ["PRCForceRest", "FOO"]


def test_resolve_and_compile_adds_the_include_the_symbol_needs():
    sources = {"prc_inc_util": "void PRCForceRest(object o){}"}
    index = sp.build_symbol_index(sources)
    wrapper_includes = []

    def fake_compile(nss_text, library):
        # the whole library is always available; only the wrapper's #includes count
        assert library == sources
        included = '#include "prc_inc_util"' in nss_text
        wrapper_includes.append(included)
        if included:
            return b"NCS V1.0 compiled", ""
        return None, 'Error: NSC1020: Undeclared identifier "PRCForceRest"'

    result = sp.resolve_and_compile(_ROBE_BRANCH, index, sources, fake_compile)
    assert result.ok and result.ncs == b"NCS V1.0 compiled"
    assert result.includes == ["prc_inc_util"]
    assert wrapper_includes == [False, True]  # tried bare first, then with the include


def test_resolve_and_compile_gives_up_on_unresolvable_symbol():
    def fake_compile(nss_text, include_files):
        return None, 'Error: NSC1020: Undeclared identifier "SomeHelperInTheDispatcher"'

    result = sp.resolve_and_compile(_ROBE_BRANCH, {}, {}, fake_compile)
    assert not result.ok and "Undeclared" in result.error


def test_resolve_and_compile_stops_on_non_symbol_error():
    calls = []

    def fake_compile(nss_text, include_files):
        calls.append(1)
        return None, "Error: NSC5000: something structural"

    result = sp.resolve_and_compile(_ROBE_BRANCH, {}, {}, fake_compile)
    assert not result.ok and len(calls) == 1  # no symbol to add → one attempt only


# --- opt-in real end-to-end compile -----------------------------------------
_MODULE = Path("/Users/sarpkans/Documents/Neverwinter Nights/modules/"
               "SoF3 - Pyramid of the Ancients [PRC8-CEP2].mod")
_HAKDIR = Path("/Users/sarpkans/Documents/Neverwinter Nights/hak")
_GAME = Path("/Users/sarpkans/Library/Application Support/Steam/steamapps/"
             "common/Neverwinter Nights")


@pytest.mark.skipif(
    not (_MODULE.exists() and os.environ.get("VK_RUN_COMPILE")),
    reason="needs the real SoF3 module + a compiler; set VK_RUN_COMPILE=1 to run")
def test_real_robe_branch_compiles_end_to_end():
    from nwnsaveeditor import script_compiler

    compiler = script_compiler.find_compiler(_GAME if _GAME.exists() else None)
    assert compiler is not None, "no compiler found"

    match = op.search_sources("robesofsesustris", [_MODULE], is_resolved=lambda _n: False)
    assert match.tier == 2 and match.branch_source

    sources = op.gather_nss_sources([_MODULE, _HAKDIR / "prc8_include.hak"])
    index = sp.build_symbol_index(sources)
    result = sp.resolve_and_compile(
        match.branch_source, index, sources, compiler.compile)
    assert result.ok, result.error
    assert result.ncs[:8] == b"NCS V1.0"
    assert "prc_inc_util" in result.includes
