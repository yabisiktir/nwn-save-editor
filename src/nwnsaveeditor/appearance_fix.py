"""Apply the appearance decisions the reconcile wizard collects.

Three choices per item (see :mod:`nwnfile.icon_reconcile`):

* **keep** — change nothing;
* **match** — re-point the item at the closest appearance the module already has
  (a staged save edit only);
* **extract** — copy the item's *original* icon into a free appearance slot in the
  user's ``override`` folder and re-point the item at it, so the true look renders
  in every module and collides with nothing.

This is Qt-free. It stages save edits through :class:`SaveEditor` (the caller does
``save_as``) and writes the override files immediately, recording every file it
writes in ``override/vk_appearance_manifest.json`` so a later run — or the user —
can remove exactly what was added.
"""
from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from pathlib import Path

from nwnfile.icon_reconcile import Appearance, ItemReport

_MANIFEST = "vk_appearance_manifest.json"
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
_EXT = {3: ".tga", 6: ".plt", 2002: ".mdl", 2005: ".txi", 2064: ".dds", 2065: ".dds"}
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


def apply_decisions(
    editor, reader, decisions: list[Decision], override_dir: Path,
) -> ApplySummary:
    """Stage the save edits and write the override art. ``reader`` reads the source
    bytes for every copy (a :class:`~nwnfile.resource_stack.ResourceStack`, which
    reads icons, models and textures alike). Returns a summary; the caller writes
    the new save with ``editor.save_as`` afterwards."""
    summary = ApplySummary()
    written: list[str] = []
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
            for op in plan.copies:
                data = reader.read(op.src_resref, op.res_type)
                if data is None:
                    summary.notes.append(f"{d.report.resref}: source {op.src_resref} missing")
                    ok = False
                    continue
                dst = override_dir / f"{op.dst_resref.lower()}{_EXT.get(op.res_type, '')}"
                override_dir.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                written.append(dst.name)
            if ok:
                for fs in plan.fields:
                    _set(editor, d.item_path, fs.field, fs.value, f"extract {d.report.resref}")
                summary.edited += 1
    if written:
        _record_manifest(override_dir, written)
        summary.files_written = len(written)
    return summary


def override_manifest(override_dir: Path) -> list[str]:
    """The files a previous Extract wrote into ``override_dir``, or ``[]``."""
    path = override_dir / _MANIFEST
    if not path.exists():
        return []
    try:
        return list(json.loads(path.read_text()).get("files", []))
    except (OSError, ValueError):
        return []


def remove_override(override_dir: Path) -> int:
    """Delete every file a previous Extract added (per the manifest) and the
    manifest itself. Returns how many files were removed. Touches only what the
    wizard wrote — never other override content."""
    removed = 0
    for name in override_manifest(override_dir):
        target = override_dir / name
        if target.exists():
            try:
                target.unlink()
                removed += 1
            except OSError:
                pass
    manifest = override_dir / _MANIFEST
    if manifest.exists():
        with contextlib.suppress(OSError):
            manifest.unlink()
    return removed


def _record_manifest(override_dir: Path, names: list[str]) -> None:
    """Append the written filenames to the override manifest, for later removal."""
    path = override_dir / _MANIFEST
    existing: list[str] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text()).get("files", [])
        except (OSError, ValueError):
            existing = []
    merged = sorted(set(existing) | set(names))
    path.write_text(json.dumps({"files": merged}, indent=1))
