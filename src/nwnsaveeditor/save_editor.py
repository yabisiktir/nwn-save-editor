"""Edit a save game and write it back as a **new** save (read-only on the original).

The first, safest edit target: **store settings** (a merchant's pricing). A store
lives in its area's ``<area>.git`` (``StoreList``); this loads that resource's GFF
tree, mutates the store's scalar fields in place, and rewrites the ``.sav`` with the
edited ``.git`` swapped in — via the byte-faithful :mod:`vaultkeeper.core.formats.gff`
writer + :mod:`vaultkeeper.core.formats.erf_writer`, so everything untouched is
preserved exactly.

Safety model:

* **Never touch the original.** :meth:`SaveEditor.save_as` writes a brand-new save
  folder; the source save is the backup.
* **Verify after write.** The new ``.sav`` is re-read and each edited resource's
  bytes are checked against what was written.
"""

from __future__ import annotations

import functools
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vaultkeeper.core.formats.bic_reader import ItemProperty
from vaultkeeper.core.formats.erf_reader import ErfReader
from vaultkeeper.core.formats.erf_writer import rewrite_erf
from vaultkeeper.core.formats.gff import (
    Gff,
    GffField,
    GffList,
    GffStruct,
    GffType,
    LocString,
    read_gff,
    write_gff,
)
from vaultkeeper.game.save_game import SaveGame

_GIT_RESTYPE = 2023
_IFO_RESTYPE = 2014
_PLAYER_LIST = "Mod_PlayerList"


class SaveEditError(Exception):
    """A save could not be read, edited or written."""


@dataclass
class EditableProperty:
    """A magical property on a player item, with its index for path-based editing."""

    index: int  #: position in the item's PropertiesList
    prop: ItemProperty  #: for describing/naming it (game.item_properties)
    uses_per_day: int  #: 255 = unlimited


@dataclass
class EditableSkill:
    """A player-character skill: its id, name and current rank."""

    index: int
    name: str
    rank: int


@dataclass
class CharacterField:
    """A top-level editable character field (gold, an ability, alignment, name …)."""

    field: str  #: the GFF field name (e.g. "Gold", "Str", "FirstName")
    display: str
    kind: str  #: "int" | "name" | "race" | "appearance" | "resref"
    value: object  #: current value (int, or the name text)
    minimum: int = 0
    maximum: int = 0


#: editable scalar character fields: (GFF field, display, min, max).
_CHARACTER_FIELDS: tuple[tuple[str, str, int, int], ...] = (
    ("Gold", "Gold", 0, 2_000_000_000),
    ("Experience", "Experience (XP)", 0, 2_000_000_000),
    ("Str", "Strength", 1, 100),
    ("Dex", "Dexterity", 1, 100),
    ("Con", "Constitution", 1, 100),
    ("Int", "Intelligence", 1, 100),
    ("Wis", "Wisdom", 1, 100),
    ("Cha", "Charisma", 1, 100),
    ("GoodEvil", "Good–Evil (100 = Good)", 0, 100),
    ("LawfulChaotic", "Lawful–Chaotic (100 = Lawful)", 0, 100),
    ("Age", "Age", 0, 100_000),
    ("CurrentHitPoints", "Current HP", 0, 32_000),
    # The stored *base* saves. The engine adds ability modifiers and gear on top,
    # so these are the sources, not the totals shown on the character sheet.
    ("FortSaveThrow", "Base Fortitude save", -128, 127),
    ("RefSaveThrow", "Base Reflex save", -128, 127),
    ("WillSaveThrow", "Base Will save", -128, 127),
)
#: editable name fields (CExoLocString).
_CHARACTER_NAMES: tuple[tuple[str, str], ...] = (
    ("FirstName", "First name"), ("LastName", "Last name"),
)


@dataclass
class EditableItem:
    """A player-character item located by its GFF path, for property editing."""

    path: tuple  #: ((field_label, index), …) from the player struct, e.g. (("Equip_ItemList", 0),)
    slot: int | None  #: equipment slot bit if equipped, else None (carried)
    name: str
    name_strref: int
    resref: str
    base_item: int
    model_part: int
    properties: list[EditableProperty]


@dataclass
class PendingChange:
    """One staged edit, for the viewer's pending-changes list + dirty markers."""

    kind: str  #: e.g. "store" — which editor produced it
    key: tuple  #: identifies the edited object (e.g. ``(area_resref, store_index)``)
    where: str  #: human label, e.g. "Nature Store — Beorunna's Well"
    summary: str  #: what changed, e.g. "buy markup 200%→120%; black market off→on"


def _fmt_pct(value: int) -> str:
    return f"{value}%"


def _fmt_gold(value: int) -> str:
    return "unlimited" if value < 0 else str(value)


def _fmt_bool(value: int) -> str:
    return "on" if value else "off"


def _fmt_uses(value: int) -> str:
    return "unlimited" if value >= 255 else str(value)


def _make_property_struct(
    property_name: int, subtype: int, cost_table: int, cost_value: int,
    param1: int | None = None,
) -> GffStruct:
    """A full item-property struct, matching the game's field layout.

    ``Param1`` is 255 — the game's "no parameter" — unless the property defines
    one, in which case it carries the chosen row from its ``Param1ResRef`` table.
    """
    return GffStruct(struct_type=0, fields={
        "PropertyName": GffField(GffType.WORD, property_name),
        "Subtype": GffField(GffType.WORD, subtype),
        "CostTable": GffField(GffType.BYTE, cost_table),
        "CostValue": GffField(GffType.WORD, cost_value),
        "Param1": GffField(GffType.BYTE, 255 if param1 is None else int(param1)),
        "Param1Value": GffField(GffType.BYTE, 0),
        "ChanceAppear": GffField(GffType.BYTE, 100),
        "UsesPerDay": GffField(GffType.BYTE, 255),
        "Useable": GffField(GffType.BYTE, 1),
        "CustomTag": GffField(GffType.CEXOSTRING, ""),
    })


#: the "empty" value for each simple GFF type, used to seed a new list entry.
#: The mutable types (list, locstring) are absent on purpose — they must be built
#: fresh per field rather than shared out of a dict.
_ZERO_VALUE: dict[GffType, object] = {
    GffType.BYTE: 0, GffType.CHAR: 0, GffType.WORD: 0, GffType.SHORT: 0,
    GffType.DWORD: 0, GffType.INT: 0, GffType.DWORD64: 0, GffType.INT64: 0,
    GffType.FLOAT: 0.0, GffType.DOUBLE: 0.0,
    GffType.CEXOSTRING: "", GffType.CRESREF: "", GffType.VOID: b"",
}


def _zero_like(entry: GffField) -> object:
    """An empty value of ``entry``'s own type (recursing into a nested struct)."""
    if entry.type == GffType.STRUCT:
        return _seeded_from(entry.value)  # a child struct keeps its shape too
    if entry.type == GffType.LIST:
        return GffList()  # an empty list is always valid; inventing entries is not
    if entry.type == GffType.CEXOLOCSTRING:
        return LocString()
    return _ZERO_VALUE[entry.type]


def _seeded_from(template: GffStruct) -> GffStruct:
    """A new struct with ``template``'s field set and GFF types, values zeroed.

    A struct with no fields is not a usable game object — the engine reads fields
    by name — so even a "blank" new list entry has to carry the shape its siblings
    have. Structs in a GFF list are not required to be homogeneous, so one sibling
    is the model rather than the union of them all.
    """
    seeded = GffStruct(struct_type=template.struct_type)
    for label, entry in template.fields.items():
        seeded.fields[label] = GffField(entry.type, _zero_like(entry))
    return seeded


def _numbered_by_index(structs: list[GffStruct]) -> bool:
    """Whether a list stores each entry's position in its ``struct_type``.

    Some lists do (an item's ``PropertiesList``); in others the struct type is a
    tag the game reads back — an equipment slot bit, a spell-list id. Renumbering
    the first kind is required and renumbering the second corrupts it, so only
    treat a list as numbered when it already unambiguously looks that way. Two
    entries is the floor: a lone ``struct_type == 0`` entry is equally consistent
    with a list whose tag just happens to be 0.
    """
    return len(structs) >= 2 and all(s.struct_type == i for i, s in enumerate(structs))


def _render_raw_path(path: tuple) -> str:
    """``Mod_Area_list[3]/Tag`` — the Raw Data screen's display form of a GFF path."""
    return "/".join(label if index is None else f"{label}[{index}]" for label, index in path)


def _shift_path(path: tuple, list_path: tuple, removed: int) -> tuple | None:
    """Re-point ``path`` after entry ``removed`` was deleted from ``list_path``.

    ``None`` means ``path`` pointed *at or into* the deleted entry and no longer
    names anything.
    """
    depth = len(list_path)
    if len(path) < depth:
        return path
    label, index = path[depth - 1]
    # Everything above the list, and the list's own label, must match — otherwise
    # this path is somewhere else entirely and the removal cannot have moved it.
    if path[:depth - 1] != list_path[:depth - 1] or label != list_path[depth - 1][0]:
        return path
    if index is None or index < removed:
        return path
    if index == removed:
        return None
    return path[:depth - 1] + ((label, index - 1),) + path[depth:]


