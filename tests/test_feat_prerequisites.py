"""Feat prerequisite checking (nwnfile/feat_prerequisites.py)."""

from __future__ import annotations

from nwnfile.feat_prerequisites import FeatSnapshot, meets_prerequisites


class _Reader:
    def __init__(self, rows):
        self.tables = {"feat": rows}

    def read_2da(self, name):
        return self.tables.get(name.lower())


def _feat(**cols):
    base = {c: "****" for c in (
        "MINATTACKBONUS", "MINSTR", "MINDEX", "MINCON", "MININT", "MINWIS", "MINCHA",
        "PREREQFEAT1", "PREREQFEAT2", "OrReqFeat0", "OrReqFeat1", "OrReqFeat2",
        "OrReqFeat3", "OrReqFeat4", "REQSKILL", "ReqSkillMinRanks", "REQSKILL2",
        "ReqSkillMinRanks2", "MinLevel", "MinFortSave", "PreReqEpic",
    )}
    base.update({k: str(v) for k, v in cols.items()})
    return _Reader({50: base})


def _char(**kw):
    return FeatSnapshot(**kw)


def test_unknown_feat_is_available():
    assert meets_prerequisites(_Reader({}), 50, _char())


def test_min_attack_bonus():
    r = _feat(MINATTACKBONUS=4)
    assert not meets_prerequisites(r, 50, _char(bab=3))
    assert meets_prerequisites(r, 50, _char(bab=4))


def test_min_ability():
    r = _feat(MINSTR=13)
    assert not meets_prerequisites(r, 50, _char(abilities={"Str": 12}))
    assert meets_prerequisites(r, 50, _char(abilities={"Str": 13}))


def test_required_feats_are_all_needed():
    r = _feat(PREREQFEAT1=28, PREREQFEAT2=6)  # Great Cleave: Cleave + Power Attack
    assert not meets_prerequisites(r, 50, _char(feats=frozenset({28})))
    assert meets_prerequisites(r, 50, _char(feats=frozenset({28, 6})))


def test_or_group_needs_one():
    r = _feat(OrReqFeat0=90, OrReqFeat1=94)
    assert not meets_prerequisites(r, 50, _char(feats=frozenset()))
    assert meets_prerequisites(r, 50, _char(feats=frozenset({94})))


def test_skill_rank_requirement():
    r = _feat(REQSKILL=3, ReqSkillMinRanks=5)
    assert not meets_prerequisites(r, 50, _char(skills={3: 4}))
    assert meets_prerequisites(r, 50, _char(skills={3: 5}))


def test_epic_requires_level_21():
    r = _feat(PreReqEpic=1)
    assert not meets_prerequisites(r, 50, _char(level=20))
    assert meets_prerequisites(r, 50, _char(level=21))


def test_min_level_and_fort():
    assert not meets_prerequisites(_feat(MinLevel=6), 50, _char(level=5))
    assert not meets_prerequisites(_feat(MinFortSave=10), 50, _char(fort_save=9))
    assert meets_prerequisites(_feat(MinLevel=6, MinFortSave=10), 50,
                               _char(level=6, fort_save=10))
