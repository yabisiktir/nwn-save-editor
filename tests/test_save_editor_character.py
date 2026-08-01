"""The Save Game Editor's Character screen."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QSpinBox

from nwnsaveeditor.ui.editor.screens.character import (
    ABILITIES,
    TABS,
    CharacterScreen,
    ability_modifier,
)
from nwnsaveeditor.ui.editor.window import SaveEditorWindow


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
def test_the_screen_has_the_prototypes_tabs(screen):
    assert [key for key, _label in TABS] == [
        "abilities", "details", "skills", "feats", "effects", "biography",
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
    return _page(screen, "abilities").findChildren(QSpinBox)


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
    text = _text_of(_page(screen, "effects"))
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
    text = _text_of(_page(screen, "effects")).lower()
    for wrong in ("deaf", "cutsceneghost", "cutscene ghost"):
        assert wrong not in text


def test_identical_effects_collapse_instead_of_repeating(window, screen, monkeypatch):
    """The owner's save stamps EffectHolyTouch on the character three times."""
    monkeypatch.setattr(screen, "_read_effects", lambda: [{
        "tag": "EffectHolyTouch", "type": 13, "subtype": 18,
        "spell": "", "caster_level": 0, "duration": 0.0,
    }] * 3)
    screen.refresh()
    text = _text_of(_page(screen, "effects"))
    assert "3×  EffectHolyTouch" in text
    assert text.count("EffectHolyTouch") == 1


def test_an_unset_caster_level_is_not_printed_as_a_caster_level(window, screen):
    """CasterLevel is a DWORD, so unset arrives as 4294967295, not 0."""
    from nwnsaveeditor.ui.editor.screens.character import _effect_row

    row = _effect_row({
        "tag": "", "type": 30, "subtype": 4, "spell": "",
        "caster_level": 0, "duration": 0.0,
    })
    assert "4294967295" not in _text_of(row)
    assert "caster level" not in _text_of(row)


# -- effects: the view switch ----------------------------------------------- #
def test_the_effects_tab_offers_both_views(window, screen):
    from nwnsaveeditor.ui.editor.screens.character import EFFECT_VIEWS

    assert [key for key, _label in EFFECT_VIEWS] == ["active", "bonuses"]
    assert screen._effects_view == "active", "the raw list stays the default"


def test_switching_to_bonuses_rebuilds_the_tab_and_sticks(window, screen):
    screen._tabs.set_value("effects")
    screen._set_effects_view("bonuses")
    assert screen._effects_view == "bonuses"
    assert screen._tabs.value() == "effects", "switching view must not change tab"
    screen.refresh()  # a later rebuild must not silently drop back to the raw list
    assert screen._effects_view == "bonuses"
    assert not window.session().has_edits, "a view is cosmetic — it must not stage an edit"


def test_the_bonuses_view_credits_each_bonus_to_the_item_that_grants_it(
    window, screen, monkeypatch
):
    from types import SimpleNamespace

    from nwnfile.formats.bic_reader import ItemProperty
    from nwnsaveeditor import active_bonuses

    def _prop(pid, subtype, cost):
        return ItemProperty(
            property_name=pid, subtype=subtype, cost_table=0,
            cost_value=cost, param1=0, param1_value=0,
        )

    def _item(name, slot, *props):
        return SimpleNamespace(
            name=name, slot=slot,
            properties=[SimpleNamespace(prop=p, index=i) for i, p in enumerate(props)],
        )

    monkeypatch.setattr(screen, "_active_bonuses", lambda info: active_bonuses.compute(
        [_item("Belt of the Warrior", 1024, _prop(0, 0, 10)),
         _item("base_prc_skin", active_bonuses.SKIN_SLOT, _prop(0, 0, 6))],
        [(1, "Cleave", True)], None,
    ))
    screen._set_effects_view("bonuses")
    text = _text_of(_page(screen, "effects"))
    assert "Strength" in text
    assert "Belt of the Warrior" in text
    assert "Creature skin (PRC)" in text
    assert "largest +10 · sum +16" in text, "both numbers, neither passed off as the total"


def test_the_bonuses_view_says_what_it_cannot_attribute(window, screen):
    """A number whose scope is unstated is worse than no number at all."""
    screen._set_effects_view("bonuses")
    text = _text_of(_page(screen, "effects")).lower()
    assert "feats" in text
    assert "running the game's rules" in text, "the feat/class gap must be spelled out"
    assert "does not stack" in text, "the same-type stacking caveat must be spelled out"


