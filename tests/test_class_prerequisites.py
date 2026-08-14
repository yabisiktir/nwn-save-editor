"""Prestige-class requirement checking (nwnfile/class_prerequisites.py)."""

from __future__ import annotations

from nwnfile.class_prerequisites import (
    CharacterSnapshot,
    check_prerequisites,
)


class _Reader:
    def __init__(self, tables):
        self.tables = tables

    def read_2da(self, name):
        return self.tables.get(name.lower())


def _reader(pres_rows):
    return _Reader({
        "classes": {50: {"Label": "Test", "PreReqTable": "CLS_PRES_TEST"}},
        "cls_pres_test": {i: r for i, r in enumerate(pres_rows)},
    })


def _row(kind, p1, p2="****"):
    return {"ReqType": kind, "ReqParam1": str(p1), "ReqParam2": str(p2)}


def _char(**kw):
    return CharacterSnapshot(**kw)


def test_no_prereq_table_means_no_requirements():
    reader = _Reader({"classes": {50: {"PreReqTable": "****"}}})
    assert check_prerequisites(reader, 50, _char()).ok


def test_bab_requirement():
    reader = _reader([_row("BAB", 7)])
    assert not check_prerequisites(reader, 50, _char(bab=6)).ok
    assert check_prerequisites(reader, 50, _char(bab=7)).ok


def test_a_required_feat_must_be_held():
    reader = _reader([_row("FEAT", 26)])
    res = check_prerequisites(reader, 50, _char(feats=frozenset()))
    assert not res.ok and "feat #26" in res.unmet[0]
    assert check_prerequisites(reader, 50, _char(feats=frozenset({26}))).ok


def test_feator_run_is_one_or_group():
    reader = _reader([_row("FEATOR", 90), _row("FEATOR", 94), _row("FEATOR", 95)])
    # holding none fails as a single "one of" requirement
    res = check_prerequisites(reader, 50, _char(feats=frozenset()))
    assert len(res.unmet) == 1 and res.unmet[0].startswith("One of:")
    # holding any one satisfies it
    assert check_prerequisites(reader, 50, _char(feats=frozenset({94}))).ok


def test_skill_rank_requirement():
    reader = _reader([_row("SKILL", 29, 9)])  # skill 29 at 9 ranks
    assert not check_prerequisites(reader, 50, _char(skills={29: 8})).ok
    assert check_prerequisites(reader, 50, _char(skills={29: 9})).ok


def test_race_run_is_one_or_group():
    reader = _reader([_row("RACE", 1), _row("RACE", 4)])
    assert not check_prerequisites(reader, 50, _char(race=6)).ok
    assert check_prerequisites(reader, 50, _char(race=4)).ok


def test_classnot_must_be_absent():
    reader = _reader([_row("CLASSNOT", 247)])
    assert not check_prerequisites(reader, 50, _char(class_ids=frozenset({247}))).ok
    assert check_prerequisites(reader, 50, _char(class_ids=frozenset({1}))).ok


def test_classor_needs_one_of():
    reader = _reader([_row("CLASSOR", 3), _row("CLASSOR", 8)])
    assert not check_prerequisites(reader, 50, _char(class_ids=frozenset({1}))).ok
    assert check_prerequisites(reader, 50, _char(class_ids=frozenset({8}))).ok


def test_spell_and_var_are_unverifiable_not_failures():
    reader = _reader([_row("SPELL", 3), _row("VAR", "X2_AllowFoo", 0)])
    res = check_prerequisites(reader, 50, _char())
    assert res.ok  # neither blocks
    assert len(res.unverifiable) == 2
    assert any("level-3 spells" in u for u in res.unverifiable)
    assert any("script-controlled" in u for u in res.unverifiable)


def test_names_are_used_in_messages():
    reader = _reader([_row("FEAT", 26)])
    res = check_prerequisites(
        reader, 50, _char(), feat_name=lambda i: f"Weapon Focus {i}"
    )
    assert "Weapon Focus 26" in res.unmet[0]
