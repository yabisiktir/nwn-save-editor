"""Rescue an item's orphaned *scripted* power into the current save.

A scripted item power — a "Unique Power"/"Activate Item" property
(:func:`nwnfile.item_properties.is_script_activated`) — carries no effect of its
own. Activating the item fires the module's ``OnActivateItem`` event, and when the
module uses BioWare **tag-based scripting** the engine then runs a script *named
after the item's tag*. That script lives in the item's home module, not on the
item, so an item carried into a different save has no script to run: the power is
**orphaned** — the property shows in the inventory but does nothing.

This module (Qt-free, mirroring :mod:`nwnsaveeditor.appearance_fix`) does three
things:

* **detect** — walk the player's items and flag script-activated properties whose
  tag-script is not resolvable in this save (:func:`find_orphans`);
* **search** — look through the installed modules/haks for the behaviour
  (:func:`search_sources`);
* **rescue** — for the clean case (the source ships a *standalone* tag-named
  compiled script), bundle that ``.ncs`` — plus any scripts it calls that this save
  lacks — into a per-save hak added to ``Mod_HakList`` (:func:`apply_rescue`),
  exactly like the appearance wizard, and reversibly (:func:`remove_haks`).

A compiled ``.ncs`` is self-contained (its ``#include`` code is compiled in), so
copying the bytes is enough — no compiler. The *monolithic-dispatcher* case (the
behaviour lives in a ``GetTag()=="…"`` branch of one big script, e.g. Sands of
Time's ``activateitem3``) has no standalone script to copy; it is reported as a
Tier-2 match (with the branch source for preview) but **not** auto-applied — that
path needs recompilation and human review (see the design plan's Phase 2).

Tag-based dispatch is a precondition (:func:`tagbased_scripting_enabled`): without
it a rescue hak never fires, and we deliberately do not edit the module's event
scripts or flip the switch (global side effects).
"""
from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from nwnfile.formats.erf_reader import ErfReader
from nwnfile.item_properties import is_script_activated

_MANIFEST = "vk_power_haks.json"
_NCS = 2010
_NSS = 2009
#: NWN resrefs (and therefore tag-based script names) cap at 16 characters.
_RESREF_MAX = 16
#: The module local int BioWare's x2 system sets to enable tag-based item scripts.
_TAGBASED_VARS = ("X2_SWITCH_ENABLE_TAGBASED_SCRIPTS", "X2_L_ENABLE_TAGBASED_SCRIPTS")
#: Tokens that look like a script resref, for tracing a compiled script's
#: ``ExecuteScript("…")`` dependencies out of its bytes.
_TOKEN = re.compile(rb"[A-Za-z0-9_]{2,16}")


def script_name_for_tag(tag: str) -> str:
    """The tag-based script name the engine runs for an item with this ``tag``.

    That is the tag, lower-cased and truncated to the 16-char resref limit (a
    longer tag simply can't name a script)."""
    return tag.strip().lower()[:_RESREF_MAX]


# --------------------------------------------------------------------------- #
#  Detection
# --------------------------------------------------------------------------- #
@dataclass
class OrphanPower:
    """A script-activated item property whose tag-script is missing from this save."""

    item_path: tuple  #: EditableItem.path — where to find the item in the save
    item_name: str
    tag: str
    script_name: str  #: the resref the engine would run (tag, ≤16 chars)
    prop_index: int
    label: str  #: readable property name, e.g. "Unique Power (self only)"


def tagbased_scripting_enabled(module_root) -> bool:
    """Whether this module runs tag-based item scripts (``X2_SWITCH_…`` local == 1).

    Read from the module object's ``VarTable`` — in a running save the switch the
    x2 module-load set is serialised there. When it is off, a rescued tag-script
    will not fire, so callers should warn rather than package silently."""
    vt = module_root.fields.get("VarTable") if module_root is not None else None
    if vt is None:
        return False
    for s in vt.value.structs:
        name = s.get("Name")
        if name in _TAGBASED_VARS and (s.get("Value") or 0) == 1:
            return True
    return False


def find_orphans(
    items, is_resolved: Callable[[str], bool], *, names=None
) -> list[OrphanPower]:
    """Flag every script-activated property whose tag-script this save can't resolve.

    ``items`` is ``session.player_items()`` (each an
    :class:`~nwnsaveeditor.save_editor.EditableItem`); ``is_resolved(script_name)``
    reports whether ``<script_name>.ncs`` already exists in the save or its haks
    (see :func:`make_resolver`). ``names`` is an optional ``{subtype: label}`` map
    (``item_properties.ACTIVATE_ITEM_SUBTYPES``) used only to label the finding.
    """
    from nwnfile.item_properties import ACTIVATE_ITEM_SUBTYPES

    names = ACTIVATE_ITEM_SUBTYPES if names is None else names
    out: list[OrphanPower] = []
    for item in items:
        tag = getattr(item, "tag", "") or ""
        if not tag:
            continue
        script = script_name_for_tag(tag)
        for ep in getattr(item, "properties", []):
            if not is_script_activated(ep.prop):
                continue
            if is_resolved(script):
                continue
            out.append(OrphanPower(
                item_path=item.path, item_name=item.name, tag=tag,
                script_name=script, prop_index=ep.index,
                label=names.get(ep.prop.subtype, "Unique Power")))
    return out