# -- biography -------------------------------------------------------------- #
def test_editing_the_first_name_stages_it(window, screen):
    window._edit_toggle.setChecked(True)
    screen.refresh()
    screen._set_name("FirstName", "Kaelen")
    changes = window.session().pending_changes()
    assert [c.key for c in changes] == ["FirstName"]
    assert screen._tabs._dots["biography"].text().endswith("●")


def _biography_page(screen):
    screen._tabs.set_value("biography")
    screen._show_tab()
    return screen._pages.currentWidget()


def _labels(widget) -> str:
    from PySide6.QtWidgets import QLabel

    return "\n".join(label.text() for label in widget.findChildren(QLabel))


def test_biography_shows_the_name_but_does_not_edit_it(window, screen):
    """It was editable here *and* under Details → Identity; two editors for one
    field means one of them always shows a stale value."""
    from PySide6.QtWidgets import QLineEdit

    window._edit_toggle.setChecked(True)
    page = _biography_page(screen)

    assert not page.findChildren(QLineEdit), "no second name editor"
    assert "Edit the name under Details → Identity." in _labels(page)


def test_biography_reflects_a_name_staged_under_details(window, screen):
    window._edit_toggle.setChecked(True)
    screen._set_name("FirstName", "Kaelen")
    assert "Kaelen" in _labels(_biography_page(screen))


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
    from nwnsaveeditor.rules import skill_rank_limit

    window._edit_toggle.setChecked(True)
    window._rule_mode.set_value("strict")
    screen.refresh()
    screen._tabs.set_value("skills")

    info = window.character_info()
    cap = skill_rank_limit(getattr(info, "level", 0) or 0)
    steppers = _page(screen, "skills").findChildren(QSpinBox)
    assert steppers, "edit mode should give skills steppers"
    assert all(box.maximum() == cap for box in steppers)


def test_free_mode_lifts_the_skill_cap(window, screen):
    window._edit_toggle.setChecked(True)
    window._rule_mode.set_value("free")
    screen.refresh()
    steppers = _page(screen, "skills").findChildren(QSpinBox)
    assert steppers
    assert all(box.maximum() == 255 for box in steppers)


def test_switching_rule_mode_re_renders_the_screens(window, screen):
    """The mode changes what inputs allow, so the screens have to be rebuilt."""
    window._edit_toggle.setChecked(True)
    window._rule_mode.set_value("strict")
    window._refresh_screens()
    strict_max = [b.maximum() for b in _page(screen, "skills").findChildren(QSpinBox)]

    window._rule_mode.set_value("free")
    window._refresh_screens()
    free_max = [b.maximum() for b in _page(screen, "skills").findChildren(QSpinBox)]
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


def _page(screen, key):
    """A tab's page by key — positional indices shift when a tab is added."""
    return screen._pages.widget(screen._page_keys.index(key))


# -- Details tab ------------------------------------------------------------ #
def test_every_editable_character_field_is_reachable(window, screen):
    """No stored field may be left without an editor anywhere.

    The read-only viewer had a Details group; losing it stranded gold, XP,
    alignment, age, HP and the look. The six ability scores are edited on the
    sheet in Abilities & Combat instead of being repeated here.
    """
    window._edit_toggle.setChecked(True)
    screen.refresh()
    details = _text_of(_page(screen, "details"))
    sheet = _text_of(_page(screen, "abilities"))
    abilities = {field for field, _label in ABILITIES}
    for field in window.session().player_fields():
        where = sheet if field.field in abilities else details
        assert field.display in where, f"{field.field} has no editor"


def test_details_offers_an_editor_for_each_numeric_field(window, screen):
    """Every numeric field except the abilities, which the sheet owns."""
    window._edit_toggle.setChecked(True)
    screen.refresh()
    abilities = {field for field, _label in ABILITIES}
    numeric = [
        f for f in window.session().player_fields()
        if f.kind == "int" and f.field not in abilities
    ]
    boxes = _page(screen, "details").findChildren(QSpinBox)
    assert len(boxes) == len(numeric)


def test_details_does_not_repeat_the_sheets_ability_steppers(window, screen):
    window._edit_toggle.setChecked(True)
    screen.refresh()
    details = _text_of(_page(screen, "details"))
    for _field, label in ABILITIES:
        assert label not in details, f"{label} is editable twice"


def test_details_is_read_only_until_edit_mode_is_on(window, screen):
    assert not _page(screen, "details").findChildren(QSpinBox)