def _unshift_path(path: tuple, list_path: tuple, removed: int) -> tuple:
    """:func:`_shift_path` backwards — the path this one was renumbered *from*."""
    depth = len(list_path)
    if len(path) < depth:
        return path
    label, index = path[depth - 1]
    if path[:depth - 1] != list_path[:depth - 1] or label != list_path[depth - 1][0]:
        return path
    if index is None or index < removed:
        return path
    return path[:depth - 1] + ((label, index + 1),) + path[depth:]


def _identity(change: PendingChange | None) -> tuple | None:
    """What makes a staged change *the same* change across a replay.

    Its key and label move when a list removal renumbers entries (see
    :meth:`SaveEditor._shift_raw_paths`), and that move must not read as "this
    command altered the change" — otherwise discarding a field edit would discard
    the removal that shifted it too.
    """
    return None if change is None else (change.kind, change.summary)


def _repointed(change: PendingChange, key: tuple) -> PendingChange:
    """A copy of ``change`` re-keyed to a shifted path, its label following along."""
    where, old = change.where, _render_raw_path(change.key[1])
    if where.endswith(old):  # the raw screen's label ends with the rendered path
        where = where[: -len(old)] + _render_raw_path(key[1])
    return PendingChange(kind=change.kind, key=key, where=where, summary=change.summary)


#: store edit key -> (GFF label, "int"|"bool", display name, value formatter).
_STORE_FIELDS: dict[str, tuple[str, str, str, object]] = {
    "markup": ("MarkUp", "int", "buy markup", _fmt_pct),
    "markdown": ("MarkDown", "int", "sell-back markdown", _fmt_pct),
    "store_gold": ("StoreGold", "int", "store gold", _fmt_gold),
    "identify_price": ("IdentifyPrice", "int", "identify price",
                       lambda v: "none" if v < 0 else str(v)),
    "max_buy_price": ("MaxBuyPrice", "int", "max buy price",
                      lambda v: "no limit" if v < 0 else str(v)),
    "black_market": ("BlackMarket", "bool", "black market", _fmt_bool),
}


@dataclass
class SpellList:
    """One spell list on a class — a KnownList/MemorizedList at a spell level."""

    class_index: int
    list_field: str  #: e.g. "KnownList2" — the GFF field on the class struct
    kind: str  #: "Known" (spontaneous) | "Memorized" (prepared)
    level: int
    spells: list[tuple[int, str]]  #: (spell id, name)


@dataclass
class ClassSpellbook:
    """A caster class's spell lists (only classes that have a spellbook)."""

    class_index: int
    class_id: int
    class_name: str
    is_base: bool  #: PRC classes route casting through PRC scripts — warn on edits
    lists: list[SpellList]