def make_resolver(sav_path: Path | None, hak_paths: Iterable[Path], *, reader=None):
    """Return ``is_resolved(name)`` — whether ``<name>.ncs`` exists in the save or a hak.

    Reads only the ERF key lists (no resource data), so it is cheap even on a
    large ``.sav``. Missing files are skipped."""
    reader = reader or ErfReader()
    present: set[str] = set()
    for path in [p for p in (sav_path, *hak_paths) if p and Path(p).exists()]:
        with contextlib.suppress(Exception):
            for r in reader.list_resources(Path(path)):
                if r.res_type == _NCS:
                    present.add(r.resref.lower())
    return lambda name: name.lower() in present


# --------------------------------------------------------------------------- #
#  Search
# --------------------------------------------------------------------------- #
@dataclass
class SourceMatch:
    """What a search for a tag-script turned up in the installed content."""

    tag: str
    script_name: str
    tier: int  #: 1 = standalone compiled script (auto-rescuable); 2 = dispatcher branch; 0 = none
    origin: str = ""  #: file the behaviour was found in (module/hak name)
    scripts: dict = field(default_factory=dict)  #: {(resref, res_type): bytes} to bundle (tier 1)
    needs_compile: bool = False  #: tier 1 but only source (.nss) found — Phase 2
    dispatcher: str = ""  #: tier 2: the script whose branch implements it
    branch_source: str = ""  #: tier 2: the extracted branch text, for preview
    notes: list = field(default_factory=list)

    @property
    def auto_rescuable(self) -> bool:
        return self.tier == 1 and bool(self.scripts) and not self.needs_compile


def _dependency_closure(
    root_bytes: bytes, ncs_by_name: dict[str, bytes], script_name: str,
    is_resolved: Callable[[str], bool],
) -> dict[str, bytes]:
    """Scripts this compiled script (transitively) calls that the save lacks.

    A compiled ``.ncs`` embeds the resrefs it ``ExecuteScript``s as plain strings;
    we scan for resref-like tokens and keep those that name another script in the
    same source and are not already resolvable in the target. Conservative: it may
    miss a computed name, and it never pulls a script the save can already resolve
    (e.g. ``prc_forcerest`` from ``prc8_scripts.hak``)."""
    found: dict[str, bytes] = {}
    queue = [(script_name, root_bytes)]
    seen = {script_name}
    while queue:
        _name, blob = queue.pop()
        for tok in {m.group().decode("ascii", "ignore").lower() for m in _TOKEN.finditer(blob)}:
            if tok in seen or tok not in ncs_by_name or is_resolved(tok):
                continue
            seen.add(tok)
            dep = ncs_by_name[tok]
            found[tok] = dep
            queue.append((tok, dep))
    return found


def search_sources(
    tag: str, sources: Iterable[Path], *,
    is_resolved: Callable[[str], bool] | None = None, reader=None,
) -> SourceMatch:
    """Search ``sources`` (``.mod``/``.hak`` paths) for a tag-script's behaviour.

    Prefers a Tier-1 hit (a standalone compiled ``<tag>.ncs`` — copyable as-is,
    with its missing-dependency closure); falls back to a Tier-2 hit (a
    ``GetTag()=="<tag>"`` branch inside a dispatcher script, reported for preview
    but not auto-applied). Returns a ``tier == 0`` match if nothing is found."""
    reader = reader or ErfReader()
    is_resolved = is_resolved or (lambda _n: False)
    script = script_name_for_tag(tag)
    branch_re = re.compile(
        r'GetTag\s*\([^)]*\)\s*==\s*"' + re.escape(script) + r'"', re.IGNORECASE)

    tier2: SourceMatch | None = None
    source_only: SourceMatch | None = None
    for src in (Path(s) for s in sources):
        if not src.exists():
            continue
        try:
            resources = reader.list_resources(src)
        except Exception:  # noqa: BLE001 — unreadable archive, skip
            continue
        ncs_by_name = {
            r.resref.lower(): reader.read_resource_bytes(src, r)
            for r in resources if r.res_type == _NCS}
        nss_names = {r.resref.lower(): r for r in resources if r.res_type == _NSS}

        if script in ncs_by_name:  # Tier 1: standalone compiled script — copy it
            blob = ncs_by_name[script]
            scripts = {(script, _NCS): blob}
            for dep_name, dep_bytes in _dependency_closure(
                    blob, ncs_by_name, script, is_resolved).items():
                scripts[(dep_name, _NCS)] = dep_bytes
            return SourceMatch(
                tag=tag, script_name=script, tier=1, origin=src.name, scripts=scripts,
                notes=[f"copied {len(scripts)} script(s) from {src.name}"])

        if script in nss_names and source_only is None:  # source only — needs compile
            source_only = SourceMatch(
                tag=tag, script_name=script, tier=1, origin=src.name,
                needs_compile=True,
                notes=[f"only source {script}.nss found in {src.name} — needs compiling"])

        if tier2 is None:  # Tier 2: a dispatcher branch keyed on the tag
            for r in nss_names.values():
                text = reader.read_resource_bytes(src, r).decode("latin-1", "replace")
                if branch_re.search(text):
                    tier2 = SourceMatch(
                        tag=tag, script_name=script, tier=2, origin=src.name,
                        dispatcher=r.resref, branch_source=_extract_branch(text, branch_re),
                        notes=[f"behaviour is a branch inside {r.resref} in {src.name} "
                               "— needs a compiled port (manual review)"])
                    break

    return source_only or tier2 or SourceMatch(tag=tag, script_name=script, tier=0)