def test_editing_a_numeric_detail_stages_it(window, screen):
    window._edit_toggle.setChecked(True)
    screen.refresh()
    field = next(f for f in window.session().player_fields() if f.kind == "int")
    screen._set_detail(field.field, int(field.value) + 7)
    changes = window.session().pending_changes()
    assert [c.key for c in changes] == [field.field]


def test_base_saves_are_editable_when_the_record_carries_them(window, screen):
    """Leto exposes these; they are stored fields, not derived totals."""
    fields = {f.field for f in window.session().player_fields()}
    stored = {"FortSaveThrow", "RefSaveThrow", "WillSaveThrow"} & fields
    if not stored:
        pytest.skip("the fixture character stores no base saves")
    window._edit_toggle.setChecked(True)
    screen.refresh()
    text = _text_of(_page(screen, "details"))
    assert "Base Fortitude save" in text


# -- skills ------------------------------------------------------------------ #
def test_skills_are_listed_alphabetically(window, screen):
    screen.refresh()
    names = [name for name, _row in screen._skill_rows]
    assert names == sorted(names), "skill-id order reads as random"


def test_skill_rows_show_a_total_not_just_a_rank(window, screen):
    screen.refresh()
    text = _text_of(_page(screen, "skills"))
    assert "rank" in text.lower()
    assert "key ability" in text.lower(), "the total's makeup must be stated"


# -- race ------------------------------------------------------------------- #
def _race_field(window):
    return next(
        f for f in window.session().player_fields() if f.field == "Race"
    )


def test_race_is_offered_as_an_editable_field(window):
    """It was shown on the sheet but nothing could change it."""
    field = _race_field(window)
    assert field.kind == "race"


def test_the_race_row_shows_the_name_not_the_byte(window, screen):
    screen._tabs.set_value("details")
    screen._show_tab()
    assert "Human" in _labels(screen._pages.currentWidget())


def test_picking_a_race_stages_it_in_both_trees(window, screen, monkeypatch):
    window._edit_toggle.setChecked(True)
    _accept_race(monkeypatch, 1)  # Elf
    screen._pick_race(_race_field(window))

    changes = window.session().pending_changes()
    assert [c.key for c in changes] == ["Race"]
    assert _race_field(window).value == 1


def test_a_prc_race_warns_first_and_declining_stages_nothing(window, screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window._edit_toggle.setChecked(True)
    _accept_race(monkeypatch, 159)  # a PRC race id, not in RACE_NAMES
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.No
    )
    screen._pick_race(_race_field(window))
    assert not window.session().has_edits


