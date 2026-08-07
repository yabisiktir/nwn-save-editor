"""The Save Game Editor shell: sections, the edit gate, and committing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nwnsaveeditor.ui.editor import sections as sec
from nwnsaveeditor.ui.editor.window import (
    SaveEditorWindow,
    _base_name,
    _next_save_folder,
)


@pytest.fixture
def window(qtbot, tmp_path):
    """The editor over one synthetic save with an editable character."""
    from tests.test_save_editor import _make_char_save_with_details

    save = _make_char_save_with_details(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    editor = SaveEditorWindow([save], _Ctrl())
    qtbot.addWidget(editor)
    return editor


# -- helpers -------------------------------------------------------------- #
def test_base_name_drops_the_games_numeric_prefix():
    assert _base_name("000014 - Auto Save") == "Auto Save"
    assert _base_name("quicksave") == "quicksave"  # no prefix -> unchanged


def test_next_save_folder_picks_the_first_free_number(tmp_path):
    (tmp_path / "000001 - a").mkdir()
    (tmp_path / "000003 - c").mkdir()
    assert _next_save_folder(tmp_path, "new").name == "000002 - new"


# -- sections ------------------------------------------------------------- #
def test_every_section_has_a_nav_row_and_a_screen(window):
    for section in sec.SECTIONS:
        assert section.key in window._nav_rows
        assert window._screens[section.key] is not None  # built on demand


def test_advanced_sections_are_grouped_last():
    """The assertion is that the advanced screens come last, not that there are
    exactly two — the set has grown and shrunk since the original design."""
    keys = [s.key for s in sec.SECTIONS]
    advanced = [s.key for s in sec.SECTIONS if s.advanced]
    assert {"raw", "backups"} <= set(advanced)
    assert keys[-len(advanced):] == advanced, "advanced sections sit at the end"


def test_area_contents_sits_after_party_in_the_sidebar():
    """A design review moved Area Contents below Party & Campaign."""
    keys = [s.key for s in sec.SECTIONS]
    assert keys.index("area") > keys.index("party")


def test_every_section_explains_itself(window):
    for section in sec.SECTIONS:
        assert sec.SECTION_BLURBS.get(section.key), f"{section.key} has no blurb"


def test_selecting_a_section_switches_the_stack_and_the_nav(window):
    window._set_section("spellbook")
    assert window._stack.currentWidget() is window._screens["spellbook"]
    assert window._nav_rows["spellbook"].isChecked()
    assert not window._nav_rows["character"].isChecked()


# -- the edit gate -------------------------------------------------------- #
def test_edit_off_hides_the_footer_and_inerts_the_commit_buttons(window):
    window.show()
    assert not window._footer.isVisible()
    assert not window._save_new_btn.isEnabled()
    assert not window._overwrite_btn.isEnabled()


def test_edit_on_shows_the_footer_but_commit_still_needs_a_change(window):
    window.show()
    window._edit_toggle.setChecked(True)
    assert window._footer.isVisible()
    assert window._edit_toggle.text() == "Editing ✓"
    # Edit mode alone stages nothing, so there is still nothing to write.
    assert not window._save_new_btn.isEnabled()

    window._ensure_session().set_character_field("Gold", 4242)
    window._refresh_pending()
    assert window._save_new_btn.isEnabled()
    assert window._overwrite_btn.isEnabled()


def test_a_staged_change_lights_its_sections_dot_only(window):
    window._edit_toggle.setChecked(True)
    window._ensure_session().set_character_field("Gold", 999)
    window._refresh_pending()
    assert window._nav_rows["character"]._dot.isVisibleTo(window)
    assert not window._nav_rows["inventory"]._dot.isVisibleTo(window)


def test_the_footer_counts_changes_and_samples_up_to_three(window):
    window._edit_toggle.setChecked(True)
    session = window._ensure_session()
    # Offset each field from what it already holds — writing a field's current
    # value back is a no-op the session drops (revert detection).
    for field in ("Gold", "Str", "GoodEvil"):
        current = next(f for f in session.player_fields() if f.field == field)
        session.set_character_field(field, int(current.value) + 1)
    session.set_character_name("FirstName", "Kaelen")
    window._refresh_pending()
    assert window._pending_caption.text() == "PENDING CHANGES (4)"
    assert window._pending_samples.count() == 3, "the design shows at most 3 samples"


def test_change_kinds_map_onto_real_sections():
    """A kind mapped to a section that doesn't exist would silently lose its dot."""
    keys = {s.key for s in sec.SECTIONS}
    for kind in ("char-field", "skill", "feat", "spell", "property", "store", "add-item"):
        assert sec.section_for_kind(kind) in keys
    assert sec.section_for_kind("not-a-kind") is None


# -- discarding ----------------------------------------------------------- #
def test_leaving_edit_mode_with_changes_asks_first(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window._edit_toggle.setChecked(True)
    window._ensure_session().set_character_field("Gold", 7)
    window._refresh_pending()

    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(1) or QMessageBox.StandardButton.Cancel,
    )
    window._edit_toggle.setChecked(False)
    assert asked, "turning Edit off with staged changes must prompt"
    assert window._edit_toggle.isChecked(), "cancelling keeps the user in edit mode"
    assert window._session.has_edits


def test_discarding_drops_the_changes_and_clears_the_dots(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window._edit_toggle.setChecked(True)
    window._ensure_session().set_character_field("Gold", 7)
    window._refresh_pending()

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard
    )
    window._discard_all()
    assert not window._session.has_edits
    assert window._pending_caption.text() == "PENDING CHANGES (0)"
    assert not window._nav_rows["character"]._dot.isVisibleTo(window)


# -- committing ----------------------------------------------------------- #
def test_save_as_new_writes_a_new_save_and_leaves_the_original(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    from tests.test_save_editor import _ifo_char

    original = window._current
    original_bytes = original.sav_path.read_bytes()

    window._edit_toggle.setChecked(True)
    window._ensure_session().set_character_field("Gold", 4242)
    window._refresh_pending()

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    _stub_save_dialog(monkeypatch, name="Shell Edit")
    window._save_as_new()

    new_folder = next(p for p in tmp_path.iterdir() if p.name.endswith("Shell Edit"))
    assert _ifo_char(next(new_folder.glob("*.sav"))).fields["Gold"].value == 4242
    assert original.sav_path.read_bytes() == original_bytes, "original was modified"
    assert window._current.folder == new_folder, "the new save becomes the selection"
    # Screens read through session(), so one exists again as soon as they render
    # the newly selected save. What matters is that nothing is left staged.
    assert not window._session.has_edits
    assert window._pending_caption.text() == "PENDING CHANGES (0)"


def _stub_save_dialog(monkeypatch, *, name: str = "Edited", backup: bool = True):
    """Stand in for the modal Save dialog.

    Any test that reaches a commit path must do this: an unstubbed modal blocks
    the run forever instead of failing it.
    """
    from PySide6.QtWidgets import QDialog

    class _Dialog:
        review_requested = False

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def new_name(self):
            return name

        def backup_wanted(self):
            return backup

    monkeypatch.setattr("nwnsaveeditor.ui.editor.dialogs.SaveDialog", _Dialog)
    return _Dialog
