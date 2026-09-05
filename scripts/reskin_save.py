#!/usr/bin/env python3
"""Re-skin a character's items to appearances that render in the module you are
playing — a reproducible, save-safe alternative to dumping haks into ``override``.

Why this exists
---------------
An item's appearance is stored on the item as *numbers* (``ModelPart1..3`` for
simple/composite items, ``ArmorPart_*`` for armour). Those numbers are looked up
as model/icon files in whatever haks the current module loads. A character that
carries gear made for one content pack (e.g. CEP2 + Aielund/Sands-of-Fate) into a
module built on another (e.g. CEP3 Swordflight) shows default/blank art, because
the numbered files it points at are absent or different there.

There is **no faithful automatic CEP2<->CEP3 converter** — CEP3 re-authored the
assets (verified: same-named files are ~93% different bytes) and ships no mapping,
so "the CEP2 look under CEP3" cannot be derived. What *is* reproducible is this:
rewrite each affected item's appearance numbers to a chosen target, and write a
brand-new save (byte-faithful, original untouched) via the tested SaveEditor.

The RESKIN table below is the mechanism. It is keyed by item ``TemplateResRef``
and lists the appearance fields to set. Edit the numbers to taste and re-run — the
originals are always read fresh from the source save, so it is idempotent.

Targets
-------
The seeded values are **vanilla base-game appearances** (low numbers present in
*every* content pack — base, CEP2 and CEP3), so the gear renders correctly in ALL
your modules, not just one. That side-steps the CEP2-vs-CEP3 problem entirely; the
cost is that the items look like plain base items rather than their custom art.
Swap in CEP3-specific numbers if you only care about the current module (but then
they will look wrong back in the CEP2 campaigns).

Usage
-----
    python scripts/reskin_save.py "<save folder>"            # dry-run report
    python scripts/reskin_save.py "<save folder>" --apply    # write a new save
    python scripts/reskin_save.py "<save folder>" --apply --out "<dest folder>"

``ArmorPart_*`` edits automatically also set the item's mirrored ``xArmorPart_*``
field (the game keeps the two in step).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the package importable when run straight from the repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nwnsaveeditor.save_editor import SaveEditor  # noqa: E402
from nwnsaveeditor.save_game import SaveGame  # noqa: E402

#: resref -> {appearance field: new value}. This is the editable mechanism.
#: Seeded with conservative vanilla-safe values for the pieces that carry custom
#: (CEP2/Aielund/SoF) appearance numbers. Comment a line out to leave an item
#: alone; add a resref to re-skin another item.
RESKIN: dict[str, dict[str, int]] = {
    # --- weapons: plain base-game rapier (parts 1/1/1) ---
    "godwind": {"ModelPart1": 1, "ModelPart2": 1, "ModelPart3": 1},
    "quicksilverrapie": {"ModelPart1": 1, "ModelPart2": 1, "ModelPart3": 1},
    # --- helmet / simple items: base variant 1 ---
    "arhe007": {"ModelPart1": 1},          # helmet
    "it_mglove018": {"ModelPart1": 1},     # gloves
    "cloakof": {"ModelPart1": 1},          # cloak
    "zep_necro_rin004": {"ModelPart1": 1},  # ring (custom 130)
    "it_mneck038": {"ModelPart1": 1},      # amulet (custom 53)
    # --- boots (composite) ---
    "it_mboots023": {"ModelPart1": 1, "ModelPart2": 1, "ModelPart3": 1},
    # --- robe (armour): reset only the custom-numbered parts to base ---
    "robesofsesustris": {
        "ArmorPart_Robe": 1,
        "ArmorPart_LBicep": 1, "ArmorPart_RBicep": 1,
        "ArmorPart_LFArm": 1, "ArmorPart_RFArm": 1,
    },
}

_ARMOR_MIRROR = {  # ArmorPart_* -> its truncated x-mirror field (game keeps synced)
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

_PLAYER = ("Mod_PlayerList", 0)


def _iter_items(editor: SaveEditor):
    """Yield (list_label, index, struct) for every equipped and carried item."""
    root = editor.raw_tree("module.ifo").root
    player = root.fields["Mod_PlayerList"].value.structs[0]
    for label in ("Equip_ItemList", "ItemList"):
        field = player.fields.get(label)
        if field is None:
            continue
        for i, item in enumerate(field.value.structs):
            yield label, i, item


def reskin(editor: SaveEditor) -> list[str]:
    """Apply RESKIN to the open save; return a human-readable change log."""
    log: list[str] = []
    for label, i, item in _iter_items(editor):
        resref = item.get("TemplateResRef")
        plan = RESKIN.get(resref)
        if not plan:
            continue
        for field_name, new_value in plan.items():
            if field_name not in item.fields:
                log.append(f"  ! {resref}: no field {field_name}; skipped")
                continue
            old = item.get(field_name)
            if old == new_value:
                continue
            path = (_PLAYER, (label, i), (field_name, None))
            editor.set_raw_field("module.ifo", path, new_value,
                                 where=f"reskin {resref}")
            log.append(f"  {resref}.{field_name}: {old} -> {new_value}")
            mirror = _ARMOR_MIRROR.get(field_name)
            if mirror and mirror in item.fields:
                mpath = (_PLAYER, (label, i), (mirror, None))
                editor.set_raw_field("module.ifo", mpath, new_value,
                                     where=f"reskin {resref}")
                log.append(f"  {resref}.{mirror}: (mirror) -> {new_value}")
    return log


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-skin carried/equipped items in a save.")
    ap.add_argument("save", type=Path, help="the save folder to read (never modified)")
    ap.add_argument("--apply", action="store_true", help="write a new save (else dry-run)")
    ap.add_argument("--out", type=Path, default=None, help="destination folder for --apply")
    args = ap.parse_args()

    if not args.save.is_dir():
        ap.error(f"not a folder: {args.save}")

    editor = SaveEditor(SaveGame(folder=args.save))
    log = reskin(editor)

    if not log:
        print("No items matched RESKIN — nothing to change.")
        return 0
    print(f"Planned {'and applied ' if args.apply else ''}changes:")
    print("\n".join(log))

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write a new save.")
        return 0

    dest = args.out or args.save.parent / f"{args.save.name} (reskinned)"
    saved = editor.save_as(dest)
    print(f"\nWrote re-skinned save to: {saved.folder}")
    print("The original save was not touched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