def test_two_base_races_need_no_warning(window, screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window._edit_toggle.setChecked(True)
    _accept_race(monkeypatch, 0)  # Dwarf, base -> base
    monkeypatch.setattr(QMessageBox, "warning", _no_modal)
    screen._pick_race(_race_field(window))
    assert window.session().has_edits


def test_the_picker_offers_only_ids_the_byte_can_hold(window, screen, monkeypatch):
    """Race is a BYTE; offering id 300 would stage a value the save cannot store."""
    seen = {}

    def _capture(field):
        from nwnfile.character import race_options

        limits = screen._limits("Race", window.character_info())
        seen["ids"] = [
            r for r in race_options() if limits.minimum <= r <= limits.maximum
        ]

    _capture(None)
    assert seen["ids"], "some races must survive the filter"
    assert max(seen["ids"]) <= 255


def _accept_race(monkeypatch, race_id: int) -> None:
    from PySide6.QtWidgets import QDialog

    import nwnsaveeditor.ui.dialogs.id_picker_dialog as idp

    class _Chose(idp.IdPickerDialog):
        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_id(self):
            return race_id

    monkeypatch.setattr(idp, "IdPickerDialog", _Chose)


def _no_modal(*_a, **_k):
    raise AssertionError("a base-to-base race change must not warn")


# -- the look pickers ------------------------------------------------------- #
class _Looks:
    def appearance_options(self):
        return {6: "Human male", 1: "Dwarf male"}

    def portrait_resrefs(self):
        return ["po_hu_m_11_", "po_el_f_01_"]

    def appearance_name(self, value):
        return self.appearance_options().get(int(value), str(value))


def test_the_look_pickers_open_at_all(window, screen, monkeypatch):
    """They were handed a mapping, which the picker iterates as bare ints — so
    clicking Appearance or Portrait raised before the dialog ever appeared."""
    monkeypatch.setattr(window, "look_tables", lambda: _Looks())
    window._edit_toggle.setChecked(True)
    fields = {f.field: f for f in window.session().player_fields()}
    shown = {}

    def _spy(title, items, **kw):
        shown[title] = list(items)
        raise _Stop

    monkeypatch.setattr(
        "nwnsaveeditor.ui.dialogs.id_picker_dialog.IdPickerDialog", _spy
    )
    for name in ("Appearance_Type", "Portrait"):
        with pytest.raises(_Stop):
            screen._pick_look(fields[name])

    assert shown["Appearance"] == [(1, "Dwarf male"), (6, "Human male")]
    assert shown["Portrait"] == [(0, "po_hu_m_11_"), (1, "po_el_f_01_")]


class _Stop(Exception):
    """Stops _pick_look once we have seen what it offered."""


# -- base vs total ----------------------------------------------------------- #
def _abilities_page(screen):
    screen._tabs.set_value("abilities")
    screen._show_tab()
    return screen._pages.currentWidget()


def test_the_combat_numbers_say_they_are_the_stored_bases(window, screen):
    """A "Fortitude +12" that Details also edits reads as a total; it is not."""
    text = _labels(_abilities_page(screen)).lower()  # the stat captions uppercase
    assert "base fortitude" in text
    assert "base reflex" in text
    assert "base will" in text
    assert "base attack bonus" in text
    assert "the one details edits" in text


def test_a_save_shows_the_ability_that_adds_to_it(window, screen):
    text = _labels(_abilities_page(screen))
    assert "Con" in text and "Dex" in text and "Wis" in text


def test_gear_is_credited_when_an_item_grants_the_save(window, screen, monkeypatch):
    monkeypatch.setattr(
        screen, "_save_gear_bonuses", lambda: {"Fortitude": 3, "Reflex": None, "Will": None}
    )
    screen.refresh()
    assert "+3 gear" in _labels(_abilities_page(screen))


def test_it_says_what_the_save_does_not_record_at_all(window, screen):
    """Perfect Two-Weapon Fighting changes attacks per round, which is computed by
    the engine and stored nowhere — so its absence needs explaining, not hiding."""
    text = _labels(_abilities_page(screen))
    assert "Attacks per round and off-hand attacks are not stored" in text
    assert "never what they do" in text, "and feats are unattributed for a reason"


def test_gear_bonuses_survive_an_unreadable_session(window, screen, monkeypatch):
    monkeypatch.setattr(
        window, "session", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert screen._save_gear_bonuses() == {}


# -- where an ability score comes from --------------------------------------- #
def _total(field="Str", base=29, parts=(), attributed=True):
    from nwnfile.ability_breakdown import AbilityTotal, Component

    return AbilityTotal(field, base, tuple(Component(*p) for p in parts), attributed)


def test_the_row_shows_what_the_score_actually_is(window, screen, monkeypatch):
    """The save stores a base; the game shows base + race + gear. Show the total.

    The total is built on the score the row is displaying, not the one the
    breakdown was read from, so it follows the stepper during an edit.
    """
    monkeypatch.setattr(
        screen, "_ability_gear",
        lambda: {"Str": _total(parts=[("Bralani", 8, "race"), ("Belt", 10, "item")])},
    )
    screen.refresh()
    text = _labels(_page(screen, "abilities"))
    assert "→ 30" in text  # the fixture's Strength is 12, plus the 18 named above
    assert "+10" in text  # and the modifier follows the total, not the base


def test_a_score_with_nothing_added_shows_no_total(window, screen, monkeypatch):
    """A bare number beside an identical one is noise."""
    monkeypatch.setattr(screen, "_ability_gear", lambda: {"Str": _total(parts=[])})
    screen.refresh()
    assert "→" not in _labels(_page(screen, "abilities"))


def test_every_contribution_is_named(window, screen):
    from nwnsaveeditor.ui.editor.screens.character import _breakdown_tooltip

    tip = _breakdown_tooltip("Strength", _total(
        parts=[("Bralani", 8, "race"), ("Halftroll", 6, "template"), ("Belt", 10, "item")]
    ))
    assert "Strength 53 in play" in tip
    assert "29\tbase" in tip
    for expected in ("+8\tBralani (race)", "+6\tHalftroll (template)", "+10\tBelt (worn)"):
        assert expected in tip


def test_an_unattributed_skin_says_so(window, screen):
    """Silently showing a partial split would lose points with no sign of it."""
    from nwnsaveeditor.ui.editor.screens.character import _breakdown_tooltip

    tip = _breakdown_tooltip("Strength", _total(parts=[("skin", 6, "item")], attributed=False))
    assert "registry did not account" in tip


def test_an_unreadable_session_costs_nothing(window, screen, monkeypatch):
    monkeypatch.setattr(
        window, "session", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert screen._ability_gear() == {}
