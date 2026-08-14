"""Class-skill resolution + the rank cap that follows (nwnfile/class_skills.py)."""

from __future__ import annotations

from nwnfile.class_skills import class_skill_ids, skill_rank_cap


class _Reader:
    def __init__(self, tables):
        self.tables = tables

    def read_2da(self, name):
        return self.tables.get(name.lower())


def _reader():
    return _Reader({
        "classes": {
            1: {"Label": "Bard", "SkillsTable": "CLS_SKILL_BARD"},
            4: {"Label": "Fighter", "SkillsTable": "CLS_SKILL_FIGHT"},
            9: {"Label": "NoTable", "SkillsTable": "****"},
        },
        "cls_skill_bard": {
            0: {"SkillIndex": "1", "ClassSkill": "1"},   # Concentration = class
            1: {"SkillIndex": "2", "ClassSkill": "0"},   # DisableTrap = cross-class
            2: {"SkillIndex": "3", "ClassSkill": "1"},   # Discipline = class
        },
        "cls_skill_fight": {
            0: {"SkillIndex": "3", "ClassSkill": "1"},   # Discipline = class
            1: {"SkillIndex": "8", "ClassSkill": "1"},   # (something) = class
        },
    })


def test_collects_class_skills_across_the_characters_classes():
    ids = class_skill_ids(_reader(), [1, 4])
    assert ids == {1, 3, 8}  # Bard's 1,3 + Fighter's 3,8 (union), not the 0-marked 2


def test_a_single_class_only_sees_its_own():
    assert class_skill_ids(_reader(), [1]) == {1, 3}


def test_a_class_without_a_skills_table_contributes_nothing():
    assert class_skill_ids(_reader(), [9]) == set()


def test_an_unknown_class_id_is_ignored():
    assert class_skill_ids(_reader(), [999]) == set()


def test_no_reader_tables_yields_empty():
    assert class_skill_ids(_Reader({}), [1, 4]) == set()


def test_class_skill_caps_at_level_plus_three():
    assert skill_rank_cap(10, class_skill=True) == 13
    assert skill_rank_cap(1, class_skill=True) == 4


def test_cross_class_caps_at_half():
    assert skill_rank_cap(10, class_skill=False) == 6   # (10+3)//2
    assert skill_rank_cap(1, class_skill=False) == 2    # (1+3)//2
    assert skill_rank_cap(0, class_skill=False) == 1    # never below 1
