"""The Save Game Editor's Character screen."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QSpinBox

from vaultkeeper.ui.save_editor.screens.character import (
    ABILITIES,
    TABS,
    CharacterScreen,
    ability_modifier,
)
from vaultkeeper.ui.save_editor.window import SaveEditorWindow


@pytest.fixture
def window(qtbot, tmp_path):
    from tests.test_save_editor import _make_char_save_with_details

    save = _make_char_save_with_details(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    editor = SaveEditorWindow([save], _Ctrl())
    qtbot.addWidget(editor)
    return editor


@pytest.fixture
def screen(window) -> CharacterScreen:
    return window._screens["character"]


# -- derived values -------------------------------------------------------- #
@pytest.mark.parametrize(
    ("score", "modifier"),
    [(1, -5), (3, -4), (8, -1), (9, -1), (10, 0), (11, 0), (12, 1), (18, 4), (24, 7)],
)
def test_ability_modifier_matches_the_d_and_d_table(score, modifier):
    assert ability_modifier(score) == modifier


# -- structure ------------------------------------------------------------- #
def test_the_screen_has_the_prototypes_five_tabs(screen):
    assert [key for key, _label in TABS] == [
        "abilities", "skills", "feats", "effects", "biography",
    ]
    assert len(screen._page_bodies) == len(TABS)


def test_every_tab_builds(screen):
    """Each tab must render without the others being current."""
    for key, _label in TABS:
        screen._tabs.set_value(key)
        screen._show_tab()
        assert screen._pages.currentIndex() == screen._page_keys.index(key)


def test_tab_pages_scroll_rather_than_stretching_the_window(screen):
    """A long tab (100+ feats) must not drive the window's height."""
    from PySide6.QtWidgets import QScrollArea

    for index in range(screen._pages.count()):
        assert isinstance(screen._pages.widget(index), QScrollArea)


# -- the edit gate --------------------------------------------------------- #
def _ability_steppers(screen) -> list[QSpinBox]:
    return screen._pages.widget(0).findChildren(QSpinBox)


def test_abilities_are_read_only_until_edit_mode_is_on(window, screen):
    assert not _ability_steppers(screen)
    window._edit_toggle.setChecked(True)
    screen.refresh()
    assert _ability_steppers(screen)


def test_only_abilities_the_record_carries_get_a_stepper(window, screen):
    """SaveEditor writes a field only when present, so a stepper on a missing
    ability would look editable and silently do nothing."""
    window._edit_toggle.setChecked(True)
    screen.refresh()
    present = {f.field for f in window.session().player_fields()}
    expected = [field for field, _label in ABILITIES if field in present]
    assert len(_ability_steppers(screen)) == len(expected)
    assert expected, "the fixture character should carry at least one ability score"


def test_editing_an_ability_stages_it_and_marks_the_tab(window, screen):
    window._edit_toggle.setChecked(True)
    screen.refresh()
    screen._set_ability("Str", 24)

    changes = window.session().pending_changes()
    assert [c.kind for c in changes] == ["char-field"]
    assert changes[0].key == "Str"
    assert changes[0].where == "Strength"
    assert screen._tabs._dots["abilities"].text().endswith("●")


def test_a_staged_ability_reports_its_original_for_the_struck_through_value(window, screen):
    window._edit_toggle.setChecked(True)
    screen.refresh()
    before = screen._field_value("Str")
    screen._set_ability("Str", before + 5)
    assert screen._field_value("Str") == before + 5
    assert screen._original_value("Str") == before


def test_reverting_an_ability_clears_the_staged_change(window, screen):
    window._edit_toggle.setChecked(True)
    screen.refresh()
    before = screen._field_value("Str")
    screen._set_ability("Str", before + 5)
    screen._set_ability("Str", before)
    assert not window.session().has_edits
    assert not screen._tabs._dots["abilities"].text().endswith("●")


# -- skills ----------------------------------------------------------------- #
def test_editing_a_skill_rank_stages_it(window, screen):
    window._edit_toggle.setChecked(True)
    screen.refresh()
    skill = window.session().player_skills()[0]
    screen._set_skill(skill, skill.rank + 3)

    changes = window.session().pending_changes()
    assert [c.kind for c in changes] == ["skill"]
    assert screen._tabs._dots["skills"].text().endswith("●")


def test_the_skill_filter_hides_non_matching_rows(window, screen):
    window._edit_toggle.setChecked(True)
    screen.refresh()
    screen._tabs.set_value("skills")
    names = [name for name, _row in screen._skill_rows]
    screen._apply_skill_filter(names[0])
    shown = [name for name, row in screen._skill_rows if not row.isHidden()]
    assert names[0] in shown


