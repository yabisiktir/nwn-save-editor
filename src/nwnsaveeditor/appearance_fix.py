"""Apply the appearance decisions the reconcile wizard collects.

Three choices per item (see :mod:`nwnfile.icon_reconcile`):

* **keep** — change nothing;
* **match** — re-point the item at the closest appearance the module already has
  (a staged save edit only);
* **extract** — bundle the item's *original* art (icon, worn model, missing
  textures) into a **per-save hak** at its original appearance numbers and add that
  hak to the save's ``Mod_HakList``, so the true look renders in this save without
  touching the item or the module's own art.

This is Qt-free. It stages the ``match`` save edits through :class:`SaveEditor` (the
caller does ``save_as``), writes one hak into the user's ``hak`` folder and records
it in ``hak/vk_appearance_haks.json`` so a later run — or the user — can remove
exactly what was added. It deliberately does **not** use the ``override`` folder:
loose override files can only replace appearance numbers that already exist (never
add one), are ignored for held-weapon models, and high free-slot numbers do not
render at all — a hak carrying the original numbers is the only approach that works
in the running game (verified in-game).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from nwnfile.icon_reconcile import Appearance, ItemReport

_MANIFEST = "vk_appearance_haks.json"
_PLAYER = ("Mod_PlayerList", 0)
#: base items with no real inventory appearance to reconcile (PRC creature weapon,
#: the PC skin that carries PRC-managed properties).
_SKIP_BASE = {72, 73}


def collect_reports(reconciler, player_struct, female: bool):
    """Walk a player's worn + carried items — **including items inside bags** — and
    return ``[(item_path, report), …]`` for the ones whose appearance is broken in
    the target module. Qt-free."""
    out: list = []
    _walk_list(reconciler, player_struct, "Equip_ItemList", (_PLAYER,), female,
               "worn", out)
    _walk_list(reconciler, player_struct, "ItemList", (_PLAYER,), female,
               "carried", out)
    return out


def _walk_list(reconciler, container, list_label, base_path, female, slot, out):
    """Report every item in ``container``'s ``list_label``, then recurse into each
    item's own contents (a bag has its own ``ItemList``)."""
    from nwnfile.icon_reconcile import _ARMOUR_TOKENS

    field_ = container.fields.get(list_label)
    if field_ is None:
        return
    for i, it in enumerate(field_.value.structs):
        item_path = base_path + ((list_label, i),)
        base = it.get("BaseItem")
        if base is not None and base not in _SKIP_BASE:
            armor_parts = {
                name: int(it.get(name) or 0) for name in _ARMOUR_TOKENS
                if it.get(name) is not None
            }
            ap = Appearance(
                base, it.get("ModelPart1") or 0, it.get("ModelPart2") or 0,
                it.get("ModelPart3") or 0, it.get("ArmorPart_Torso") or 0,
                it.get("ArmorPart_Robe") or 0, female, armor_parts)
            report = reconciler.report(it.get("TemplateResRef") or "", slot, ap)
            if report.broken:
                out.append((item_path, report))
        # a container item carries its own ItemList — descend into the bag
        if "ItemList" in it.fields:
            _walk_list(reconciler, it, "ItemList", item_path, female,
                       "in a bag", out)
#: ArmorPart_* -> its truncated x-mirror twin (the game keeps the two in step).
_ARMOR_MIRROR = {
    "ArmorPart_Neck": "xArmorPart_Neck", "ArmorPart_Torso": "xArmorPart_Torso",
    "ArmorPart_Belt": "xArmorPart_Belt", "ArmorPart_Pelvis": "xArmorPart_Pelvi",
    "ArmorPart_LShoul": "xArmorPart_LShou", "ArmorPart_RShoul": "xArmorPart_RShou",
    "ArmorPart_LBicep": "xArmorPart_LBice", "ArmorPart_RBicep": "xArmorPart_RBice",
    "ArmorPart_LFArm": "xArmorPart_LFArm", "ArmorPart_RFArm": "xArmorPart_RFArm",
    "ArmorPart_LHand": "xArmorPart_LHand", "ArmorPart_RHand": "xArmorPart_RHand",
    "ArmorPart_LThigh": "xArmorPart_LThig", "ArmorPart_RThigh": "xArmorPart_RThig",
    "ArmorPart_LShin": "xArmorPart_LShin", "ArmorPart_RShin": "xArmorPart_RShin",
    "ArmorPart_LFoot": "xArmorPart_LFoot", "ArmorPart_RFoot": "xArmorPart_RFoot",
    "ArmorPart_Robe": "xArmorPart_Robe",
}


@dataclass
class Decision:
    """One item's chosen fix. ``item_path`` is the raw GFF path prefix of the item,
    e.g. ``(("Mod_PlayerList", 0), ("Equip_ItemList", 3))``."""

    item_path: tuple
    report: ItemReport
    choice: str  # "keep" | "match" | "extract"


@dataclass
class ApplySummary:
    edited: int = 0
    files_written: int = 0
    notes: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


