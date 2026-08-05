"""Module variables, party settings and companion detection."""

from __future__ import annotations

import pytest
from tests.test_save_editor import _make_char_save_with_details

from nwnfile.formats.gff import GffField, GffList, GffStruct, GffType
from nwnsaveeditor.save_editor import SaveEditError, SaveEditor
from nwnsaveeditor.world_state import (
    INT,
    LOCATION,
    OBJECT,
    STRING,
    Variable,
    matches,
    read_variables,
)


def _var(name: str, type_code: int, gff_type: GffType, value) -> GffStruct:
    return GffStruct(struct_type=0, fields={
        "Name": GffField(GffType.CEXOSTRING, name),
        "Type": GffField(GffType.DWORD, type_code),
        "Value": GffField(gff_type, value),
    })


@pytest.fixture
def editor(tmp_path) -> SaveEditor:
    """An editor over a save whose module.ifo really holds a VarTable.

    The table has to be written to disk, not just poked into the loaded tree:
    undo replays the command log from a clean reload, which would discard an
    in-memory-only injection.
    """
    seed = SaveEditor(_make_char_save_with_details(tmp_path))
    seed._module_tree().root.fields["VarTable"] = GffField(GffType.LIST, GffList([
        _var("QUEST_STAGE", INT, GffType.INT, 3),
        _var("PLAYER_TITLE", STRING, GffType.CEXOSTRING, "Hero"),
        _var("GOLEM_REF", OBJECT, GffType.DWORD, 6915),
    ]))
    seed.set_character_field("Gold", 1, where="Gold")  # so save_as has work to do
    return SaveEditor(seed.save_as(tmp_path / "with-vars"))


# -- reading ---------------------------------------------------------------- #
def test_variables_are_read_with_their_type(editor):
    variables = editor.module_variables()
    assert [v.name for v in variables] == ["QUEST_STAGE", "PLAYER_TITLE", "GOLEM_REF"]
    assert [v.type_name for v in variables] == ["int", "string", "object"]


def test_object_and_location_variables_are_not_editable():
    """They hold runtime handles — editing one points a script at nothing."""
    assert not Variable(0, "x", OBJECT, 1).editable
    assert not Variable(0, "x", LOCATION, 1).editable
    assert Variable(0, "x", INT, 1).editable
    assert "object ids" in Variable(0, "x", OBJECT, 1).why_locked


def test_a_module_with_no_variables_reads_as_empty(tmp_path):
    editor = SaveEditor(_make_char_save_with_details(tmp_path))
    editor._module_tree().root.fields.pop("VarTable", None)
    assert read_variables(editor._module_tree()) == []


def test_search_matches_name_or_value():
    variable = Variable(0, "QUEST_STAGE", INT, 3)
    assert matches(variable, "")
    assert matches(variable, "quest")
    assert matches(variable, "3")
    assert not matches(variable, "zzz")


# -- editing ---------------------------------------------------------------- #
def test_setting_a_variable_stages_it(editor):
    editor.set_variable(0, 7, where="QUEST_STAGE")
    change = editor.pending_changes()[0]
    assert change.kind == "variable"
    assert change.summary == "3→7"
    assert editor.module_variables()[0].value == 7


def test_returning_a_variable_to_its_original_clears_the_change(editor):
    editor.set_variable(0, 7, where="QUEST_STAGE")
    editor.set_variable(0, 3, where="QUEST_STAGE")
    assert not editor.has_edits


def test_a_variable_keeps_its_stored_type(editor):
    editor.set_variable(1, 12345, where="PLAYER_TITLE")
    assert editor.module_variables()[1].value == "12345", "a string stays a string"


def test_an_object_variable_refuses_to_be_edited(editor):
    with pytest.raises(SaveEditError, match="cannot be edited safely"):
        editor.set_variable(2, 1, where="GOLEM_REF")


def test_an_unknown_variable_index_is_rejected(editor):
    with pytest.raises(SaveEditError, match="no such module variable"):
        editor.set_variable(99, 1)


def test_a_variable_edit_undoes(editor):
    editor.set_variable(0, 7, where="QUEST_STAGE")
    editor.undo()
    assert editor.module_variables()[0].value == 3
    assert not editor.has_edits


