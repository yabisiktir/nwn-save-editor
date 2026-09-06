"""Port a Tier-2 item power (a dispatcher branch) into a standalone tag-script.

Some modules implement an item's activated power not as a script named after the
item's tag but as a ``if (GetTag(item)=="<tag>") { … }`` branch inside one big
``OnActivateItem`` dispatcher (e.g. Sands of Time's ``activateitem3``). That branch
can't be copied as a file — there is no standalone script. This module rebuilds one:

* wrap the branch in a ``main`` that restores the dispatcher's activate-event
  locals (``GetItemActivated``/``GetItemActivator``/target/target-location) so the
  branch's variable references resolve (:func:`generate_wrapper`);
* compile it, resolving ``#include``\\s **error-driven** — start with none and, for
  each ``Undeclared identifier`` the compiler reports, add the one module/hak
  include that defines it (:func:`resolve_and_compile`). This deliberately avoids
  adding the dispatcher's *whole* include list: those pull in colliding base
  includes (``nw_i0_tool`` vs ``nw_i0_plot`` both define ``DC_EASY``) that the
  branch never needs.

The actual compilation is injected as a ``compile_fn`` (see
:mod:`nwnsaveeditor.script_compiler` for the real nwnsc-backed one), so this module
is Qt-free and unit-testable with a fake compiler. A compiled ``.ncs`` is
self-contained (its includes are compiled in), so the result is a plain
``<tag>.ncs`` :func:`nwnsaveeditor.orphan_powers.apply_rescue` can bundle like any
Tier-1 script.

Honest limits: a branch that calls a helper *defined in the dispatcher itself*
(not via an include), or that uses a base-only include we don't index, won't
resolve — the compile fails and we report it rather than guessing.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

#: nwnsc's message for a symbol with no definition in scope.
_UNDECLARED = re.compile(r'Undeclared identifier "([^"]+)"')
#: A top-level function definition/prototype: ``<rettype> Name(``.
_FUNC_DEF = re.compile(
    r'^\s*(?:void|int|float|string|object|vector|location|effect|itemproperty|'
    r'event|talent|action|json|struct\s+\w+)\s+(\w+)\s*\(', re.MULTILINE)
#: A top-level constant: ``[const] <type> NAME =`` / ``#define NAME``.
_CONST_DEF = re.compile(
    r'^\s*(?:const\s+)?(?:int|float|string|object)\s+(\w+)\s*=|^\s*#define\s+(\w+)\b',
    re.MULTILINE)
#: The activate-event locals a dispatcher defines before its branches — restored so
#: a branch that uses any of them still compiles.
_PREAMBLE = (
    "    object item = GetItemActivated();\n"
    "    object oPC = GetItemActivator();\n"
    "    object target = GetItemActivatedTarget();\n"
    "    location targetloc = GetItemActivatedTargetLocation();\n")


@dataclass
class CompileResult:
    """The outcome of trying to port + compile a Tier-2 branch."""

    ncs: bytes | None = None
    includes: list[str] = field(default_factory=list)  #: includes that made it compile
    error: str = ""  #: compiler output when it did not compile

    @property
    def ok(self) -> bool:
        return self.ncs is not None


def generate_wrapper(branch_source: str, includes=()) -> str:
    """A standalone ``main`` around ``branch_source`` with the activate preamble.

    ``branch_source`` is the extracted ``if (GetTag(item)=="…") { … }`` block."""
    head = "".join(f'#include "{name}"\n' for name in includes)
    return f"{head}\nvoid main()\n{{\n{_PREAMBLE}{branch_source}\n}}\n"


def build_symbol_index(sources: dict[str, str]) -> dict[str, str]:
    """Map each symbol a module/hak include *defines* to that include's name.

    ``sources`` is ``{include_name: nss_text}`` (module + hak ``.nss``). First
    definer wins. Used to answer "which include defines ``PRCForceRest``?"."""
    index: dict[str, str] = {}
    for name, text in sources.items():
        for m in _FUNC_DEF.finditer(text):
            index.setdefault(m.group(1), name)
        for m in _CONST_DEF.finditer(text):
            index.setdefault(m.group(1) or m.group(2), name)
    return index


def undeclared_symbols(compiler_output: str) -> list[str]:
    """The identifiers nwnsc reported as undeclared, in order, de-duplicated."""
    seen: dict[str, None] = {}
    for m in _UNDECLARED.finditer(compiler_output):
        seen.setdefault(m.group(1), None)
    return list(seen)


def resolve_and_compile(
    branch_source: str, symbol_index: dict[str, str], sources: dict[str, str],
    compile_fn: Callable[[str, dict[str, str]], tuple[bytes | None, str]],
    *, max_iters: int = 16,
) -> CompileResult:
    """Compile the wrapped branch, adding the includes its symbols need one by one.

    ``compile_fn(nss_text, library)`` compiles ``nss_text`` with the whole
    ``{name: source}`` ``library`` available on disk (so an added include's *own*
    transitive ``#include``\\s resolve), returning ``(ncs_bytes_or_None,
    error_text)``. Only what the wrapper ``#include``\\s is actually compiled —
    keeping that list minimal is what dodges base-include collisions. Starting from
    no includes, each pass adds — for every still-undeclared symbol the compiler
    names — the module/hak include that defines it (per ``symbol_index``). Stops
    when it compiles, when a pass adds nothing new (an unresolvable symbol, or a
    non-symbol error), or after ``max_iters``."""
    includes: list[str] = []
    last_error = ""
    for _ in range(max_iters):
        wrapper = generate_wrapper(branch_source, includes)
        ncs, error = compile_fn(wrapper, sources)
        if ncs is not None:
            return CompileResult(ncs=ncs, includes=list(includes))
        last_error = error
        added = False
        for sym in undeclared_symbols(error):
            inc = symbol_index.get(sym)
            if inc and inc not in includes:
                includes.append(inc)
                added = True
        if not added:  # nothing left we know how to satisfy
            break
    return CompileResult(ncs=None, includes=list(includes), error=last_error)
