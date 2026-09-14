"""Add a generic "Recompute PRC Features" widget to a character.

A small companion to :mod:`nwnsaveeditor.appearance_fix` and
:mod:`nwnsaveeditor.orphan_powers`. It gives a PRC character a one-click way to make
PRC re-derive its *managed* state — feats, the invisible skin, class scripts and
applied templates — without the level-drop of ``/relevel``. Useful after any save
edit that PRC would normally only reconcile at level-up or on a fresh module load.

No class, template, or build assumptions: the item's tag-based script just calls
``EvalPRCFeats`` (in the module-rebuild context) and re-equips the held weapons so
on-hit / on-equip class powers re-wire. ``/relevel`` (twice, in chat) remains the
last resort for state PRC only builds at level-up.

Delivery: the compiled ``prc_recompute.ncs`` (a new resref, overriding nothing) is
bundled into one shared hak added to the save's ``Mod_HakList`` so the tag script
resolves in-game; the widget item is a per-save inventory edit the caller keeps by
writing the save with ``editor.save_as``. Qt-free.

The compiled script is shipped prebuilt under ``data/prc_recompute/`` (see its ``.nss``
source); this module only installs it — the bytes are the exact output of the PRC
toolchain for that source, so do not hand-edit them.
"""
from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data" / "prc_recompute"
_MANIFEST = "vk_prc_recompute.json"
_NCS_RESTYPE = 2010  # compiled NWScript
#: the shared widget hak, referenced from each save's Mod_HakList (<=16 chars).
HAK_NAME = "vkrecomp"


@dataclass
class RecomputeSummary:
    widget_added: bool = False   #: the recompute widget was added to inventory
    hak: str = ""                #: the widget hak file written (if any)
    notes: list[str] = field(default_factory=list)

    @property
    def did_anything(self) -> bool:
        return self.widget_added


def script_bytes() -> bytes | None:
    """The bundled compiled widget script, or ``None`` if the bundle is missing."""
    try:
        return (_DATA / "prc_recompute.ncs").read_bytes()
    except OSError:
        return None


def has_widget(player_struct) -> bool:
    """Whether the character already carries a recompute widget."""
    from nwnfile.formats.gff import GffType

    carried = player_struct.fields.get("ItemList")
    if carried is None or carried.type != GffType.LIST:
        return False
    return any((it.get("Tag") or "") == "prc_recompute" for it in carried.value.structs)


def add_widget(
    editor, player_struct, hak_dir: Path, *, hak_name: str = HAK_NAME,
) -> RecomputeSummary:
    """Bundle the widget script into a hak and add the widget item to inventory.

    Writes ``hak_dir/<hak_name>.hak`` (holding ``prc_recompute.ncs``), adds it to the
    save's ``Mod_HakList`` and stages the widget item. Idempotent: a character that
    already carries the widget is not given a second one. The caller writes the new
    save with ``editor.save_as`` afterwards. Returns a summary.
    """
    from nwnfile.formats.erf_writer import build_hak

    summary = RecomputeSummary()
    blob = script_bytes()
    if blob is None:
        summary.notes.append("Recompute widget unavailable: prc_recompute.ncs is not bundled.")
        return summary

    if has_widget(player_struct):
        summary.notes.append("Recompute widget already in inventory — not added again.")
    else:
        try:
            editor.add_recompute_item()
            summary.widget_added = True
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the caller
            summary.notes.append(f"Recompute widget not added: {exc}")
            return summary

    try:
        hak_dir.mkdir(parents=True, exist_ok=True)
        (hak_dir / f"{hak_name}.hak").write_bytes(
            build_hak([("prc_recompute", _NCS_RESTYPE, blob)]))
    except OSError as exc:
        summary.notes.append(f"Could not write the widget hak: {exc}")
        return summary
    # A new resref overrides nothing, so a normal (bottom) hak entry is enough for
    # the tag script to resolve — no top-priority slot needed here.
    editor.add_module_hak(hak_name, where="PRC recompute widget")
    _record_manifest(hak_dir, [f"{hak_name}.hak"])
    summary.hak = f"{hak_name}.hak"
    return summary


def installed_files(hak_dir: Path) -> list[str]:
    """The widget hak file(s) a previous run wrote, or ``[]``."""
    path = hak_dir / _MANIFEST
    if not path.exists():
        return []
    try:
        return list(json.loads(path.read_text()).get("files", []))
    except (OSError, ValueError):
        return []


def remove_installed(hak_dir: Path) -> int:
    """Delete the widget hak file(s) this module wrote and the manifest. Returns how
    many were removed.

    Caveat: NWN refuses to load a save whose ``Mod_HakList`` references a missing hak,
    so only delete it once no save still lists it. The hak is shared, harmless
    infrastructure; leaving it in place is usually correct.
    """
    removed = 0
    for name in installed_files(hak_dir):
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
    path = hak_dir / _MANIFEST
    existing: list[str] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text()).get("files", [])
        except (OSError, ValueError):
            existing = []
    merged = sorted(set(existing) | set(names))
    path.write_text(json.dumps({"files": merged}, indent=1))