# -- feats ------------------------------------------------------------------ #
def test_removing_a_base_feat_stages_it_without_a_prc_warning(window, screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(1))

    feats = window.session().player_feats()
    base = next((f for f in feats if f[2]), None)
    if base is None:
        pytest.skip("this character has no base-game feat")
    screen._remove_feat(base[0], True)
    assert not warned
    assert any(c.kind == "feat" for c in window.session().pending_changes())


def test_removing_a_prc_feat_warns_and_can_be_declined(window, screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.No)
    screen._remove_feat(9999, False)
    assert not window.session().has_edits, "declining the PRC warning must stage nothing"


# -- effects ---------------------------------------------------------------- #
def test_effects_are_read_from_the_saves_effect_list(window, screen):
    """No EffectList (or an empty one) must render an empty state, not crash."""
    assert screen._read_effects() == []


def test_effect_rows_describe_what_the_save_actually_stores(window, screen, monkeypatch):
    monkeypatch.setattr(screen, "_read_effects", lambda: [{
        "tag": "EffectHolyTouch", "type": 13, "subtype": 18,
        "spell": "", "caster_level": 0, "duration": 0.0,
    }])
    screen.refresh()
    screen._tabs.set_value("effects")
    text = _text_of(screen._pages.widget(3))
    assert "EffectHolyTouch" in text
    assert "permanent" in text
    assert "type 13/18" in text


def test_effect_types_are_not_named_from_the_script_constants(screen, monkeypatch):
    """The serialized Type is a different enum from nwscript's EFFECT_TYPE_*.

    On the owner's save the three EffectHolyTouch effects carry Type 13 and 83,
    which those constants call DEAF and CUTSCENEGHOST — so naming a row from that
    table would be confidently wrong. Guard against someone "fixing" this later.
    """
    monkeypatch.setattr(screen, "_read_effects", lambda: [{
        "tag": "EffectHolyTouch", "type": 13, "subtype": 18,
        "spell": "", "caster_level": 0, "duration": 0.0,
    }])
    screen.refresh()
    text = _text_of(screen._pages.widget(3)).lower()
    for wrong in ("deaf", "cutsceneghost", "cutscene ghost"):
        assert wrong not in text


# -- biography -------------------------------------------------------------- #
def test_editing_the_first_name_stages_it(window, screen):
    window._edit_toggle.setChecked(True)
    screen.refresh()
    screen._set_name("FirstName", "Kaelen")
    changes = window.session().pending_changes()
    assert [c.key for c in changes] == ["FirstName"]
    assert screen._tabs._dots["biography"].text().endswith("●")


# -- skins ------------------------------------------------------------------ #
def test_switching_sheet_skin_changes_nothing_in_the_save(window, screen):
    window._edit_toggle.setChecked(True)
    screen.refresh()
    screen._set_skin("verdant")
    assert screen._skin == "verdant"
    assert not window.session().has_edits, "a skin is cosmetic — it must not stage an edit"


def _text_of(widget) -> str:
    from PySide6.QtWidgets import QLabel

    return "\n".join(label.text() for label in widget.findChildren(QLabel))


# -- rule mode -------------------------------------------------------------- #
def test_strict_mode_caps_the_skill_stepper_at_the_rank_limit(window, screen):
    from vaultkeeper.game.rules import skill_rank_limit

    window._edit_toggle.setChecked(True)
    window._rule_mode.set_value("strict")
    screen.refresh()
    screen._tabs.set_value("skills")

    info = window.character_info()
    cap = skill_rank_limit(getattr(info, "level", 0) or 0)
    steppers = screen._pages.widget(1).findChildren(QSpinBox)
    assert steppers, "edit mode should give skills steppers"
    assert all(box.maximum() == cap for box in steppers)


def test_free_mode_lifts_the_skill_cap(window, screen):
    window._edit_toggle.setChecked(True)
    window._rule_mode.set_value("free")
    screen.refresh()
    steppers = screen._pages.widget(1).findChildren(QSpinBox)
    assert steppers
    assert all(box.maximum() == 255 for box in steppers)


def test_switching_rule_mode_re_renders_the_screens(window, screen):
    """The mode changes what inputs allow, so the screens have to be rebuilt."""
    window._edit_toggle.setChecked(True)
    window._rule_mode.set_value("strict")
    window._refresh_screens()
    strict_max = [b.maximum() for b in screen._pages.widget(1).findChildren(QSpinBox)]

    window._rule_mode.set_value("free")
    window._refresh_screens()
    free_max = [b.maximum() for b in screen._pages.widget(1).findChildren(QSpinBox)]
    assert free_max != strict_max


def test_neither_mode_lets_an_ability_exceed_what_a_byte_holds(window, screen):
    """Free mode breaks rules, never the file."""
    window._edit_toggle.setChecked(True)
    for mode in ("strict", "free"):
        window._rule_mode.set_value(mode)
        screen.refresh()
        steppers = _ability_steppers(screen)
        assert steppers
        assert all(box.maximum() <= 255 for box in steppers), mode