def _free_backup(backup_dir: Path, save_name: str) -> Path:
    """A backup folder that does not exist yet.

    The timestamp is only second-resolution, so two overwrites in the same second
    would otherwise target the same path — and ``shutil.move`` onto an existing
    directory moves *into* it, nesting one backup inside another instead of
    keeping both.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = backup_dir / f"{stamp} - {save_name}"
    suffix = 2
    while candidate.exists():
        candidate = backup_dir / f"{stamp}.{suffix} - {save_name}"
        suffix += 1
    return candidate


@dataclass
class _Command:
    """One recorded edit, replayable from a clean state.

    Undo is built by replaying the log rather than by inverting each edit: a
    per-kind inverse would have to know how to un-remove an item property or
    un-clone an item, and every new edit type would need one. Replaying the
    remaining commands is uniformly correct and needs nothing per kind.
    """

    method: str
    args: tuple
    kwargs: dict
    #: edits sharing a coalesce key collapse into one undo step, so dragging a
    #: stepper does not become twenty of them.
    coalesce: tuple | None = None


def _removal(command: _Command) -> tuple[str, tuple, int] | None:
    """``(target, list path, index)`` if ``command`` is a raw list removal.

    Read off the recorded call: ``remove_raw_struct`` takes those three
    positional-only, so a recorded removal is always in exactly this shape.
    """
    if command.method != "remove_raw_struct":
        return None
    target, path, index = command.args
    return target, tuple(path), index


def _records(coalesce=None):
    """Mark a mutator so its call is appended to the undo log.

    ``coalesce`` maps the call's arguments to a key; consecutive calls with the
    same key replace the previous log entry instead of appending.
    """

    def decorate(method):
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            result = method(self, *args, **kwargs)
            if self._recording:
                key = coalesce(*args, **kwargs) if coalesce is not None else None
                self._record(_Command(method.__name__, args, dict(kwargs), key))
            return result

        return wrapper

    return decorate


class SaveEditor:
    """Accumulates edits to a save's resources and writes them to a new save.

    Edits are staged in memory (the source is never modified); :meth:`save_as`
    materialises them into a new save folder and verifies the result.

    Every mutator is recorded in an undo log, so :meth:`undo`, :meth:`redo` and
    :meth:`discard_change` work for all edit kinds without per-kind inverses.
    """

    #: editable store field names (the public keyword args of set_store_fields).
    STORE_FIELDS = tuple(_STORE_FIELDS)

    def __init__(self, save: SaveGame) -> None:
        if save.sav_path is None:
            raise SaveEditError("save has no .sav file")
        self._save = save
        self._reader = ErfReader()
        self._areas: dict[str, Gff] = {}  # area resref (lower) -> loaded .git tree
        #: original store field values, per (area, index), captured on first touch.
        self._store_originals: dict[tuple[str, int], dict[str, object]] = {}
        #: staged changes keyed by (kind, key) so re-editing an object replaces it.
        self._changes: dict[tuple[str, tuple], PendingChange] = {}
        #: the player character's module.ifo tree + its player.bic mirror (lazy).
        self._module: Gff | None = None
        self._bic: Gff | None = None
        self._bic_loaded = False
        self._char_dirty = False
        #: original editable-field values per (item_path, prop_index), first touch.
        self._prop_originals: dict[tuple[tuple, int], dict[str, object]] = {}
        self._max_obj_id: int | None = None  # for handing out fresh item ObjectIds
        self._add_seq = 0  # tells apart staged changes whose object no longer exists
        #: original skill rank per skill index, captured on first touch.
        self._skill_originals: dict[int, int] = {}
        #: original value per touched top-level character field.
        self._char_field_originals: dict[str, object] = {}
        #: the character's feat ids at load, captured on the first feat op.
        self._feat_originals: set[int] | None = None
        #: original spell ids per (class_index, list_field), first spell op.
        self._spell_originals: dict[tuple[int, str], set[int]] = {}
        #: applied edits, in order — the undo log.
        self._log: list[_Command] = []
        #: edits taken off the log by undo. The design keeps these visible in the
        #: ledger, struck through and excluded from the write count.
        self._undone: list[_Command] = []
        #: the PendingChanges each undo removed, parallel to ``_undone``.
        self._undone_display: list[list[PendingChange]] = []
        self._recording = True  # False while replaying, so replay doesn't re-log
        #: original value per raw-edited (target, path).
        self._raw_originals: dict[tuple, object] = {}
        #: decoded trees for raw targets that are neither the character nor an area,
        #: keyed (resref, extension) — cached because a raw edit has to survive
        #: until :meth:`save_as`, and because the screen re-reads on every refresh.
        self._raw_trees: dict[tuple[str, str], Gff | None] = {}
        self._raw_types: dict[tuple[str, str], int] = {}  # …and their ERF res types
        self._raw_dirty: set[tuple[str, str]] = set()  # of those, the edited ones
        self._raw_areas: set[str] = set()  # area resrefs raw-edited (their .git)
        self._edited_areas: set[str] = set()  # area resrefs whose items were edited
        #: original value per edited module variable index / module setting.
        self._variable_originals: dict[int, object] = {}
        self._module_field_originals: dict[str, object] = {}

    @property
    def has_edits(self) -> bool:
        return bool(self._changes)

    def pending_changes(self) -> list[PendingChange]:
        """The staged edits, in the order they were first made."""
        return list(self._changes.values())

    # -- undo / redo ------------------------------------------------------- #
    @property
    def can_undo(self) -> bool:
        return bool(self._log)

    @property
    def can_redo(self) -> bool:
        return bool(self._undone)

    @property
    def undone_count(self) -> int:
        """Edits undone but still shown — never written."""
        return len(self._undone)

    def _record(self, command: _Command) -> None:
        """Append ``command``, collapsing a run of edits to the same target."""
        if (
            command.coalesce is not None
            and self._log
            and self._log[-1].coalesce == command.coalesce
        ):
            self._log[-1] = command  # replace: the run is one undo step
        else:
            self._log.append(command)
        self._undone.clear()  # a fresh edit invalidates the redo branch
        self._undone_display.clear()

    def undone_changes(self) -> list[PendingChange]:
        """Changes removed by :meth:`undo`, newest last.

        The design keeps these in the ledger, struck through — so what was backed
        out of stays visible — while excluding them from the write count.
        """
        return [change for group in self._undone_display for change in group]

    def undo(self) -> bool:
        """Take the last edit off the log. ``False`` if there was nothing to undo."""
        if not self._log:
            return False
        before = dict(self._changes)
        self._undone.append(self._log.pop())
        self._replay()
        # Whatever is no longer staged is what this undo backed out of.
        self._undone_display.append([
            change for key, change in before.items() if key not in self._changes
        ])
        return True

    def redo(self) -> bool:
        """Re-apply the most recently undone edit."""
        if not self._undone:
            return False
        self._log.append(self._undone.pop())
        if self._undone_display:
            self._undone_display.pop()
        self._replay()
        return True

    def _stage(self, kind: str, key, where: str, summary: str) -> None:
        """File a staged change under the ledger's ``(kind, key)`` key.

        The ledger's Discard button asks for ``(change.kind, change.key)``, so a
        staging site that files the entry anywhere else stages a change nobody can
        drop. ``key`` alone identifies the edited object; this pairs it with the
        kind. Every additive edit goes through here so the two cannot drift apart.
        """
        self._changes[(kind, key)] = PendingChange(
            kind=kind, key=key, where=where, summary=summary,
        )

    def discard_change(self, key: tuple) -> bool:
        """Drop the staged change identified by its ``self._changes`` key.

        Implemented by replaying every *other* edit, so nothing has to know how to
        reverse an edit — dropping the commands that produced it is enough.
        """
        culprits = self._commands_touching(key)
        if not culprits:
            return False
        self._log = [c for c in self._log if not any(c is x for x in culprits)]
        self._undone.clear()
        self._undone_display.clear()
        self._replay()
        return True

    def _commands_touching(self, key: tuple) -> list[_Command]:
        """Commands that created or altered the staged change at ``key``.

        One incremental replay: apply the log a command at a time and note where
        the entry at ``key`` appears or changes. Editing a field twice produces two
        commands but one change, and discarding it has to drop both.

        A raw list removal renumbers entries, so the change's key *moves* partway
        through the log — hence the per-step key from :meth:`_watched_keys`, and
        comparing identities rather than whole entries. Without either, an edit
        staged before a removal would look untouched and the removal would be
        dropped in its place.
        """
        watched = self._watched_keys(key)
        found: list[_Command] = []
        self._recording = False
        try:
            self._reset()
            for step, command in enumerate(self._log):
                before = _identity(self._changes.get(watched[step]))
                getattr(self, command.method)(*command.args, **command.kwargs)
                if _identity(self._changes.get(watched[step + 1])) != before:
                    found.append(command)
        finally:
            self._recording = True
        return found

    def _watched_keys(self, key: tuple) -> list[tuple]:
        """The key the change now at ``key`` was filed under before each command.

        Read straight off the log: a removal command carries the list and index it
        deleted, which is all :func:`_unshift_path` needs to walk a key backwards.
        """
        keys = [key]
        for command in reversed(self._log):
            current = keys[-1]
            removal = _removal(command)
            if removal is not None and current[0] == "raw" and current[1][0] == removal[0]:
                change_key = current[1]
                current = ("raw", (
                    change_key[0], _unshift_path(change_key[1], removal[1], removal[2]),
                ) + tuple(change_key[2:]))
            keys.append(current)
        keys.reverse()
        return keys

    def _replay(self) -> None:
        """Rebuild the staged state from the log, starting clean."""
        self._recording = False
        try:
            self._reset()
            for command in self._log:
                getattr(self, command.method)(*command.args, **command.kwargs)
        finally:
            self._recording = True

    def discard(self) -> None:
        """Drop every staged edit (re-reads happen fresh afterwards)."""
        self._reset()
        self._log.clear()
        self._undone.clear()
        self._undone_display.clear()

    def _reset(self) -> None:
        """Clear the staged state, keeping the undo log (see :meth:`_replay`)."""
        self._areas.clear()
        self._store_originals.clear()
        self._changes.clear()
        self._module = None
        self._bic = None
        self._bic_loaded = False
        self._char_dirty = False
        self._prop_originals.clear()
        self._max_obj_id = None
        self._add_seq = 0
        self._skill_originals.clear()
        self._char_field_originals.clear()
        self._feat_originals = None
        self._spell_originals.clear()
        self._raw_originals.clear()
        self._raw_trees.clear()
        self._raw_types.clear()
        self._raw_dirty.clear()
        self._raw_areas.clear()
        self._edited_areas.clear()
        self._variable_originals.clear()
        self._module_field_originals.clear()

    # -- store editing ---------------------------------------------------- #
    @_records(lambda area_resref, store_index, **_k: ("store", area_resref, store_index))
    def set_store_fields(
        self, area_resref: str, store_index: int, *, where: str | None = None, **values
    ) -> None:
        """Stage edits to a store's scalar settings (only non-``None`` values apply).

        ``where`` is a display label for the pending-changes list. Re-editing the
        same store updates its single pending entry; reverting every field to its
        original value removes it.
        """
        store = self._store_struct(area_resref, store_index)
        tkey = (area_resref.lower(), store_index)
        if tkey not in self._store_originals:
            self._store_originals[tkey] = {
                label: store.fields[label].value
                for label, _kind, _disp, _fmt in _STORE_FIELDS.values()
                if label in store.fields
            }
        for key, value in values.items():
            if value is None:
                continue
            if key not in _STORE_FIELDS:
                raise SaveEditError(f"unknown store field {key!r}")
            label, kind, _disp, _fmt = _STORE_FIELDS[key]
            gfield = store.fields.get(label)
            if gfield is None:
                raise SaveEditError(f"store has no {label!r} field to edit")
            gfield.value = int(value) if kind == "int" else (1 if value else 0)
        self._record_store_change(area_resref, store_index, store, where)

    def _record_store_change(self, area_resref, store_index, store, where) -> None:
        tkey = (area_resref.lower(), store_index)
        original = self._store_originals[tkey]
        parts = []
        for _key, (label, _kind, disp, fmt) in _STORE_FIELDS.items():
            if label not in store.fields:
                continue
            now = store.fields[label].value
            was = original.get(label)
            if now != was:
                parts.append(f"{disp} {fmt(was)}→{fmt(now)}")
        change_key = ("store", tkey)
        if parts:
            self._changes[change_key] = PendingChange(
                kind="store", key=(area_resref, store_index),
                where=where or (store.get("Tag") or f"Store {store_index}"),
                summary="; ".join(parts),
            )
        else:  # reverted to original -> no longer a pending change
            self._changes.pop(change_key, None)

    # -- items that live in an area's .git ----------------------------------- #
    # A store's stock could be browsed and a container's loot could be looked at,
    # but only a store's *settings* could be changed — so a chest and a guard's
    # sword were readable and untouchable for no reason the user could see.
    # These edit them in place. An area's .git has no player.bic mirror, so there
    # is one tree to write, not two.
    def _area_item_struct(self, area_resref: str, git_path: tuple) -> GffStruct:
        struct = self._area_tree(area_resref).root
        for label, index in git_path:
            entry = struct.fields.get(label)
            if entry is None or entry.type != GffType.LIST:
                raise SaveEditError(f"item path {git_path} does not resolve")
            if not 0 <= index < len(entry.value.structs):
                raise SaveEditError(f"item path {git_path} does not resolve")
            struct = entry.value.structs[index]
        return struct

    def _area_property_list(self, area_resref: str, git_path: tuple) -> GffField:
        item = self._area_item_struct(area_resref, git_path)
        plist = item.fields.get("PropertiesList")
        if plist is None or plist.type != GffType.LIST:
            plist = GffField(GffType.LIST, GffList([]))
            item.fields["PropertiesList"] = plist
        return plist

    def _area_dirty(self, area_resref: str) -> None:
        self._edited_areas.add(area_resref.lower())

    @_records(lambda area, path, index, *_a, **_k: ("area-prop", area.lower(), tuple(path), index))
    def set_area_property(
        self, area_resref: str, git_path: tuple, prop_index: int, *,
        subtype: int | None = None, cost_value: int | None = None,
        param1: int | None = None, param1_value: int | None = None,
        uses_per_day: int | None = None, where: str = "", label: str = "property",
    ) -> None:
        """Stage a change to an area item's property (subtype / value / param)."""
        structs = self._area_property_list(area_resref, git_path).value.structs
        if not 0 <= prop_index < len(structs):
            raise SaveEditError(f"property {prop_index} out of range")
        prop = structs[prop_index]
        for field_name, value in (
            ("Subtype", subtype), ("CostValue", cost_value), ("Param1", param1),
            ("Param1Value", param1_value), ("UsesPerDay", uses_per_day),
        ):
            if value is not None and field_name in prop.fields:
                prop.fields[field_name].value = int(value)
        self._area_dirty(area_resref)
        self._stage(
            "area-item", (area_resref, tuple(git_path), prop_index),
            where or area_resref, f"edit {label}",
        )

    @_records()
    def add_area_property(
        self, area_resref: str, git_path: tuple, *, property_name: int, subtype: int,
        cost_value: int, cost_table: int, param1: int | None = None,
        where: str = "", label: str = "property",
    ) -> None:
        """Stage adding a magical property to an item that lives in an area."""
        plist = self._area_property_list(area_resref, git_path)
        struct = _make_property_struct(
            property_name, subtype, cost_table, cost_value, param1
        )
        struct.struct_type = len(plist.value.structs)  # struct_type == list index
        plist.value.structs.append(struct)
        self._area_dirty(area_resref)
        self._stage(
            "area-item", (area_resref, tuple(git_path), struct.struct_type),
            where or area_resref, f"add {label}",
        )

    @_records()
    def remove_area_property(
        self, area_resref: str, git_path: tuple, prop_index: int, *,
        where: str = "", label: str = "property",
    ) -> None:
        """Stage removing a property from an item that lives in an area."""
        structs = self._area_property_list(area_resref, git_path).value.structs
        if not 0 <= prop_index < len(structs):
            raise SaveEditError(f"property {prop_index} out of range")
        del structs[prop_index]
        for i, struct in enumerate(structs):  # keep struct_type == index
            struct.struct_type = i
        self._add_seq += 1
        self._area_dirty(area_resref)
        # What it named is gone, so a sequence number keeps successive removals
        # from the same slot distinct — as it does for a raw list removal.
        self._stage(
            "area-item", (area_resref, tuple(git_path), prop_index, self._add_seq),
            where or area_resref, f"remove {label}",
        )

    def _area_tree(self, area_resref: str) -> Gff:
        key = area_resref.lower()
        if key not in self._areas:
            res = self._reader.find_resource(
                self._save.sav_path, area_resref, res_type=_GIT_RESTYPE
            )
            if res is None:
                raise SaveEditError(f"area {area_resref!r} is not in this save")
            self._areas[key] = read_gff(
                self._reader.read_resource_bytes(self._save.sav_path, res)
            )
        return self._areas[key]

    def _store_struct(self, area_resref: str, store_index: int):
        field = self._area_tree(area_resref).root.fields.get("StoreList")
        if field is None or field.type != GffType.LIST:
            raise SaveEditError(f"area {area_resref!r} has no stores")
        stores = field.value.structs
        if not 0 <= store_index < len(stores):
            raise SaveEditError(f"store index {store_index} out of range for {area_resref!r}")
        return stores[store_index]

    # -- player-item property editing ------------------------------------ #
    def player_items(self) -> list[EditableItem]:
        """Every item on the player character (equipped + carried, incl. bags).

        Read from ``module.ifo`` ``Mod_PlayerList[0]`` — the copy the engine loads
        for a saved game — each tagged with the GFF path used to edit it.
        """
        player = self._player_struct(self._module_tree())
        items: list[EditableItem] = []
        equip = player.fields.get("Equip_ItemList")
        if equip is not None and equip.type == GffType.LIST:
            for i, struct in enumerate(equip.value.structs):
                path = (("Equip_ItemList", i),)
                items.append(self._editable_item(struct, path, struct.struct_type))
        self._walk_carried(player, (), items)
        return items

    def _walk_carried(self, container: GffStruct, base: tuple, out: list) -> None:
        field = container.fields.get("ItemList")
        if field is None or field.type != GffType.LIST:
            return
        for i, struct in enumerate(field.value.structs):
            path = (*base, ("ItemList", i))
            out.append(self._editable_item(struct, path, None))
            self._walk_carried(struct, path, out)  # a bag's own contents

    @staticmethod
    def _editable_item(struct: GffStruct, path: tuple, slot: int | None) -> EditableItem:
        loc = struct.get("LocalizedName")
        name = loc.text() if loc is not None else ""
        name_strref = loc.strref if loc is not None else -1
        resref = (struct.get("TemplateResRef") or "").strip()
        props: list[EditableProperty] = []
        plist = struct.fields.get("PropertiesList")
        if plist is not None and plist.type == GffType.LIST:
            for j, ps in enumerate(plist.value.structs):
                props.append(EditableProperty(
                    index=j,
                    prop=ItemProperty(
                        property_name=ps.get("PropertyName") or 0,
                        subtype=ps.get("Subtype") or 0,
                        cost_table=ps.get("CostTable") or 0,
                        cost_value=ps.get("CostValue") or 0,
                        param1=ps.get("Param1") or 0,
                        param1_value=ps.get("Param1Value") or 0,
                    ),
                    uses_per_day=ps.get("UsesPerDay") if ps.get("UsesPerDay") is not None else 255,
                ))
        return EditableItem(
            path=path, slot=slot,
            name=name or (f"(unnamed: {resref})" if resref else "(item)"),
            name_strref=name_strref, resref=resref,
            base_item=struct.get("BaseItem") or -1,
            model_part=struct.get("ModelPart1") or 0,
            properties=props,
        )

    #: property struct fields the editor may change (all indexes into iprp_* tables).
    _PROP_FIELDS = ("Subtype", "CostValue", "Param1", "Param1Value", "UsesPerDay")

    @_records(lambda item_path, prop_index, **_k: ("property", tuple(item_path), prop_index))
    def set_property(
        self, item_path: tuple, prop_index: int, *,
        subtype: int | None = None, cost_value: int | None = None,
        param1: int | None = None, param1_value: int | None = None,
        uses_per_day: int | None = None, where: str = "", label: str = "property",
    ) -> None:
        """Stage a change to a property's subtype / cost value / param (both trees).

        Only non-``None`` fields change; each is a valid row in the property's
        ``iprp_*`` table (see :mod:`vaultkeeper.game.item_property_tables`), so the
        result can't be out of range. Reverting every field removes the pending
        entry. Applied to ``module.ifo`` (authoritative) and the ``player.bic`` mirror.
        """
        okey = (tuple(item_path), prop_index)
        base_ps = self._property_struct(self._module_tree(), item_path, prop_index)
        if okey not in self._prop_originals:
            self._prop_originals[okey] = {
                field: base_ps.get(field) for field in self._PROP_FIELDS
                if field in base_ps.fields
            }
        edits = {
            "Subtype": subtype, "CostValue": cost_value,
            "Param1": param1, "Param1Value": param1_value, "UsesPerDay": uses_per_day,
        }
        for tree in self._targets():
            try:
                ps = self._property_struct(tree, item_path, prop_index)
            except SaveEditError:
                continue  # player.bic diverged; module.ifo is authoritative
            for field, value in edits.items():
                if value is not None and field in ps.fields:
                    ps.fields[field].value = int(value)
        self._char_dirty = True
        self._record_property_change(item_path, prop_index, base_ps, where, label)

    @_records(lambda item_path, prop_index, *_a, **_k: ("cost", tuple(item_path), prop_index))
    def set_property_cost(
        self, item_path: tuple, prop_index: int, *,
        cost_value: int | None = None, uses_per_day: int | None = None,
        where: str = "", prop_label: str = "property",
    ) -> None:
        """Backwards-compatible shim for the magnitude/uses quick edit."""
        self.set_property(
            item_path, prop_index, cost_value=cost_value, uses_per_day=uses_per_day,
            where=where, label=prop_label,
        )

    def _targets(self) -> list[Gff]:
        trees = [self._module_tree()]
        bic = self._bic_tree()
        if bic is not None:
            trees.append(bic)
        return trees

    def _record_property_change(self, item_path, prop_index, base_ps, where, label) -> None:
        original = self._prop_originals[(tuple(item_path), prop_index)]
        now = {field: base_ps.get(field) for field in original}
        change_key = ("property", (tuple(item_path), prop_index))
        if now != original:
            self._changes[change_key] = PendingChange(
                kind="property", key=(item_path, prop_index),
                where=where or "item", summary=f"edited → {label}",
            )
        else:
            self._changes.pop(change_key, None)

    def _module_tree(self) -> Gff:
        if self._module is None:
            res = self._reader.find_resource(self._save.sav_path, "module", res_type=_IFO_RESTYPE)
            if res is None:
                raise SaveEditError("save has no module.ifo")
            self._module = read_gff(self._reader.read_resource_bytes(self._save.sav_path, res))
        return self._module

    def _bic_tree(self) -> Gff | None:
        if not self._bic_loaded:
            self._bic_loaded = True
            bic = self._save.player_bic
            if bic is not None:
                try:
                    self._bic = read_gff(bic.read_bytes())
                except Exception:
                    self._bic = None
        return self._bic

    @staticmethod
    def _player_struct(tree: Gff) -> GffStruct:
        # module.ifo wraps the character in Mod_PlayerList; player.bic *is* the character.
        field = tree.root.fields.get(_PLAYER_LIST)
        if field is not None and field.type == GffType.LIST and field.value.structs:
            return field.value.structs[0]
        if tree.root.fields.keys() & {"Equip_ItemList", "ItemList", "FeatList"}:
            return tree.root
        raise SaveEditError("save has no player character")

    def _item_struct(self, tree: Gff, item_path: tuple) -> GffStruct:
        struct = self._player_struct(tree)
        for label, index in item_path:
            field = struct.fields.get(label)
            if field is None or field.type != GffType.LIST:
                raise SaveEditError(f"item path {item_path} does not resolve")
            if not 0 <= index < len(field.value.structs):
                raise SaveEditError(f"item path {item_path} does not resolve")
            struct = field.value.structs[index]
        return struct

    def _property_struct(self, tree: Gff, item_path: tuple, prop_index: int) -> GffStruct:
        plist = self._item_struct(tree, item_path).fields.get("PropertiesList")
        if plist is None or plist.type != GffType.LIST:
            raise SaveEditError(f"property {prop_index} out of range")
        if not 0 <= prop_index < len(plist.value.structs):
            raise SaveEditError(f"property {prop_index} out of range")
        return plist.value.structs[prop_index]

    @_records()
    def add_item_property(
        self, item_path: tuple, *, property_name: int, subtype: int, cost_value: int,
        cost_table: int, param1: int | None = None,
        where: str = "", label: str = "property",
    ) -> None:
        """Stage adding a new magical property to a player item (both trees)."""
        self._char_dirty = True
        module, index = self._module_tree(), 0
        for tree in self._targets():
            item = self._item_struct(tree, item_path)
            plist = item.fields.get("PropertiesList")
            if plist is None or plist.type != GffType.LIST:
                plist = GffField(GffType.LIST, GffList([]))
                item.fields["PropertiesList"] = plist
            struct = _make_property_struct(
                property_name, subtype, cost_table, cost_value, param1
            )
            struct.struct_type = len(plist.value.structs)  # struct_type == list index
            plist.value.structs.append(struct)
            if tree is module:  # the authoritative tree names the property
                index = struct.struct_type
        # Keyed on where the property landed — the same (item path, index) pair the
        # inventory screen marks a property with, and edits to it are staged under.
        self._stage("prop-add", (tuple(item_path), index), where or "item", f"add {label}")

    @_records()
    def remove_item_property(
        self, item_path: tuple, prop_index: int, *, where: str = "", label: str = "property",
    ) -> None:
        """Stage removing a property from a player item (both trees)."""
        self._char_dirty = True
        for tree in self._targets():
            plist = self._item_struct(tree, item_path).fields.get("PropertiesList")
            if plist is not None and plist.type == GffType.LIST:
                if 0 <= prop_index < len(plist.value.structs):
                    del plist.value.structs[prop_index]
                for i, struct in enumerate(plist.value.structs):  # keep struct_type == index
                    struct.struct_type = i
        self._add_seq += 1
        # What it named is gone, so the sequence number keeps successive removals
        # from the same slot distinct — as it does for a raw list removal.
        self._stage(
            "prop-remove", (tuple(item_path), prop_index, self._add_seq),
            where or "item", f"remove {label}",
        )

    # -- add items -------------------------------------------------------- #
    @_records()
    def add_item_copy(self, source_path: tuple, *, where: str = "") -> None:
        """Append a copy of an existing player item to the carried inventory.

        Cloning a known-good item is the safe way to "add an item": it is already
        valid for this character/module.
        """
        source = self._item_struct(self._module_tree(), source_path)
        name = where or (source.get("TemplateResRef") or "item")
        self._clone_into_carried(source, where=name, summary="added a copy to inventory")

    @_records()
    def add_item_from_area(self, area_resref: str, resref: str, *, where: str = "") -> None:
        """Clone an item that lives in an area (a store's stock, a creature's or a
        container's item) into the player's carried inventory.

        The source is found in the area's ``.git`` by its blueprint ``resref`` — a
        complete, module-valid item struct — and copied over unchanged (bar a fresh
        ObjectId + carried slot). The area itself is not modified.
        """
        source = self._find_area_item(self._area_tree(area_resref).root, resref)
        if source is None:
            raise SaveEditError(f"could not find item {resref!r} in area {area_resref!r}")
        self._clone_into_carried(
            source, where=where or resref, summary=f"added a copy from {area_resref}"
        )

    def _clone_into_carried(self, source: GffStruct, *, where: str, summary: str) -> None:
        """Deep-copy an item struct into the player's ItemList (both trees), staged."""
        import copy

        clone = copy.deepcopy(source)
        clone.struct_type = 0  # a carried item (equipped items carry a slot bit)
        new_id = self._next_object_id()
        if "ObjectId" in clone.fields:
            clone.fields["ObjectId"].value = new_id
        for tree in self._targets():
            carried = self._player_struct(tree).fields.get("ItemList")
            if carried is not None and carried.type == GffType.LIST:
                carried.value.structs.append(copy.deepcopy(clone))
        self._char_dirty = True
        # The fresh ObjectId names the new item: unique per add, and minted in the
        # same order on every replay, so the ledger's discard key stays put.
        self._stage("add-item", (new_id,), where, summary)

    def _find_area_item(self, struct: GffStruct, resref: str) -> GffStruct | None:
        """First item struct (has ``BaseItem``) with this ``TemplateResRef``, DFS.

        ``BaseItem`` distinguishes items from the creatures/placeables that also
        carry a ``TemplateResRef``.
        """
        if "BaseItem" in struct.fields and (
            (struct.get("TemplateResRef") or "").lower() == resref.lower()
        ):
            return struct
        for field in struct.fields.values():
            if field.type == GffType.STRUCT:
                hit = self._find_area_item(field.value, resref)
                if hit is not None:
                    return hit
            elif field.type == GffType.LIST:
                for child in field.value.structs:
                    hit = self._find_area_item(child, resref)
                    if hit is not None:
                        return hit
        return None

    def _next_object_id(self) -> int:
        """A fresh ObjectId above every real (< OBJECT_INVALID) id in module.ifo."""
        if self._max_obj_id is None:
            ids: list[int] = []
            self._collect_object_ids(self._module_tree().root, ids)
            valid = [i for i in ids if i < 0x7F000000]
            self._max_obj_id = max(valid) if valid else 0
        self._max_obj_id += 1
        return self._max_obj_id

    def _collect_object_ids(self, struct: GffStruct, out: list[int]) -> None:
        for field in struct.fields.values():
            if field.type == GffType.STRUCT:
                self._collect_object_ids(field.value, out)
            elif field.type == GffType.LIST:
                for child in field.value.structs:
                    self._collect_object_ids(child, out)
        oid = struct.fields.get("ObjectId")
        if oid is not None:
            out.append(oid.value)

    # -- skill editing ---------------------------------------------------- #
    def player_skills(self) -> list[EditableSkill]:
        """The player character's skills (id, name, rank), in skill-id order."""
        from vaultkeeper.game.character_reference import default_reference

        ref = default_reference()
        skills = self._player_struct(self._module_tree()).fields.get("SkillList")
        if skills is None or skills.type != GffType.LIST:
            return []
        return [
            EditableSkill(i, ref.skill_name(i), struct.get("Rank") or 0)
            for i, struct in enumerate(skills.value.structs)
        ]

    @_records(lambda skill_index, *_a, **_k: ("skill", skill_index))
    def set_skill_rank(self, skill_index: int, rank: int, *, where: str = "") -> None:
        """Stage a change to a skill's rank (reverting to its original removes it)."""
        if skill_index not in self._skill_originals:
            self._skill_originals[skill_index] = (
                self._skill_struct(self._module_tree(), skill_index).get("Rank") or 0
            )
        for tree in self._targets():
            try:
                self._skill_struct(tree, skill_index).fields["Rank"].value = int(rank)
            except SaveEditError:
                continue  # player.bic diverged; module.ifo is authoritative
        self._char_dirty = True
        was, now = self._skill_originals[skill_index], int(rank)
        change_key = ("skill", skill_index)
        if now != was:
            self._changes[change_key] = PendingChange(
                kind="skill", key=skill_index,
                where=where or f"Skill {skill_index}", summary=f"rank {was}→{now}",
            )
        else:
            self._changes.pop(change_key, None)

    def _skill_struct(self, tree: Gff, skill_index: int) -> GffStruct:
        skills = self._player_struct(tree).fields.get("SkillList")
        if skills is None or skills.type != GffType.LIST:
            raise SaveEditError("character has no skills")
        if not 0 <= skill_index < len(skills.value.structs):
            raise SaveEditError(f"skill {skill_index} out of range")
        return skills.value.structs[skill_index]

    # -- top-level character fields --------------------------------------- #
    def player_fields(self) -> list[CharacterField]:
        """Editable character fields present on the character (gold, abilities …)."""
        player = self._player_struct(self._module_tree())
        fields: list[CharacterField] = []
        for name, display, lo, hi in _CHARACTER_FIELDS:
            if name in player.fields:
                fields.append(CharacterField(name, display, "int", player.get(name) or 0, lo, hi))
        for name, display in _CHARACTER_NAMES:
            if name in player.fields:
                loc = player.get(name)
                text = loc.text() if loc is not None else ""
                fields.append(CharacterField(name, display, "name", text))
        if "Race" in player.fields:  # racial type — a byte, but picked by name
            fields.append(CharacterField("Race", "Race", "race", player.get("Race") or 0))
        if "Appearance_Type" in player.fields:  # cosmetic model (appearance.2da)
            fields.append(CharacterField(
                "Appearance_Type", "Appearance", "appearance", player.get("Appearance_Type") or 0
            ))
        if "Portrait" in player.fields:  # cosmetic portrait resref
            fields.append(
                CharacterField("Portrait", "Portrait", "resref", player.get("Portrait") or "")
            )
        return fields

    def original_field_value(self, field: str):
        """What a character field held before any staged edit, or ``None``.

        Lets a UI show the design's ``old → new`` treatment without parsing a
        :attr:`PendingChange.summary` display string.
        """
        return self._char_field_originals.get(field)

    @_records(lambda field, *_a, **_k: ("char", field))
    def set_character_field(self, field: str, value: int, *, where: str = "") -> None:
        """Stage a change to a scalar character field (both trees), reverting removes it."""
        base = self._player_struct(self._module_tree())
        if field not in self._char_field_originals:
            self._char_field_originals[field] = base.get(field)
        for tree in self._targets():
            player = self._player_struct(tree)
            if field in player.fields:
                player.fields[field].value = int(value)
        self._char_dirty = True
        self._record_char_field(field, where, f"{self._char_field_originals[field]}→{int(value)}")

    @_records(lambda field, *_a, **_k: ("char", field))
    def set_character_resref(self, field: str, resref: str, *, where: str = "") -> None:
        """Stage a change to a CRESREF character field (e.g. Portrait) in both trees."""
        base = self._player_struct(self._module_tree())
        if field not in self._char_field_originals:
            self._char_field_originals[field] = base.get(field)
        for tree in self._targets():
            player = self._player_struct(tree)
            if field in player.fields:
                player.fields[field].value = str(resref)
        self._char_dirty = True
        was = self._char_field_originals[field]
        self._record_char_field(field, where, f"“{was}”→“{resref}”", changed=str(resref) != was)

    @_records(lambda field, *_a, **_k: ("char", field))
    def set_character_name(self, field: str, text: str, *, where: str = "") -> None:
        """Stage a change to a character name field (CExoLocString) in both trees."""
        base = self._player_struct(self._module_tree())
        if field not in self._char_field_originals:
            loc = base.get(field)
            self._char_field_originals[field] = loc.text() if loc is not None else ""
        for tree in self._targets():
            loc = self._player_struct(tree).get(field)
            if loc is not None:
                if loc.substrings:
                    loc.substrings[0] = (loc.substrings[0][0], text)
                else:
                    loc.substrings.append((0, text))
                loc.strref = -1  # store the name inline
        self._char_dirty = True
        was = self._char_field_originals[field]
        self._record_char_field(field, where, f"“{was}”→“{text}”", changed=text != was)

    def _record_char_field(self, field, where, summary, *, changed=None) -> None:
        if changed is None:
            now = self._player_struct(self._module_tree()).get(field)
            changed = now != self._char_field_originals[field]
        key = ("char-field", field)
        if changed:
            self._changes[key] = PendingChange(
                kind="char-field", key=field, where=where or field, summary=summary,
            )
        else:
            self._changes.pop(key, None)

    # -- feat editing ----------------------------------------------------- #
    def player_feats(self) -> list[tuple[int, str, bool]]:
        """The character's feats as ``(feat_id, name, is_base)`` (name-sorted).

        ``is_base`` is False for PRC feats — those are regenerated by PRC's scripts
        so editing them via ``FeatList`` may not persist in-game (warn the user).
        """
        from vaultkeeper.game.character_reference import default_reference

        ref = default_reference()
        feats = self._feat_list(self._module_tree())
        if feats is None:
            return []
        rows = [
            (fid, ref.feat_name(fid), ref.is_base_feat(fid))
            for fid in sorted({s.get("Feat") for s in feats.structs if s.get("Feat") is not None})
        ]
        rows.sort(key=lambda r: r[1].lower())
        return rows

    @_records()
    def add_feat(self, feat_id: int) -> None:
        """Stage adding a feat id to the character's FeatList (both trees)."""
        self._ensure_feat_originals()
        for tree in self._targets():
            feats = self._feat_list(tree)
            if feats is not None and feat_id not in self._feat_ids(feats):
                struct_type = feats.structs[0].struct_type if feats.structs else 1
                feats.structs.append(GffStruct(
                    struct_type=struct_type,
                    fields={"Feat": GffField(GffType.WORD, feat_id)},
                ))
        self._char_dirty = True
        self._recompute_feat_changes()

    @_records()
    def remove_feat(self, feat_id: int) -> None:
        """Stage removing a feat id from the character's FeatList (both trees)."""
        self._ensure_feat_originals()
        for tree in self._targets():
            feats = self._feat_list(tree)
            if feats is not None:
                feats.structs[:] = [s for s in feats.structs if s.get("Feat") != feat_id]
        self._char_dirty = True
        self._recompute_feat_changes()

    def _feat_list(self, tree: Gff):
        field = self._player_struct(tree).fields.get("FeatList")
        return field.value if field is not None and field.type == GffType.LIST else None

    @staticmethod
    def _feat_ids(feat_list) -> set[int]:
        return {s.get("Feat") for s in feat_list.structs if s.get("Feat") is not None}

    def _ensure_feat_originals(self) -> None:
        if self._feat_originals is None:
            feats = self._feat_list(self._module_tree())
            self._feat_originals = self._feat_ids(feats) if feats is not None else set()

    def _recompute_feat_changes(self) -> None:
        """Derive pending feat add/removes from the tree vs the original feat set."""
        from vaultkeeper.game.character_reference import default_reference

        ref = default_reference()
        feats = self._feat_list(self._module_tree())
        current = self._feat_ids(feats) if feats is not None else set()
        original = self._feat_originals or set()
        for key in [k for k in self._changes if k[0] == "feat"]:
            del self._changes[key]
        for verb, ids in (("add", current - original), ("remove", original - current)):
            for fid in sorted(ids):
                note = "" if ref.is_base_feat(fid) else " (PRC — may not persist)"
                self._changes[("feat", (verb, fid))] = PendingChange(
                    kind="feat", key=(verb, fid),
                    where=ref.feat_name(fid), summary=f"{verb} feat{note}",
                )

    # -- spell editing ---------------------------------------------------- #
    def player_spellbook(self) -> list[ClassSpellbook]:
        """The character's spellbook: each caster class's Known/Memorized lists."""
        from vaultkeeper.game.character import class_name, is_base_class
        from vaultkeeper.game.character_reference import default_reference

        ref = default_reference()
        classes = self._player_struct(self._module_tree()).fields.get("ClassList")
        books: list[ClassSpellbook] = []
        if classes is None or classes.type != GffType.LIST:
            return books
        for ci, cstruct in enumerate(classes.value.structs):
            cid = cstruct.get("Class") or -1
            lists: list[SpellList] = []
            for name in cstruct.fields:
                kind = "Known" if name.startswith("KnownList") else (
                    "Memorized" if name.startswith("MemorizedList") else None
                )
                level = name[len("Memorized" if kind == "Memorized" else "Known") + 4:]
                if kind is None or not level.isdigit():
                    continue
                field = cstruct.fields[name]
                if field.type != GffType.LIST:
                    continue
                spells = [
                    (s.get("Spell"), ref.spell_name(s.get("Spell")))
                    for s in field.value.structs if s.get("Spell") is not None
                ]
                lists.append(SpellList(ci, name, kind, int(level), spells))
            if lists:
                lists.sort(key=lambda sl: (sl.kind, sl.level))
                books.append(ClassSpellbook(ci, cid, class_name(cid), is_base_class(cid), lists))
        return books

    @_records()
    def add_spell(self, class_index: int, list_field: str, spell_id: int) -> None:
        """Stage adding a spell to a class's Known/Memorized list (both trees)."""
        self._ensure_spell_originals()
        for tree in self._targets():
            spell_list = self._spell_list(tree, class_index, list_field)
            if spell_list is not None and spell_id not in self._spell_ids(spell_list):
                spell_list.structs.append(self._new_spell_struct(spell_list, spell_id))
        self._char_dirty = True
        self._recompute_spell_changes(class_index, list_field)

    @_records()
    def remove_spell(self, class_index: int, list_field: str, spell_id: int) -> None:
        """Stage removing a spell from a class's Known/Memorized list (both trees)."""
        self._ensure_spell_originals()
        for tree in self._targets():
            spell_list = self._spell_list(tree, class_index, list_field)
            if spell_list is not None:
                spell_list.structs[:] = [
                    s for s in spell_list.structs if s.get("Spell") != spell_id
                ]
        self._char_dirty = True
        self._recompute_spell_changes(class_index, list_field)

    @staticmethod
    def _new_spell_struct(spell_list, spell_id: int) -> GffStruct:
        """A struct for a new spell: clone an existing one (exact shape) or minimal."""
        import copy

        if spell_list.structs:
            clone = copy.deepcopy(spell_list.structs[0])  # preserve Ready/MetaMagic/…
            if "Spell" in clone.fields:
                clone.fields["Spell"].value = spell_id
            return clone
        return GffStruct(struct_type=3, fields={"Spell": GffField(GffType.WORD, spell_id)})

    def _spell_list(self, tree: Gff, class_index: int, list_field: str):
        classes = self._player_struct(tree).fields.get("ClassList")
        if classes is None or not 0 <= class_index < len(classes.value.structs):
            return None
        field = classes.value.structs[class_index].fields.get(list_field)
        return field.value if field is not None and field.type == GffType.LIST else None

    @staticmethod
    def _spell_ids(spell_list) -> set[int]:
        return {s.get("Spell") for s in spell_list.structs if s.get("Spell") is not None}

    def _ensure_spell_originals(self) -> None:
        if not self._spell_originals:
            for book in self.player_spellbook():
                for sl in book.lists:
                    self._spell_originals[(sl.class_index, sl.list_field)] = {
                        sid for sid, _ in sl.spells
                    }

    def _recompute_spell_changes(self, class_index: int, list_field: str) -> None:
        from vaultkeeper.game.character_reference import default_reference

        ref = default_reference()
        spell_list = self._spell_list(self._module_tree(), class_index, list_field)
        current = self._spell_ids(spell_list) if spell_list is not None else set()
        original = self._spell_originals.get((class_index, list_field), set())
        key_prefix = (class_index, list_field)
        for k in [k for k in self._changes if k[0] == "spell" and k[1][:2] == key_prefix]:
            del self._changes[k]
        for verb, ids in (("add", current - original), ("remove", original - current)):
            for sid in sorted(ids):
                self._changes[("spell", (class_index, list_field, verb, sid))] = PendingChange(
                    kind="spell", key=(class_index, list_field, verb, sid),
                    where=ref.spell_name(sid), summary=f"{verb} spell",
                )

    # -- world state + party ------------------------------------------------ #
    #: editable module-level settings: GFF field -> (display, min, max).
    MODULE_FIELDS: dict[str, tuple[str, int, int]] = {
        "Mod_MaxHenchmen": ("Max henchmen", 0, 20),
        "Mod_PartyControl": ("Party control", 0, 1),
        "Mod_XPScale": ("XP scale (%)", 0, 1000),
    }

    def module_variables(self) -> list:
        """The module's persistent script variables (its world state)."""
        from vaultkeeper.game.world_state import read_variables

        return read_variables(self._module_tree())

    @_records(lambda index, *_a, **_k: ("variable", index))
    def set_variable(self, index: int, value, *, where: str = "") -> None:
        """Set a module variable's value, keeping its stored type."""
        from vaultkeeper.game.world_state import EDITABLE_TYPES

        entry_field = self._module_tree().root.fields.get("VarTable")
        table = entry_field.value if entry_field is not None else None
        if table is None or index >= len(table.structs):
            raise SaveEditError("no such module variable")
        struct = table.structs[index]
        type_code = int(struct.fields["Type"].value)
        if type_code not in EDITABLE_TYPES:
            raise SaveEditError("this variable's type cannot be edited safely")

        entry = struct.fields["Value"]
        original = self._variable_originals.setdefault(index, entry.value)
        try:
            entry.value = type(entry.value)(value)
        except (TypeError, ValueError) as exc:
            raise SaveEditError(f"{value!r} does not fit this variable") from exc

        self._char_dirty = True  # the variable lives in module.ifo
        name = str(struct.fields["Name"].value)
        key = ("variable", index)
        if entry.value != original:
            self._changes[key] = PendingChange(
                kind="variable", key=index, where=where or name,
                summary=f"{original}→{entry.value}",
            )
        else:
            self._changes.pop(key, None)

    def module_fields(self) -> list[CharacterField]:
        """Editable module-level settings present in this save."""
        root = self._module_tree().root
        out: list[CharacterField] = []
        for field, (display, low, high) in self.MODULE_FIELDS.items():
            entry = root.fields.get(field)
            if entry is None:
                continue  # not every module writes every setting
            out.append(CharacterField(
                field=field, display=display, kind="int",
                value=entry.value, minimum=low, maximum=high,
            ))
        return out

    @_records(lambda field, *_a, **_k: ("module-field", field))
    def set_module_field(self, field: str, value: int, *, where: str = "") -> None:
        """Set a module-level setting (henchmen cap, party control, XP scale)."""
        if field not in self.MODULE_FIELDS:
            raise SaveEditError(f"{field} is not an editable module setting")
        entry = self._module_tree().root.fields.get(field)
        if entry is None:
            raise SaveEditError(f"this module has no {field} setting")
        original = self._module_field_originals.setdefault(field, entry.value)
        entry.value = type(entry.value)(value)
        self._char_dirty = True

        key = ("module-field", field)
        if entry.value != original:
            self._changes[key] = PendingChange(
                kind="module-field", key=field,
                where=where or self.MODULE_FIELDS[field][0],
                summary=f"{original}→{entry.value}",
            )
        else:
            self._changes.pop(key, None)

    # -- raw GFF editing ---------------------------------------------------- #
    #: The two trees the friendly editors write. Everything else in the .sav is
    #: browsable too (see :meth:`raw_targets`) but is not part of the edit path.
    RAW_TARGETS = ("module.ifo", "player.bic")

    def raw_targets(self) -> list[str]:
        """Every resource a save carries, as ``"name.ext"``, browsable raw.

        Leto could open any component of a ``.sav``; so can this. The character's
        own two trees come first because they are what almost every edit touches.
        """
        names = list(self.RAW_TARGETS)
        try:
            for res in self._reader.list_resources(self._save.sav_path):
                name = f"{res.resref}.{res.extension}"
                if name not in names:
                    names.append(name)
        except Exception:
            pass
        return names

    def raw_tree(self, target: str) -> Gff | None:
        """The decoded tree for a raw target, or ``None`` if it is unavailable."""
        if target == "module.ifo":
            return self._module_tree()
        if target == "player.bic":
            return self._bic_tree()
        resref, extension = self._split_target(target)
        if extension == "git":
            return self._area_tree(resref)
        return self._read_resource_tree(resref, extension)

    @staticmethod
    def _split_target(target: str) -> tuple[str, str]:
        """``"foo.are"`` -> ``("foo", "are")``; a bare name is an area's ``.git``."""
        resref, dot, extension = target.rpartition(".")
        return (resref.lower(), extension.lower()) if dot else (target.lower(), "git")

    def _read_resource_tree(self, resref: str, extension: str) -> Gff | None:
        """Decode (and keep) any other GFF resource in the ``.sav``.

        Cached like the character and area trees: a raw edit has to survive until
        :meth:`save_as`, and the screen re-reads the tree on every refresh — an
        uncached tree would take the edit and then be discarded.
        """
        key = (resref.lower(), extension.lower())
        if key in self._raw_trees:
            return self._raw_trees[key]
        self._raw_trees[key] = None
        try:
            for res in self._reader.list_resources(self._save.sav_path):
                if res.resref == key[0] and res.extension == key[1]:
                    data = self._reader.read_resource_bytes(self._save.sav_path, res)
                    self._raw_trees[key] = read_gff(data)
                    self._raw_types[key] = res.res_type
                    break
        except Exception:
            self._raw_trees[key] = None
        return self._raw_trees[key]

    def _mark_raw_dirty(self, target: str) -> None:
        """Note which resource a raw edit touched, so :meth:`save_as` writes it back."""
        if target in self.RAW_TARGETS:
            self._char_dirty = True
            return
        resref, extension = self._split_target(target)
        if extension == "git":
            self._raw_areas.add(resref)
        elif (resref, extension) in self._raw_types:
            self._raw_dirty.add((resref, extension))

    @_records(lambda target, path, *_a, **_k: ("raw", target, tuple(path)))
    def set_raw_field(self, target: str, path: tuple, value, *, where: str = "") -> None:
        """Set a scalar field directly, bypassing the friendly editors.

        ``path`` is the sequence of ``(label, index_or_None)`` steps produced by the
        Raw Data screen. Only scalars are settable — a container has no single
        value — and the field's existing Python type is preserved, so a raw edit
        cannot change a WORD into a string and corrupt the resource.
        """
        tree = self.raw_tree(target)
        if tree is None:
            raise SaveEditError(f"{target} is not part of this save")
        entry = self._raw_entry(tree, path)
        original = entry.value
        if isinstance(original, (GffStruct, GffList)):
            raise SaveEditError("only scalar fields can be edited here")
        try:
            entry.value = type(original)(value)
        except (TypeError, ValueError) as exc:
            raise SaveEditError(f"{value!r} is not a valid {type(original).__name__}") from exc

        self._mark_raw_dirty(target)
        key = ("raw", (target, tuple(path)))
        label = _render_raw_path(path)
        if entry.value != self._raw_original(target, path, original):
            self._changes[key] = PendingChange(
                kind="raw", key=(target, tuple(path)),
                where=where or f"{target}: {label}",
                summary=f"{self._raw_originals[(target, tuple(path))]}→{entry.value}",
            )
        else:
            self._changes.pop(key, None)

    def _raw_original(self, target: str, path: tuple, current):
        """Remember a raw field's pre-edit value the first time it is touched."""
        key = (target, tuple(path))
        if key not in self._raw_originals:
            self._raw_originals[key] = current
        return self._raw_originals[key]

    @staticmethod
    def _raw_entry(tree: Gff, path: tuple):
        """Walk ``path`` to the GffField it names."""
        struct = tree.root
        for step, (label, index) in enumerate(path):
            entry = struct.fields.get(label)
            if entry is None:
                raise SaveEditError(f"no field {label!r} at that path")
            if step == len(path) - 1:
                return entry
            value = entry.value
            if isinstance(value, GffList):
                if index is None or index >= len(value.structs):
                    raise SaveEditError(f"{label}[{index}] is out of range")
                struct = value.structs[index]
            elif isinstance(value, GffStruct):
                struct = value
            else:
                raise SaveEditError(f"{label} is a scalar, not a container")
        raise SaveEditError("empty path")

    # -- raw list structure (add / duplicate / remove entries) ------------- #
    @_records()
    def add_raw_struct(
        self, target: str, path: tuple, *, source_index: int | None = None, where: str = ""
    ) -> int:
        """Append an entry to the GFF list at ``path``, and return its index.

        ``source_index`` **duplicates** that sibling — the reliable route, because
        the copy is already a valid entry of this list, with the fields, GFF types
        and ``struct_type`` the game expects there. Without it the new entry is
        *seeded* instead: the first sibling's field set and types, values zeroed.
        Either way the caller gets back the index so it can say which it did.

        Like every raw edit this touches one resource only — editing ``module.ifo``
        does not mirror into ``player.bic``.
        """
        import copy

        entries = self._raw_list(target, path).structs
        numbered = _numbered_by_index(entries)
        if source_index is None:
            new = _seeded_from(entries[0]) if entries else GffStruct()
            how = "seeded from [0]" if entries else "empty (the list had no sibling)"
        else:
            if not 0 <= source_index < len(entries):
                raise SaveEditError(f"entry {source_index} is out of range")
            new = copy.deepcopy(entries[source_index])
            how = f"copy of [{source_index}]"
        index = len(entries)
        if numbered:  # e.g. PropertiesList — the entry's position is its struct type
            new.struct_type = index
        entries.append(new)

        self._mark_raw_dirty(target)
        self._add_seq += 1
        self._stage_raw(
            (target, tuple(path), "add", self._add_seq), where, f"add entry [{index}] — {how}"
        )
        return index

    # ``target``/``path``/``index`` are positional-only so the recorded command is
    # always in that shape — :meth:`_watched_keys` reads the removal back off it.
    @_records()
    def remove_raw_struct(
        self, target: str, path: tuple, index: int, /, *, where: str = ""
    ) -> None:
        """Remove entry ``index`` from the GFF list at ``path``."""
        entries = self._raw_list(target, path).structs
        if not 0 <= index < len(entries):
            raise SaveEditError(f"entry {index} is out of range")
        numbered = _numbered_by_index(entries)
        del entries[index]
        if numbered:
            for position, struct in enumerate(entries):
                struct.struct_type = position

        self._shift_raw_paths(target, tuple(path), index)
        self._mark_raw_dirty(target)
        self._add_seq += 1
        self._stage_raw(
            (target, tuple(path), "remove", self._add_seq), where,
            f"remove entry [{index}] of {len(entries) + 1}",
        )

    def _stage_raw(self, key: tuple, where: str, summary: str) -> None:
        """Stage a structural raw change under the ledger's ``(kind, key)`` key."""
        self._stage("raw", key, where or f"{key[0]}: {_render_raw_path(key[1])}", summary)

    def _raw_list(self, target: str, path: tuple) -> GffList:
        """The GFF list ``path`` names, for the structural raw edits."""
        tree = self.raw_tree(target)
        if tree is None:
            raise SaveEditError(f"{target} is not part of this save")
        entry = self._raw_entry(tree, path)
        if entry.type != GffType.LIST or not isinstance(entry.value, GffList):
            raise SaveEditError("only a list can gain or lose entries")
        return entry.value

    def _shift_raw_paths(self, target: str, list_path: tuple, removed: int) -> None:
        """Re-point the staged raw bookkeeping after an entry was removed.

        Deleting entry *k* renumbers everything after it, so a change staged
        against ``…[k+1]/Field`` now names a different struct — and, worse, could
        collide with a later edit to that same index. Rewriting the staged paths
        here (and dropping the ones that named the deleted entry) keeps the ledger,
        the revert-detection originals and the discard keys on the objects the user
        actually edited. The undo log needs no fixing: it replays in recorded
        order, so every command still meets the tree its path was captured against.
        """
        originals: dict[tuple, object] = {}
        for (resource, path), value in self._raw_originals.items():
            shifted = _shift_path(path, list_path, removed) if resource == target else path
            if shifted is not None:
                originals[(resource, shifted)] = value
        self._raw_originals = originals

        changes: dict[tuple[str, tuple], PendingChange] = {}
        for key, change in self._changes.items():
            if key[0] != "raw" or change.key[0] != target:
                changes[key] = change
                continue
            shifted = _shift_path(change.key[1], list_path, removed)
            if shifted is None:
                continue  # what it named went away with the entry
            new_key = (target, shifted) + tuple(change.key[2:])
            changes[("raw", new_key)] = _repointed(change, new_key)
        self._changes = changes

    # -- write ------------------------------------------------------------ #
    def _dirty_areas(self) -> set[str]:
        """Area resrefs (lower) whose ``.git`` a pending change touched."""
        return {
            change.key[0].lower()
            for change in self._changes.values()
            if change.kind == "store"
        } | self._raw_areas | self._edited_areas

    def _overrides(self) -> dict[tuple[str, int], bytes]:
        out = {(key, _GIT_RESTYPE): write_gff(self._areas[key]) for key in self._dirty_areas()}
        if self._char_dirty and self._module is not None:
            out[("module", _IFO_RESTYPE)] = write_gff(self._module)  # authoritative character
        for key in self._raw_dirty:  # anything else the raw screen edited
            tree = self._raw_trees.get(key)
            if tree is not None:
                out[(key[0], self._raw_types[key])] = write_gff(tree)
        return out

    def _file_overrides(self) -> dict[str, bytes]:
        """Non-ERF sibling files to write instead of copy (the edited player.bic)."""
        if self._char_dirty and self._bic is not None:
            return {"player.bic": write_gff(self._bic)}  # keep the mirror in sync
        return {}

    def save_as(
        self, dest_folder: Path, *, overwrite: bool = False, backup_dir: Path | None = None
    ) -> SaveGame:
        """Write the edited save to ``dest_folder`` and return it (verified).

        By default ``dest_folder`` must not exist (a brand-new save). With
        ``overwrite=True`` an existing save is replaced — but only after the edited
        save is fully written to a staging folder **and verified**, so a failure
        never harms the target. If ``backup_dir`` is given, the replaced save is
        moved there (timestamped) rather than deleted, so it stays recoverable.
        """
        if not self.has_edits:
            raise SaveEditError("no edits to save")
        if dest_folder.exists() and not overwrite:
            raise SaveEditError(f"destination already exists: {dest_folder}")

        staging = dest_folder.parent / f"{dest_folder.name}.vk-staging"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            self._write_save_to(staging)  # reads the source; dest untouched yet
            self._verify(SaveGame(folder=staging))
            if dest_folder.exists():  # commit: back up / remove the old, then swap in
                self._replace_existing(dest_folder, backup_dir)
            shutil.move(str(staging), str(dest_folder))
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return SaveGame(folder=dest_folder)

    def _write_save_to(self, folder: Path) -> None:
        """Materialise the edited save into a fresh ``folder`` (siblings + .sav)."""
        src_sav = self._save.sav_path
        file_overrides = self._file_overrides()
        folder.mkdir(parents=True)
        for item in self._save.folder.iterdir():
            if item.is_file() and item != src_sav and item.name not in file_overrides:
                shutil.copy2(item, folder / item.name)
        for name, data in file_overrides.items():
            (folder / name).write_bytes(data)
        rewrite_erf(src_sav, self._overrides(), folder / src_sav.name)

    @staticmethod
    def _replace_existing(dest_folder: Path, backup_dir: Path | None) -> None:
        if backup_dir is not None:
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest_folder), str(_free_backup(backup_dir, dest_folder.name)))
        else:
            shutil.rmtree(dest_folder)

    def _verify(self, new_save: SaveGame) -> None:
        """Confirm each edited resource/file in the new save matches what we wrote."""
        for (resref, res_type), expected in self._overrides().items():
            res = self._reader.find_resource(new_save.sav_path, resref, res_type=res_type)
            if res is None:
                raise SaveEditError(f"verify failed: {resref} missing from written save")
            if self._reader.read_resource_bytes(new_save.sav_path, res) != expected:
                raise SaveEditError(f"verify failed: {resref} bytes differ after write")
        for name, expected in self._file_overrides().items():
            path = new_save.folder / name
            if not path.is_file() or path.read_bytes() != expected:
                raise SaveEditError(f"verify failed: {name} differs after write")
