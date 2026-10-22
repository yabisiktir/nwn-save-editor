"""Editing a CExoLocString in the Raw Data (GFF) editor.

Reported as "Edit value… does nothing" on an item's ``LocalizedName``: the screen
tried ``int()`` on the value, which raised inside a Qt slot and was swallowed. The
tests pin the fix at each layer — the session's validation, the dialog, and the
screen — plus the neighbouring field types that failed the same way.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialog

from nwnfile.formats.gff import (
    GffField,
    GffType,
    LocString,
    string_id_label,
)
from nwnsaveeditor.save_editor import SaveEditError, SaveEditor
from nwnsaveeditor.ui.editor.window import SaveEditorWindow
from tests.test_save_editor import _ifo_char, _make_char_save_with_details

_FIRST_NAME = (("Mod_PlayerList", 0), ("FirstName", None))


@pytest.fixture
def editor(tmp_path):
    return SaveEditor(_make_char_save_with_details(tmp_path))


def _name(editor) -> LocString:
    return editor.raw_tree("module.ifo").root.fields["Mod_PlayerList"].value.structs[0] \
        .fields["FirstName"].value


# -- LocString helpers ------------------------------------------------------- #
def test_string_ids_are_named_by_language_and_gender():
    assert string_id_label(0) == "English"
    assert string_id_label(1) == "English (feminine)"
    assert string_id_label(4) == "German"
    assert string_id_label(5) == "German (feminine)"
    assert string_id_label(262) == "Japanese"
    assert string_id_label(40) == "Language 20"  # an id this table does not know


def test_describe_shows_every_part_of_the_value():
    both = LocString(strref=12847, substrings=[(0, "Helm"), (2, "Helm FR")])
    assert both.describe() == "“Helm” + “Helm FR” + StrRef 12847"
    assert LocString(strref=7).describe() == "StrRef 7"
    assert LocString().describe() == "(empty)"


# -- the session ------------------------------------------------------------- #
def test_a_localized_string_is_edited_and_saved(tmp_path, editor):
    editor.set_raw_field("module.ifo", _FIRST_NAME, LocString(substrings=[(0, "Shortsword")]))

    [change] = editor.pending_changes()
    assert change.summary == "“Hero”→“Shortsword”"
    saved = editor.save_as(tmp_path / "out")
    name = _ifo_char(saved.sav_path).fields["FirstName"].value
    assert name.strref == -1 and name.substrings == [(0, "Shortsword")]


def test_the_original_save_is_untouched(tmp_path):
    save = _make_char_save_with_details(tmp_path)
    editor = SaveEditor(save)
    editor.set_raw_field("module.ifo", _FIRST_NAME, LocString(substrings=[(0, "Other")]))
    editor.save_as(tmp_path / "out")
    assert _ifo_char(save.sav_path).fields["FirstName"].value.text() == "Hero"


def test_plain_text_is_refused_rather_than_stored_as_a_strref(editor):
    """type(original)(value) used to build LocString(strref="text"), which only
    failed when the save was written."""
    with pytest.raises(SaveEditError):
        editor.set_raw_field("module.ifo", _FIRST_NAME, "Shortsword")
    assert _name(editor) == LocString(substrings=[(0, "Hero")])
    assert not editor.has_edits


@pytest.mark.parametrize("bad", [
    LocString(strref=-2),
    LocString(strref=0xFFFFFFFF),  # the "none" marker is -1 here, not this
    LocString(substrings=[(0, "a"), (0, "b")]),  # one language answering twice
    LocString(substrings=[(-1, "a")]),
])
def test_an_invalid_localized_string_is_refused(editor, bad):
    with pytest.raises(SaveEditError):
        editor.set_raw_field("module.ifo", _FIRST_NAME, bad)
    assert _name(editor).text() == "Hero"


def test_the_value_is_copied_so_the_caller_cannot_reach_the_tree(editor):
    mine = LocString(substrings=[(0, "Copy")])
    editor.set_raw_field("module.ifo", _FIRST_NAME, mine)
    mine.substrings[0] = (0, "Mutated afterwards")
    assert _name(editor).text() == "Copy"


def test_putting_the_original_back_removes_the_pending_change(editor):
    editor.set_raw_field("module.ifo", _FIRST_NAME, LocString(substrings=[(0, "Changed")]))
    assert editor.has_edits
    editor.set_raw_field("module.ifo", _FIRST_NAME, LocString(substrings=[(0, "Hero")]))
    assert not editor.has_edits


def test_only_the_edited_language_changes_on_disk(tmp_path, editor):
    """Text in another language, including bytes that are not valid UTF-8, must
    come through a save exactly as it went in."""
    name = _name(editor)
    name.substrings = [(0, "Hero"), (2, "H\udce9ro")]  # id 2 holds a lone 0xE9 byte
    editor.set_raw_field(
        "module.ifo", _FIRST_NAME,
        LocString(substrings=[(0, "Renamed"), (2, "H\udce9ro")]),
    )
    saved = editor.save_as(tmp_path / "out")
    after = _ifo_char(saved.sav_path).fields["FirstName"].value
    assert after.substrings == [(0, "Renamed"), (2, "H\udce9ro")]


def test_undo_and_discard_bring_the_original_back(editor):
    editor.set_raw_field("module.ifo", _FIRST_NAME, LocString(substrings=[(0, "Changed")]))
    assert editor.undo()
    assert _name(editor).text() == "Hero" and not editor.has_edits
    assert editor.redo()
    assert _name(editor).text() == "Changed"
    editor.discard()
    assert _name(editor).text() == "Hero"


# -- neighbouring types that failed the same way ----------------------------- #
def _inject(editor, label, gtype, value):
    player = editor.raw_tree("module.ifo").root.fields["Mod_PlayerList"].value.structs[0]
    player.fields[label] = GffField(gtype, value)
    return (("Mod_PlayerList", 0), (label, None))


@pytest.mark.parametrize(("gtype", "value"), [
    (GffType.BYTE, 256), (GffType.BYTE, -1), (GffType.WORD, 70000),
    (GffType.SHORT, 40000), (GffType.DWORD, -5), (GffType.INT, 2 ** 31),
    (GffType.DWORD64, -1), (GffType.INT64, 2 ** 63),
])
def test_an_integer_that_does_not_fit_its_field_is_refused(editor, gtype, value):
    """The writer packs with struct, so this used to surface only when saving."""
    path = _inject(editor, "Probe", gtype, 1)
    with pytest.raises(SaveEditError):
        editor.set_raw_field("module.ifo", path, value)
    assert not editor.has_edits


def test_a_wide_integer_and_a_float_keep_what_they_were_given(tmp_path, editor):
    wide = _inject(editor, "Wide", GffType.INT64, 1)
    ratio = _inject(editor, "Ratio", GffType.FLOAT, 1.0)
    editor.set_raw_field("module.ifo", wide, 2 ** 40)
    editor.set_raw_field("module.ifo", ratio, 0.75)
    saved = editor.save_as(tmp_path / "out")
    char = _ifo_char(saved.sav_path)
    assert char.fields["Wide"].value == 2 ** 40
    assert char.fields["Ratio"].value == 0.75


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_float_must_be_finite(editor, bad):
    path = _inject(editor, "Ratio", GffType.FLOAT, 1.0)
    with pytest.raises(SaveEditError):
        editor.set_raw_field("module.ifo", path, bad)


def test_a_binary_field_is_refused_not_filled_with_zero_bytes(editor):
    """bytes(4242) is 4,242 zero bytes."""
    path = _inject(editor, "Blob", GffType.VOID, b"\x01\x02")
    with pytest.raises(SaveEditError):
        editor.set_raw_field("module.ifo", path, 4242)
    assert not editor.has_edits


# -- the dialog -------------------------------------------------------------- #
@pytest.fixture
def make_dialog(qtbot):
    from nwnsaveeditor.ui.dialogs.locstring_edit_dialog import LocStringEditDialog

    def build(value, **kwargs):
        dialog = LocStringEditDialog("Item/LocalizedName", value, **kwargs)
        qtbot.addWidget(dialog)
        return dialog

    return build


def _type(dialog, text, row=0):
    dialog._rows[row].box.setPlainText(text)


def test_pressing_ok_without_typing_changes_nothing(make_dialog):
    original = LocString(strref=12847, substrings=[(0, "Helm of the Gladiator")])
    assert make_dialog(original).value() == original


def test_untouched_text_comes_back_exactly_as_read(make_dialog):
    """A box round-trips CRLF as LF and cannot hold undecodable bytes; neither may
    count as an edit, or opening and closing the dialog would rewrite the text."""
    original = LocString(substrings=[(0, "Line one\r\nLine two"), (2, "caf\udce9")])
    dialog = make_dialog(original)
    assert dialog.value() == original
    assert dialog._rows[1].lossy  # shown with a replacement character, and flagged


def test_typing_over_a_tlk_name_lets_go_of_its_strref(make_dialog):
    dialog = make_dialog(LocString(strref=12847, substrings=[(0, "Helm")]), tlk_text="Helm")
    assert not dialog._clear.isChecked()
    _type(dialog, "Crown")
    assert dialog._clear.isChecked() and not dialog._strref.isEnabled()
    assert dialog.value() == LocString(strref=-1, substrings=[(0, "Crown")])


def test_the_strref_can_be_kept_by_unticking(make_dialog):
    dialog = make_dialog(LocString(strref=12847, substrings=[(0, "Helm")]))
    _type(dialog, "Crown")
    dialog._clear.setChecked(False)
    assert dialog._strref.isEnabled()
    assert dialog.value() == LocString(strref=12847, substrings=[(0, "Crown")])


def test_a_strref_only_string_gains_text_in_english_when_typed_into(make_dialog):
    dialog = make_dialog(LocString(strref=12847))
    assert dialog.value() == LocString(strref=12847), "left alone it stays StrRef-only"
    _type(dialog, "Mine")
    assert dialog.value() == LocString(strref=-1, substrings=[(0, "Mine")])
    _type(dialog, "")  # typed and deleted again
    assert dialog.value() == LocString(strref=12847)


def test_a_value_without_a_strref_offers_no_checkbox(make_dialog):
    dialog = make_dialog(LocString(substrings=[(0, "Hero")]))
    assert dialog._clear.isHidden()
    _type(dialog, "Villain")
    assert dialog.value() == LocString(strref=-1, substrings=[(0, "Villain")])


def test_each_language_is_labelled_and_edited_on_its_own(make_dialog):
    dialog = make_dialog(LocString(substrings=[(0, "Sword"), (5, "Schwert")]))
    assert [string_id_label(r.string_id) for r in dialog._rows] == [
        "English", "German (feminine)"]
    _type(dialog, "Blade", row=0)
    assert dialog.value().substrings == [(0, "Blade"), (5, "Schwert")]


def test_non_ascii_text_carries_a_notice(make_dialog):
    dialog = make_dialog(LocString(substrings=[(0, "Sword")]))
    assert dialog._note.isHidden()
    _type(dialog, "Épée")
    assert not dialog._note.isHidden() and "UTF-8" in dialog._note.text()


def test_the_dialog_wears_the_editors_theme(make_dialog):
    """Dialogs that skip this draw the OS palette — unreadable in the other theme."""
    dialog = make_dialog(LocString(substrings=[(0, "Sword")]))
    assert "QPlainTextEdit" in dialog.styleSheet()


# -- the Raw Data screen ------------------------------------------------------ #
@pytest.fixture
def window(qtbot, tmp_path):
    saves = tmp_path / "saves"
    saves.mkdir()
    save = _make_char_save_with_details(saves, name="000001 - test")

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    win = SaveEditorWindow([save], _Ctrl())
    qtbot.addWidget(win)
    win._edit_toggle.setChecked(True)
    return win


@pytest.fixture
def raw(window):
    window._set_section("raw")
    return window._screens["raw"]


def _select(raw, label):
    from tests.test_save_editor_advanced import _find_scalar

    node = _find_scalar(raw, label)
    assert node is not None, label
    raw._tree.setCurrentItem(node)
    return node


class _FakeDialog:
    """Stands in for LocStringEditDialog (replace the class: patching __init__
    leaves the C++ half unbuilt and hangs a headless run)."""

    shown: list = []
    result: QDialog.DialogCode = QDialog.DialogCode.Accepted
    returns: LocString | None = None

    def __init__(self, description, value, *, tlk_text=None, parent=None):
        type(self).shown.append((description, value, tlk_text))

    def exec(self):
        return type(self).result

    def value(self):
        return type(self).returns


@pytest.fixture
def fake_dialog(monkeypatch):
    import nwnsaveeditor.ui.dialogs.locstring_edit_dialog as module

    _FakeDialog.shown = []
    _FakeDialog.result = QDialog.DialogCode.Accepted
    _FakeDialog.returns = None
    monkeypatch.setattr(module, "LocStringEditDialog", _FakeDialog)
    return _FakeDialog


def test_edit_value_opens_the_text_editor_on_a_localized_string(raw, fake_dialog):
    """The reported bug: nothing happened."""
    _select(raw, "FirstName")
    assert raw._edit_button.isEnabled()
    fake_dialog.returns = LocString(substrings=[(0, "Villain")])
    raw._edit_selected()

    assert len(fake_dialog.shown) == 1
    assert fake_dialog.shown[0][0].endswith("FirstName")
    [change] = raw._window.session().pending_changes()
    assert change.summary == "“Hero”→“Villain”"
    assert raw._tree.currentItem().text(2) == "Villain", "the tree shows the new text"


def test_cancelling_the_text_editor_changes_nothing(raw, fake_dialog):
    _select(raw, "FirstName")
    fake_dialog.result = QDialog.DialogCode.Rejected
    raw._edit_selected()
    assert not raw._window.session().has_edits


def test_ok_on_an_unchanged_string_stages_nothing(raw, fake_dialog):
    _select(raw, "FirstName")
    fake_dialog.returns = LocString(substrings=[(0, "Hero")])
    raw._edit_selected()
    assert not raw._window.session().has_edits


def test_a_refused_value_is_reported_not_swallowed(raw, fake_dialog, monkeypatch):
    import nwnsaveeditor.ui.editor.screens.raw as screen

    _select(raw, "FirstName")
    fake_dialog.returns = LocString(substrings=[(0, "a"), (0, "b")])
    told = []
    monkeypatch.setattr(screen.w, "message", lambda *a, **k: told.append(a[2:4]))
    raw._edit_selected()
    assert told and told[0][0] == "Raw edit failed" and "twice" in told[0][1]


def test_a_binary_field_says_so_instead_of_doing_nothing(raw, monkeypatch):
    import nwnsaveeditor.ui.editor.screens.raw as screen

    session = raw._window.session()
    player = session.raw_tree("module.ifo").root.fields["Mod_PlayerList"].value.structs[0]
    player.fields["Blob"] = GffField(GffType.VOID, b"\x01\x02")
    raw.refresh()
    _select(raw, "Blob")
    told = []
    monkeypatch.setattr(screen.w, "message", lambda *a, **k: told.append(a[2:4]))
    raw._edit_selected()
    assert told and told[0][0] == "Binary field"
    assert not session.has_edits


def test_a_float_field_keeps_its_decimals(raw, monkeypatch):
    import nwnsaveeditor.ui.editor.screens.raw as screen

    session = raw._window.session()
    player = session.raw_tree("module.ifo").root.fields["Mod_PlayerList"].value.structs[0]
    player.fields["Ratio"] = GffField(GffType.FLOAT, 0.75)
    raw.refresh()
    _select(raw, "Ratio")
    offered = []
    monkeypatch.setattr(
        screen, "_get_text", lambda _p, _t, current: (offered.append(current), ("0.5", True))[1])
    raw._edit_selected()
    assert offered == ["0.75"], "the text editor starts from the real value, not int(0.75)"
    assert player.fields["Ratio"].value == 0.5


def test_unreadable_number_text_is_reported_and_changes_nothing(raw, monkeypatch):
    import nwnsaveeditor.ui.editor.screens.raw as screen

    session = raw._window.session()
    player = session.raw_tree("module.ifo").root.fields["Mod_PlayerList"].value.structs[0]
    player.fields["Wide"] = GffField(GffType.INT64, 2 ** 40)
    raw.refresh()
    _select(raw, "Wide")
    told = []
    monkeypatch.setattr(screen, "_get_text", lambda *_a: ("lots", True))
    monkeypatch.setattr(screen.w, "message", lambda *a, **k: told.append(a[2]))
    raw._edit_selected()
    assert told == ["Not a number"]
    assert player.fields["Wide"].value == 2 ** 40 and not session.has_edits


def test_an_out_of_range_integer_is_reported_through_the_themed_box(raw, monkeypatch):
    import nwnsaveeditor.ui.dialogs.property_edit_dialog as ped
    import nwnsaveeditor.ui.editor.screens.raw as screen

    class _Dialog:
        def __init__(self, *a, **k):
            pass

        def setStyleSheet(self, _qss):  # noqa: N802 - Qt name
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def value(self):
            return 300

    monkeypatch.setattr(ped, "PropertyEditDialog", _Dialog)
    monkeypatch.setattr(screen.w, "style_dialog", lambda d: d)
    session = raw._window.session()
    player = session.raw_tree("module.ifo").root.fields["Mod_PlayerList"].value.structs[0]
    player.fields["Small"] = GffField(GffType.BYTE, 7)
    raw.refresh()
    _select(raw, "Small")
    told = []
    monkeypatch.setattr(screen.w, "message", lambda *a, **k: told.append(a[2:4]))
    raw._edit_selected()
    assert told and told[0][0] == "Raw edit failed" and "BYTE" in told[0][1]
    assert player.fields["Small"].value == 7


def test_a_strref_too_big_for_the_spin_box_is_kept_not_clamped(make_dialog):
    """QSpinBox is a signed 32-bit number; showing such a StrRef must not rewrite it."""
    huge = LocString(strref=0xF0000000, substrings=[(0, "Odd")])
    dialog = make_dialog(huge)
    assert not dialog._strref.isEnabled()
    assert dialog.value() == huge
    _type(dialog, "Even")  # typing lets go of it, as for any StrRef
    assert dialog.value() == LocString(strref=-1, substrings=[(0, "Even")])


def test_a_clear_the_user_chose_is_not_undone_by_the_text(make_dialog):
    dialog = make_dialog(LocString(strref=12847, substrings=[(0, "Helm")]))
    dialog._clear.click()  # the user's own decision
    assert dialog.value() == LocString(strref=-1, substrings=[(0, "Helm")])
    _type(dialog, "Crown")
    _type(dialog, "Helm")
    assert dialog._clear.isChecked(), "only a clear made by typing is handed back"