def _extract_branch(text: str, branch_re: re.Pattern) -> str:
    """The ``if (GetTag(...)=="tag") { … }`` block, for preview. Best-effort brace
    match from the matched condition; falls back to a window around the match."""
    m = branch_re.search(text)
    if m is None:
        return ""
    brace = text.find("{", m.end())
    if brace == -1:
        return text[max(0, m.start() - 40):m.end() + 400]
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                start = text.rfind("if", 0, m.start())
                return text[start if start != -1 else m.start():i + 1]
    return text[m.start():m.end() + 400]


# --------------------------------------------------------------------------- #
#  Apply (Tier 1 only)
# --------------------------------------------------------------------------- #
@dataclass
class RescueSummary:
    powers: int = 0  #: orphan powers rescued
    scripts: int = 0  #: script files bundled
    hak: str = ""
    notes: list = field(default_factory=list)


def apply_rescue(
    editor, matches: Iterable[SourceMatch], hak_dir: Path, *,
    hak_name: str, where: str = "rescue item power",
) -> RescueSummary:
    """Bundle the auto-rescuable matches' scripts into one per-save hak and add it.

    Mirrors :func:`nwnsaveeditor.appearance_fix.apply_decisions`: writes
    ``hak_dir/<hak_name>.hak``, calls ``editor.add_module_hak(hak_name)`` and records
    the file in a manifest for later removal. Only Tier-1 (compiled) matches are
    packaged; anything else is skipped (and noted). The caller writes the new save
    with ``editor.save_as`` afterwards. Returns a summary."""
    from nwnfile.formats.erf_writer import build_hak

    summary = RescueSummary()
    entries: dict[tuple[str, int], bytes] = {}
    for match in matches:
        if not match.auto_rescuable:
            summary.notes.append(
                f"{match.tag}: not auto-rescuable (tier {match.tier}"
                f"{', needs compiling' if match.needs_compile else ''})")
            continue
        entries.update(match.scripts)
        summary.powers += 1
    if not entries:
        return summary

    hak_dir.mkdir(parents=True, exist_ok=True)
    hak_path = hak_dir / f"{hak_name}.hak"
    hak_path.write_bytes(build_hak(
        (resref, res_type, blob) for (resref, res_type), blob in entries.items()))
    editor.add_module_hak(hak_name, where=where)
    _record_manifest(hak_dir, [hak_path.name])
    summary.hak = hak_path.name
    summary.scripts = len(entries)
    return summary


# --------------------------------------------------------------------------- #
#  Manifest / removal (a per-save-power hak set, distinct from appearance haks)
# --------------------------------------------------------------------------- #
def hak_manifest(hak_dir: Path) -> list[str]:
    """The hak file(s) a previous rescue wrote into ``hak_dir``, or ``[]``."""
    path = hak_dir / _MANIFEST
    if not path.exists():
        return []
    try:
        return list(json.loads(path.read_text()).get("files", []))
    except (OSError, ValueError):
        return []


def remove_haks(hak_dir: Path) -> int:
    """Delete every rescue hak recorded in the manifest and the manifest itself.

    Returns how many hak files were removed. Touches only what a rescue wrote; a
    save that still lists a removed hak simply loses the rescued power again (the
    engine skips a missing hak — the ``Mod_HakList`` entry is harmless)."""
    removed = 0
    for name in hak_manifest(hak_dir):
        target = hak_dir / name
        if target.exists():
            with contextlib.suppress(OSError):
                target.unlink()
                removed += 1
    manifest = hak_dir / _MANIFEST
    if manifest.exists():
        with contextlib.suppress(OSError):
            manifest.unlink()
    return removed


def _record_manifest(hak_dir: Path, names: list[str]) -> None:
    """Append the written hak filenames to the manifest, for later removal."""
    path = hak_dir / _MANIFEST
    existing: list[str] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text()).get("files", [])
        except (OSError, ValueError):
            existing = []
    path.write_text(json.dumps({"files": sorted(set(existing) | set(names))}, indent=1))
