"""The add-a-class-level wizard (ui/dialogs/level_up_wizard.py).

Covers which steps appear for a given level, the live skill-point budget guard,
and that the wizard hands back only the choices the player actually made.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from nwnfile.level_up import LevelGains  # noqa: E402
from nwnsaveeditor.ui.dialogs.level_up_wizard import LevelUpWizard  # noqa: E402


class _Skill:
    def __init__(self, index: int, name: str, rank: int) -> None:
        self.index, self.name, self.rank = index, name, rank


def _gains(**over) -> LevelGains:
    base = dict(
        class_id=0, class_name="Barbarian", class_level=2, character_level=2,
        hit_die=12, bab_gain=1, fort_gain=1, ref_gain=0, will_gain=0,
        skill_point_base=4, granted_feats=(), general_feat=False,
        ability_increase=False, is_base_class=True, spellcaster=False,
    )
    base.update(over)
    return LevelGains(**base)


def test_plain_level_is_summary_only(qtbot):
    # No skill budget (int mod cancels base to 0 floor is 1, so force base 0),
    # no feat, no ability -> just the summary page.
    wiz = LevelUpWizard(
        _gains(skill_point_base=0), con_modifier=0, int_modifier=-5,
        new_total_level=2, skills=[_Skill(0, "Discipline", 3)],
    )
    qtbot.addWidget(wiz)
    # budget is max(1, 0-5)=1 -> a skill page still appears; only-summary needs 0 skills
    wiz2 = LevelUpWizard(
        _gains(), con_modifier=0, int_modifier=0, new_total_level=2, skills=[],
    )
    qtbot.addWidget(wiz2)
    assert len(wiz2.pageIds()) == 1


def test_skill_page_appears_with_a_budget(qtbot):
    wiz = LevelUpWizard(
        _gains(), con_modifier=0, int_modifier=1, new_total_level=2,
        skills=[_Skill(0, "Discipline", 3), _Skill(1, "Tumble", 0)], skill_cap=10,
    )
    qtbot.addWidget(wiz)
    assert len(wiz.pageIds()) == 2  # summary + skills
    assert wiz._skill_budget == 5  # base 4 + Int 1


def test_over_budget_blocks_completion(qtbot):
    wiz = LevelUpWizard(
        _gains(), con_modifier=0, int_modifier=1, new_total_level=2,
        skills=[_Skill(0, "Discipline", 3)], skill_cap=99,
    )
    qtbot.addWidget(wiz)
    page = wiz.page(wiz.pageIds()[1])
    wiz._skill_boxes[0].setValue(3 + 5)  # spend exactly the budget
    assert page.isComplete() and wiz._remaining() == 0
    wiz._skill_boxes[0].setValue(3 + 6)  # one over
    assert not page.isComplete() and wiz._remaining() == -1


def test_skill_allocations_reports_only_changes(qtbot):
    wiz = LevelUpWizard(
        _gains(), con_modifier=0, int_modifier=1, new_total_level=2,
        skills=[_Skill(0, "Discipline", 3), _Skill(1, "Tumble", 0)], skill_cap=99,
    )
    qtbot.addWidget(wiz)
    wiz._skill_boxes[0].setValue(5)  # +2 on Discipline
    # Tumble untouched -> not reported
    assert wiz.skill_allocations() == {0: 5}


def test_feat_page_only_when_a_feat_is_due(qtbot):
    without = LevelUpWizard(
        _gains(general_feat=False), con_modifier=0, int_modifier=-9,
        new_total_level=2, skills=[], feat_options=[(1, "Alertness")],
    )
    qtbot.addWidget(without)
    assert without.chosen_feat() is None and len(without.pageIds()) == 1

    with_feat = LevelUpWizard(
        _gains(general_feat=True), con_modifier=0, int_modifier=-9,
        new_total_level=3, skills=[], feat_options=[(1, "Alertness"), (6, "Cleave")],
        prc_feat_ids=frozenset({6}),
    )
    qtbot.addWidget(with_feat)
    assert len(with_feat.pageIds()) == 2
    assert with_feat.chosen_feat() is None  # defaults to 'pick later'
    with_feat._feat_group._tree.setCurrentItem(
        with_feat._feat_group._tree.topLevelItem(1)  # first real feat
    )
    assert with_feat.chosen_feat() == 1


def test_ability_page_only_when_an_ability_is_due(qtbot):
    wiz = LevelUpWizard(
        _gains(ability_increase=True), con_modifier=0, int_modifier=-9,
        new_total_level=4, skills=[], ability_scores={"Str": 16},
    )
    qtbot.addWidget(wiz)
    assert len(wiz.pageIds()) == 2
    assert wiz.chosen_ability() is None  # 'not now' is the default
    for field, btn in wiz._ability_choice._buttons:
        if field == "Str":
            btn.setChecked(True)
    assert wiz.chosen_ability() == "Str"