def test_a_variable_edit_reaches_the_written_save(editor, tmp_path):
    from tests.test_save_editor import _ifo_char  # noqa: F401  (import guard)

    editor.set_variable(0, 7, where="QUEST_STAGE")
    new_save = editor.save_as(tmp_path / "out")
    written = SaveEditor(new_save).module_variables()
    assert written[0].value == 7


# -- module settings -------------------------------------------------------- #
def test_module_fields_report_only_what_the_module_has(editor):
    root = editor._module_tree().root
    root.fields["Mod_MaxHenchmen"] = GffField(GffType.BYTE, 1)
    fields = {f.field for f in editor.module_fields()}
    assert "Mod_MaxHenchmen" in fields
    assert "Mod_PartyControl" not in fields, "absent settings are not invented"


def test_setting_a_module_field_stages_and_undoes(editor):
    editor._module_tree().root.fields["Mod_MaxHenchmen"] = GffField(GffType.BYTE, 1)
    editor.set_module_field("Mod_MaxHenchmen", 4, where="Max henchmen")
    assert editor.pending_changes()[0].summary == "1→4"
    editor.undo()
    assert not editor.has_edits


def test_an_unknown_module_field_is_rejected(editor):
    with pytest.raises(SaveEditError, match="not an editable module setting"):
        editor.set_module_field("Mod_Nonsense", 1)


def test_a_module_field_the_save_lacks_is_rejected(editor):
    editor._module_tree().root.fields.pop("Mod_MaxHenchmen", None)
    with pytest.raises(SaveEditError, match="has no Mod_MaxHenchmen"):
        editor.set_module_field("Mod_MaxHenchmen", 4)


# -- the screen's search box ------------------------------------------------- #
def test_typing_in_the_search_does_not_throw_you_out_of_the_box(qtbot, tmp_path):
    """Searching rebuilds the variable list on every keystroke.

    A box built *inside* refresh() is destroyed by the very keystroke being typed
    into it — focus and the caret go with it, so the next letter lands nowhere.
    The box has to outlive a refresh, keep focus, and keep the cursor where the
    user left it. Owner-reported against Quests & World State.
    """
    from types import SimpleNamespace

    from PySide6.QtCore import Qt

    from nwnsaveeditor.ui.editor.screens.quests import QuestsScreen
    from nwnsaveeditor.ui.editor.window import SaveEditorWindow

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    seed = SaveEditor(_make_char_save_with_details(tmp_path))
    seed._module_tree().root.fields["VarTable"] = GffField(GffType.LIST, GffList([
        _var("QUEST_STAGE", INT, GffType.INT, 3),
        _var("PLAYER_TITLE", STRING, GffType.CEXOSTRING, "Hero"),
    ]))
    seed.set_character_field("Gold", 1, where="Gold")
    saved = seed.save_as(tmp_path / "with-vars-ui")

    window = SaveEditorWindow([saved], _Ctrl())
    qtbot.addWidget(window)
    screen = QuestsScreen(window)  # shown on its own so it can take focus
    qtbot.addWidget(screen)
    screen.show()
    qtbot.waitExposed(screen)

    box = screen._search
    box.setFocus()
    qtbot.waitUntil(lambda: box.hasFocus(), timeout=2000)

    qtbot.keyClicks(box, "quest")
    assert box.text() == "quest"
    assert box.hasFocus()
    assert box.cursorPosition() == len("quest")
    assert screen._filter == "quest"

    qtbot.keyClick(box, Qt.Key.Key_Backspace)
    assert box.text() == "ques"
    assert box.hasFocus()
    assert box.cursorPosition() == len("ques")


def test_the_search_box_survives_a_refresh_as_the_same_widget(qtbot, tmp_path):
    """The identity is the fix: a rebuilt box is a different, unfocused widget."""
    from types import SimpleNamespace

    from nwnsaveeditor.ui.editor.screens.quests import QuestsScreen
    from nwnsaveeditor.ui.editor.window import SaveEditorWindow

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    window = SaveEditorWindow([_make_char_save_with_details(tmp_path)], _Ctrl())
    qtbot.addWidget(window)
    screen = QuestsScreen(window)
    qtbot.addWidget(screen)
    before = screen._search
    screen.refresh()
    assert screen._search is before
    assert screen._search.parent() is not None  # still in the layout, not orphaned
