"""Tell the user what adding a given PRC feat will actually do.

PRC does not read most of its abilities off the stored feat list — it builds them
from its own scripts and keeps the result in a hidden skin item, event-hook
registrations and a persistent spellbook. So adding a feat in the editor *lists*
it, but whether its **effect** works depends on how PRC implements that feat.

This classifies a feat from data any PRC install already carries — ``feat.2da``
plus the per-class feat and spell tables — so no source download or ``.ncs``
decompilation is needed. Four outcomes, matching ``docs/prc_abilities.md``:

* **spellbook** — the ability is cast through a class spellbook (its feat id is a
  ``FeatID`` in some ``cls_spell_*``). Built at level-up from the class spell
  list into PRC's own store; a feat-add can't grant it.
* **class** — a class feature (its feat id is a ``FeatIndex`` in some
  ``cls_feat_*``). Keyed on the class, so the feat alone is not enough.
* **base** — a base-game feat (in the base ``feat.2da`` under the haks). The
  engine handles it, so it edits cleanly; a class listing it as a *selectable*
  bonus feat does not make it class-gated.
* **standalone** — a PRC feat neither of the above. PRC reads it from the feat
  list: a passive one applies at once; an on-hit/on-equip one after PRC
  re-evaluates the character (re-enter the module + re-equip).
* **unknown** — the id is not in ``feat.2da`` of the current install.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class _Reader(Protocol):
    def read_2da(self, name: str) -> dict[int, dict[str, str]] | None: ...


#: PRC's general feat/effect handlers. A feat whose constant is referenced here is
#: driven by the machinery that reads ``GetHasFeat`` on re-evaluation (``prc_feats``:
#: on-hit / on-equip hooks) or at effect time (``prc_effect_inc``: passive checks) —
#: so it works from the feat list even when a class also grants it. This is what
#: separates "granted by a class" from "gated on a class".
_HANDLER_SCRIPTS = {"onhit": "prc_feats", "passive": "prc_effect_inc"}
_FEAT_CONST_SCRIPT = "prc_feat_const"
_FEAT_CONST_RE = re.compile(r"const\s+int\s+(FEAT_\w+)\s*=\s*(\d+)\s*;")

#: Base NWN:EE ``feat.2da`` is rows 0-1115; PRC appends its feats above that. Used
#: only when the base table can't be read outright (no game folder), so a class's
#: *selectable* base feats aren't mistaken for class-gated PRC features.
_BASE_FEAT_COUNT = 1116


@dataclass(frozen=True)
class FeatAdvice:
    """The verdict for one feat id."""

    feat_id: int
    label: str
    bucket: str  # "spellbook" | "class" | "standalone" | "unknown"
    class_name: str  # for spellbook / class buckets, else ""
    active: bool  # has a SpellID -> shows in the radial as an activated ability
    headline: str
    direction: str


def _col(row: dict[str, str], name: str) -> str:
    """Case-insensitive column read (2DA headers vary in case across content)."""
    for key, value in row.items():
        if key.lower() == name.lower():
            return value
    return ""


def _is_set(value: str) -> bool:
    return value not in ("", "****")


def _to_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class PrcAdvisor:
    """Classify PRC feats for the add-feat flow, from the installed 2das.

    The class→feat/spell membership is scanned once (it reads every class's
    ``cls_feat_*`` and, for casters, ``cls_spell_*``) and cached on the instance,
    so hold one advisor per install rather than rebuilding it per feat.
    """

    def __init__(self, reader: _Reader) -> None:
        self._reader = reader
        self._feats: dict[int, dict[str, str]] | None = None
        self._class_feats: dict[int, str] | None = None
        self._spellbook_feats: dict[int, str] | None = None
        self._constants: dict[int, str] | None = None
        self._handler_text: dict[str, str] | None = None
        self._base_feats: set[int] | None = None
        #: Guards the one-time membership scan so a background prewarm and a
        #: foreground advise cannot both build it at once (the second waits).
        self._membership_lock = threading.Lock()

    def _feat_table(self) -> dict[int, dict[str, str]]:
        if self._feats is None:
            self._feats = self._reader.read_2da("feat") or {}
        return self._feats

    # -- optional source refinement (present when the haks carry .nss) ------ #
    def _read_script(self, name: str) -> str:
        reader = getattr(self._reader, "read_script", None)
        return (reader(name) or "") if callable(reader) else ""

    def _feat_constants(self) -> dict[int, str]:
        """``feat id -> FEAT_* constant`` from ``prc_feat_const.nss`` (or empty)."""
        if self._constants is None:
            self._constants = {}
            for match in _FEAT_CONST_RE.finditer(self._read_script(_FEAT_CONST_SCRIPT)):
                self._constants[int(match.group(2))] = match.group(1)
        return self._constants

    def _handlers(self) -> dict[str, str]:
        if self._handler_text is None:
            self._handler_text = {
                kind: self._read_script(script)
                for kind, script in _HANDLER_SCRIPTS.items()
            }
        return self._handler_text

    def _is_base_feat(self, feat_id: int) -> bool:
        """Whether the id is a base-game feat (engine-handled, edits cleanly).

        Reads the base ``feat.2da`` from under the haks when the reader can; a
        class's *selectable* base feats (Alertness, weapon proficiencies …) live in
        its ``cls_feat_*`` too, and must not be read as class-gated PRC features.
        """
        if self._base_feats is None:
            reader = getattr(self._reader, "read_base_2da", None)
            table = reader("feat") if callable(reader) else None
            self._base_feats = set(table) if table else set()
        if self._base_feats:
            return feat_id in self._base_feats
        return feat_id < _BASE_FEAT_COUNT

    def _feat_driven(self, feat_id: int) -> str | None:
        """"onhit" / "passive" if the general machinery reads this feat, else None.

        Such a feat works from the feat list — the class that grants it (if any) is
        incidental. Falls back to ``None`` when the source is not in the haks, so
        the classification degrades to the 2da-only buckets rather than misfiring.
        """
        name = self._feat_constants().get(feat_id)
        if not name:
            return None
        pattern = re.compile(r"\b" + re.escape(name) + r"\b")
        for kind, text in self._handlers().items():
            if text and pattern.search(text):
                return kind
        return None

    def _build_membership(self) -> None:
        if self._class_feats is not None:
            return
        with self._membership_lock:
            if self._class_feats is not None:  # built while we waited for the lock
                return
            self._scan_membership()

    def _scan_membership(self) -> None:
        class_feats: dict[int, str] = {}
        spellbook_feats: dict[int, str] = {}
        for row in (self._reader.read_2da("classes") or {}).values():
            label = _col(row, "Label").replace("_", " ")
            feats_table = _col(row, "FeatsTable")
            if not _is_set(feats_table):
                continue
            # Feats this class grants outright (the "class" bucket).
            for frow in (self._reader.read_2da(feats_table.lower()) or {}).values():
                fid = _to_int(_col(frow, "FeatIndex"))
                if fid is not None:
                    class_feats.setdefault(fid, label)
            # Its spellbook, by PRC's CLS_FEAT_x -> cls_spell_x naming (the
            # spellbook only exists for casters; a missing table just returns
            # nothing). Casting SLAs are the FeatID column of that table.
            if feats_table.upper().startswith("CLS_FEAT_"):
                spell_table = "cls_spell_" + feats_table[len("CLS_FEAT_") :].lower()
                for srow in (self._reader.read_2da(spell_table) or {}).values():
                    fid = _to_int(_col(srow, "FeatID"))
                    if fid is not None:
                        spellbook_feats.setdefault(fid, label)
        self._class_feats = class_feats
        self._spellbook_feats = spellbook_feats

    # -- membership cache (the one expensive part) -------------------------- #
    def membership_ready(self) -> bool:
        """Whether the class/spellbook index is built or seeded (no scan needed)."""
        return self._class_feats is not None

    def membership_index(self) -> dict[str, dict[str, str]]:
        """Force + return the class/spellbook membership as a JSON-able dict."""
        self._build_membership()
        return {
            "class": {str(k): v for k, v in (self._class_feats or {}).items()},
            "spellbook": {str(k): v for k, v in (self._spellbook_feats or {}).items()},
        }

    def seed_membership(self, index: dict[str, dict[str, str]]) -> None:
        """Populate the membership from a cached index, skipping the per-class scan."""
        self._class_feats = {int(k): v for k, v in (index.get("class") or {}).items()}
        self._spellbook_feats = {
            int(k): v for k, v in (index.get("spellbook") or {}).items()
        }

    def advise(self, feat_id: int) -> FeatAdvice:
        row = self._feat_table().get(feat_id)
        if row is None:
            return FeatAdvice(
                feat_id, "", "unknown", "", False,
                "Not in this install's feat table.",
                "The id is not in feat.2da for the haks this save uses, so nothing "
                "can be said about it.",
            )
        label = _col(row, "LABEL").replace("_", " ")
        active = _is_set(_col(row, "SPELLID"))

        if self._is_base_feat(feat_id):
            return FeatAdvice(
                feat_id, label, "base", "", active,
                "Base-game feat — the engine handles it.",
                "Edits cleanly and takes effect when the save loads; PRC is not "
                "involved.",
            )
        # Feat-driven (read by the general machinery via GetHasFeat) beats
        # class-granted: a class may list the feat, but it still works from the
        # feat list, so it is not gated on the class. Checked *before* the class
        # membership scan because it is cheap (a source grep) and settles most
        # standalone feats without the expensive per-class table walk.
        driven = self._feat_driven(feat_id)
        if driven == "passive":
            return FeatAdvice(
                feat_id, label, "standalone", "", active,
                "Passive feat — PRC reads it live.",
                "Works from your feat list; the effect applies as soon as the save "
                "loads, nothing else to do.",
            )
        if driven == "onhit":
            return FeatAdvice(
                feat_id, label, "standalone", "", active,
                "On-hit / on-equip feat wired by PRC on re-evaluation.",
                "Works from your feat list, but PRC wires the effect when it "
                "re-evaluates you — re-enter the module and re-equip your weapon.",
            )

        # Only now, for feats that are neither base nor feat-driven, pay for the
        # per-class membership scan that separates class features from spellbook
        # abilities.
        self._build_membership()

        if feat_id in (self._spellbook_feats or {}):
            cls = self._spellbook_feats[feat_id]
            return FeatAdvice(
                feat_id, label, "spellbook", cls, active,
                f"Spellbook ability, cast through the {cls} spellbook.",
                "A feat-add can't grant this. PRC builds the spellbook at level-up "
                "from the class's spell list, into its own persistent store — the "
                f"feat list never populates it. Gain it in-game via the {cls} class.",
            )

        if feat_id in (self._class_feats or {}):
            cls = self._class_feats[feat_id]
            return FeatAdvice(
                feat_id, label, "class", cls, active,
                f"Class feature of {cls}.",
                f"Its effect is keyed on the {cls} class, not the feat alone. Add "
                f"the {cls} class levels too, then re-enter the module so PRC "
                "re-evaluates you.",
            )
        return FeatAdvice(
            feat_id, label, "standalone", "", active,
            "Standalone feat — not a class feature or a spellbook ability.",
            "PRC (or the base game) reads this from your feat list. A passive feat "
            "applies at once; a PRC on-hit or on-equip feat is wired when PRC next "
            "re-evaluates you, so re-enter the module and re-equip your weapon.",
        )


# -- persistent index cache (the membership scan is one-time per hak set) ----- #
def hak_fingerprint(haks) -> str:
    """A short stable id for a hak set: name + size + mtime of each file.

    The membership index depends only on the installed haks, so it can be cached
    on disk and reused until a hak changes — at which point the fingerprint, and
    the cache key, changes with it.
    """
    parts: list[str] = []
    for hak in haks:
        path = Path(hak)
        try:
            stat = path.stat()
            parts.append(f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}")
        except OSError:
            parts.append(f"{path.name}:?")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def load_membership_index(path) -> dict | None:
    """Read a cached index, or ``None`` if it is absent or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_membership_index(path, index: dict) -> None:
    """Write the index to ``path`` (best-effort; a cache miss is not an error)."""
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(index), encoding="utf-8")
    except OSError:
        pass
