"""Whether a character meets a (prestige) class's requirements.

A prestige class names a ``PreReqTable`` in ``classes.2da`` — a ``CLS_PRES_*``
table of ``ReqType`` rows the game checks *at level-up*, never at load. So a save
can hold a character who never met them; this reads the same table the game does
so an editor can say which requirements are unmet before adding the class.

The requirement kinds and how they combine:

* ``BAB`` — a minimum base attack bonus.
* ``FEAT`` — a feat that must be held (each row is its own requirement).
* ``FEATOR`` — a run of consecutive rows is *one* requirement met by holding any
  one of the feats (the "any weapon focus" pattern).
* ``SKILL`` — a skill at a minimum rank.
* ``RACE`` — a run of rows is one requirement met by being any of those races.
* ``CLASSOR`` — a run of rows is one requirement met by having any of those classes.
* ``CLASSNOT`` — a class that must *not* be held.
* ``SPELL`` / ``VAR`` — the ability to cast a spell level, and a module script
  variable. Neither can be judged from the save alone, so they are reported as
  *unverifiable* rather than pass/fail: the game may still refuse the class.

Reading only, no Qt: the caller passes a :class:`CharacterSnapshot` and optional
id→name lookups for the messages.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


class _Reader(Protocol):
    def read_2da(self, name: str) -> dict[int, dict[str, str]] | None: ...


def _col(row: dict[str, str], name: str) -> str:
    for key, value in row.items():
        if key.lower() == name.lower():
            return value
    return ""


def _is_set(value: str) -> bool:
    return value not in ("", "****")


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class CharacterSnapshot:
    """The parts of a character a prestige requirement is judged against."""

    bab: int = 0
    feats: frozenset[int] = frozenset()
    skills: dict[int, int] = field(default_factory=dict)  # skill index -> rank
    race: int = -1
    class_ids: frozenset[int] = frozenset()


@dataclass(frozen=True)
class PrereqResult:
    """The outcome of checking a class's requirements against a character."""

    unmet: tuple[str, ...] = ()  # requirements the character fails (Strict blocks)
    unverifiable: tuple[str, ...] = ()  # SPELL / VAR — script- or spell-gated

    @property
    def ok(self) -> bool:
        """True when nothing the save can judge is unmet (unverifiable aside)."""
        return not self.unmet


_Namer = Callable[[int], str]


def _names(fn: _Namer | None, prefix: str) -> _Namer:
    return fn if fn is not None else (lambda i: f"{prefix}{i}")


def check_prerequisites(
    reader: _Reader,
    class_id: int,
    character: CharacterSnapshot,
    *,
    feat_name: _Namer | None = None,
    skill_name: _Namer | None = None,
    race_name: _Namer | None = None,
    class_name: _Namer | None = None,
) -> PrereqResult:
    """Which of ``class_id``'s prerequisites ``character`` does not meet.

    An empty :attr:`PrereqResult.unmet` means every requirement the save can judge
    is satisfied; ``unverifiable`` collects the ones it cannot (see the module doc).
    """
    classes = reader.read_2da("classes") or {}
    row = classes.get(class_id)
    if row is None:
        return PrereqResult()
    table_name = _col(row, "PreReqTable")
    if not _is_set(table_name):
        return PrereqResult()  # no requirement table -> nothing to meet
    table = reader.read_2da(table_name.lower()) or {}
    rows = [table[i] for i in sorted(table) if _is_set(_col(table[i], "ReqType"))]

    feat_n = _names(feat_name, "feat #")
    skill_n = _names(skill_name, "skill #")
    race_n = _names(race_name, "race #")
    class_n = _names(class_name, "class #")

    unmet: list[str] = []
    unverifiable: list[str] = []
    i = 0
    while i < len(rows):
        kind = _col(rows[i], "ReqType").upper()
        p1, p2 = _col(rows[i], "ReqParam1"), _col(rows[i], "ReqParam2")
        if kind in ("FEATOR", "CLASSOR", "RACE"):  # consecutive run = one OR group
            group = [rows[i]]
            while i + 1 < len(rows) and _col(rows[i + 1], "ReqType").upper() == kind:
                i += 1
                group.append(rows[i])
            ids = [_to_int(_col(r, "ReqParam1")) for r in group]
            if kind == "FEATOR":
                if not any(f in character.feats for f in ids):
                    unmet.append("One of: " + _join(ids, feat_n))
            elif kind == "CLASSOR":
                if not any(c in character.class_ids for c in ids):
                    unmet.append("One of these classes: " + _join(ids, class_n))
            else:  # RACE
                if character.race not in ids:
                    unmet.append("Race: " + _join(ids, race_n))
        elif kind == "BAB":
            need = _to_int(p1)
            if character.bab < need:
                unmet.append(f"Base attack bonus {need} (have {character.bab})")
        elif kind == "FEAT":
            fid = _to_int(p1)
            if fid not in character.feats:
                unmet.append(f"Feat: {feat_n(fid)}")
        elif kind == "SKILL":
            sid, need = _to_int(p1), _to_int(p2)
            have = character.skills.get(sid, 0)
            if have < need:
                unmet.append(f"{skill_n(sid)} {need} ranks (have {have})")
        elif kind == "CLASSNOT":
            cid = _to_int(p1)
            if cid in character.class_ids:
                unmet.append(f"Must not have {class_n(cid)}")
        elif kind == "SPELL":
            unverifiable.append(f"Able to cast level-{_to_int(p1)} spells")
        elif kind == "VAR":
            unverifiable.append(f"Module setting {p1} (script-controlled)")
        i += 1
    return PrereqResult(tuple(unmet), tuple(unverifiable))


def _join(ids: list[int], namer: _Namer, limit: int = 8) -> str:
    shown = ", ".join(namer(i) for i in ids[:limit])
    return shown + (f", … (+{len(ids) - limit} more)" if len(ids) > limit else "")