def _set(editor, item_path: tuple, field_name: str, value: int, where: str) -> None:
    editor.set_raw_field("module.ifo", item_path + ((field_name, None),), value, where=where)
    mirror = _ARMOR_MIRROR.get(field_name)
    if mirror is not None:
        # an item without the x-mirror field just has nothing to sync
        with contextlib.suppress(Exception):
            editor.set_raw_field(
                "module.ifo", item_path + ((mirror, None),), value, where=where)


def hak_name_for(save_name: str) -> str:
    """A stable, unique hak name for a save being edited.

    Deterministic in the source save, so re-running the wizard on the same save
    reuses (overwrites) its hak rather than orphaning old ones. Kept **well under
    the engine's 16-char hak-name limit** — a 16-char name silently fails to load
    the whole hak, so ``vk_`` + 8 hex of a hash = 11 chars, still collision-safe
    across saves."""
    digest = hashlib.sha1(save_name.encode("utf-8", "replace")).hexdigest()
    return f"vk_{digest[:8]}"


def apply_decisions(
    editor, reader, decisions: list[Decision], hak_dir: Path, *, hak_name: str,
) -> ApplySummary:
    """Stage the save edits and bundle the extracted gear art into a per-save hak.

    The art is written into ``hak_dir/<hak_name>.hak`` and the hak is added to the
    save's ``module.ifo`` ``Mod_HakList`` (the engine honours the save's own hak
    list) — the reliable way to introduce appearance numbers the game renders.
    Loose ``override`` files cannot: they only replace numbers that already exist in
    a hak/base, and composite weapon/boot models ignore override entirely, so the
    old free-slot-in-override approach never rendered in the running game.

    The art is bundled at each item's **original** appearance numbers — verified
    in-game — and the item is *not* repointed. Relocating to a high free slot does
    **not** work: appearance numbers near the top of the byte range (our old 254-
    down slots) are not honoured for item models/icons even from a hak, so a
    relocated item fell back to the default picture. An item's original number is,
    by definition, one the engine renders (it did in the item's home campaign) and
    the module lacks (that is why it looks broken here), so bundling the original
    art at that number in this low-priority per-save hak fills exactly the gap
    without touching the item or clobbering module art. Two items that resolve to
    the same source resref share it (same number ⇒ same look — correct).

    ``reader`` reads the source bytes for every copy (a
    :class:`~nwnfile.resource_stack.ResourceStack`). Returns a summary; the caller
    writes the new save with ``editor.save_as`` afterwards."""
    from nwnfile.formats.erf_writer import build_hak

    summary = ApplySummary()
    entries: dict[tuple[str, int], bytes] = {}
    for d in decisions:
        if d.choice == "keep":
            continue
        if d.choice == "match":
            for fs in d.report.match_fields:
                _set(editor, d.item_path, fs.field, fs.value, f"match {d.report.resref}")
            summary.edited += 1
        elif d.choice == "extract" and d.report.extract is not None:
            plan = d.report.extract
            ok = True
            staged: dict[tuple[str, int], bytes] = {}
            for op in plan.copies:
                data = reader.read(op.src_resref, op.res_type)
                if data is None:
                    summary.notes.append(f"{d.report.resref}: source {op.src_resref} missing")
                    ok = False
                    continue
                # Bundle at the ORIGINAL resref (op.src_resref), not the relocated
                # slot — original numbers render, high free slots do not. The model
                # keeps its own internal name (no rename needed) and the item keeps
                # its ModelPart fields (no repoint).
                staged[(op.src_resref.lower(), op.res_type)] = data
            if ok:
                entries.update(staged)
                summary.edited += 1
    if entries:
        hak_dir.mkdir(parents=True, exist_ok=True)
        hak_path = hak_dir / f"{hak_name}.hak"
        hak_path.write_bytes(build_hak(
            (resref, res_type, blob) for (resref, res_type), blob in entries.items()))
        editor.add_module_hak(hak_name, where="fix appearances")
        _record_manifest(hak_dir, [hak_path.name])
        summary.files_written = len(entries)
    return summary


def hak_manifest(hak_dir: Path) -> list[str]:
    """The hak file(s) a previous Extract wrote into ``hak_dir``, or ``[]``."""
    path = hak_dir / _MANIFEST
    if not path.exists():
        return []
    try:
        return list(json.loads(path.read_text()).get("files", []))
    except (OSError, ValueError):
        return []


def remove_haks(hak_dir: Path) -> int:
    """Delete every hak a previous Extract added (per the manifest) and the manifest
    itself. Returns how many were removed. Touches only what the wizard wrote. Saves
    that referenced a removed hak simply show default pictures again (the engine
    skips a missing hak); their ``Mod_HakList`` entry is harmless."""
    removed = 0
    for name in hak_manifest(hak_dir):
        target = hak_dir / name
        if target.exists():
            try:
                target.unlink()
                removed += 1
            except OSError:
                pass
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
    merged = sorted(set(existing) | set(names))
    path.write_text(json.dumps({"files": merged}, indent=1))
