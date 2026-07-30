"""The Save Game Editor's advanced screens: Raw Data (GFF) and Backups & Diff."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from vaultkeeper.ui.save_editor.window import SaveEditorWindow

_ROLE = Qt.ItemDataRole.UserRole


@pytest.fixture
def window(qtbot, tmp_path):
    from tests.test_save_editor import _make_char_save_with_details

    saves = tmp_path / "saves"
    saves.mkdir()
    save = _make_char_save_with_details(saves, name="000001 - test")

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    editor = SaveEditorWindow([save], _Ctrl())
    qtbot.addWidget(editor)
    return editor


def _texts(widget) -> str:
    return "\n".join(label.text() for label in widget.findChildren(QLabel))


# -- Raw Data --------------------------------------------------------------- #
@pytest.fixture
def raw(window):
    return window._screens["raw"]


def test_the_raw_tree_lists_the_resources_top_level_fields(raw):
    labels = [
        raw._tree.topLevelItem(i).text(0) for i in range(raw._tree.topLevelItemCount())
    ]
    assert "Mod_PlayerList" in labels


def test_containers_expand_lazily(raw):
    """A save's tree is far too large to build eagerly."""
    node = next(
        raw._tree.topLevelItem(i) for i in range(raw._tree.topLevelItemCount())
        if raw._tree.topLevelItem(i).text(0) == "Mod_PlayerList"
    )
    assert node.childCount() == 1 and node.child(0).text(0) == "…"

    raw._tree.expandItem(node)
    assert node.child(0).text(0) == "[0]"
    assert node.child(0).text(1) == "struct"


def test_a_scalar_shows_its_type_and_value(raw):
    node = _find_scalar(raw, "Gold")
    assert node is not None
    assert node.text(1) in {"dword", "int"}
    assert node.text(2).isdigit()


def test_editing_is_gated_on_edit_mode(window, raw):
    node = _find_scalar(raw, "Gold")
    raw._tree.setCurrentItem(node)
    assert not raw._edit_button.isEnabled()

    window._edit_toggle.setChecked(True)
    raw._tree.setCurrentItem(_find_scalar(raw, "Gold"))
    assert raw._edit_button.isEnabled()


def test_a_container_cannot_be_edited(window, raw):
    window._edit_toggle.setChecked(True)
    node = next(
        raw._tree.topLevelItem(i) for i in range(raw._tree.topLevelItemCount())
        if raw._tree.topLevelItem(i).text(0) == "Mod_PlayerList"
    )
    raw._tree.setCurrentItem(node)
    assert not raw._edit_button.isEnabled(), "a list has no single value to set"


def test_a_raw_edit_stages_as_raw(window, raw):
    window._edit_toggle.setChecked(True)
    session = window.session()
    path = (("Mod_PlayerList", 0), ("Gold", None))
    session.set_raw_field("module.ifo", path, 4242, where="raw gold")
    window.notify_changed()

    change = window.session().pending_changes()[0]
    assert change.kind == "raw"
    assert change.summary.endswith("→4242")


def test_a_raw_edit_will_not_change_a_fields_type(window):
    from vaultkeeper.game.save_editor import SaveEditError

    session = window.session()
    path = (("Mod_PlayerList", 0), ("Gold", None))
    with pytest.raises(SaveEditError):
        session.set_raw_field("module.ifo", path, "not a number", where="bad")


def test_a_raw_edit_refuses_a_container(window):
    from vaultkeeper.game.save_editor import SaveEditError

    session = window.session()
    with pytest.raises(SaveEditError, match="scalar"):
        session.set_raw_field("module.ifo", (("Mod_PlayerList", None),), 1)


def test_the_filter_hides_non_matching_top_level_fields(raw):
    raw._apply_filter("Mod_PlayerList")
    visible = [
        raw._tree.topLevelItem(i) for i in range(raw._tree.topLevelItemCount())
        if not raw._tree.topLevelItem(i).isHidden()
    ]
    assert [node.text(0) for node in visible] == ["Mod_PlayerList"]


# -- Backups & Diff --------------------------------------------------------- #
@pytest.fixture
def backups_screen(window):
    return window._screens["backups"]


def test_with_no_backups_the_screen_explains_how_they_appear(backups_screen):
    assert backups_screen.backups() == []
    assert "No backups yet" in _texts(backups_screen)


def test_an_overwrite_shows_up_as_a_backup(window, backups_screen):
    window._edit_toggle.setChecked(True)
    session = window.session()
    session.set_character_field("Gold", 4242, where="Gold")
    save = window.save
    session.save_as(
        save.folder, overwrite=True,
        backup_dir=save.folder.parent.parent / "vaultkeeper_backups",
    )
    backups_screen.refresh()

    assert len(backups_screen.backups()) == 1
    assert "000001 - test" in _texts(backups_screen)


def test_diffing_a_backup_reports_the_edited_field(window, backups_screen):
    window._edit_toggle.setChecked(True)
    session = window.session()
    session.set_character_field("Gold", 4242, where="Gold")
    save = window.save
    session.save_as(
        save.folder, overwrite=True,
        backup_dir=save.folder.parent.parent / "vaultkeeper_backups",
    )
    backups_screen.refresh()
    backups_screen._run_diff()

    assert backups_screen._diff is not None
    assert not backups_screen._diff.is_empty
    text = _texts(backups_screen)
    assert "Gold" in text
    assert "4242" in text


def test_restoring_adds_a_new_save_without_replacing_anything(
    window, backups_screen, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    window._edit_toggle.setChecked(True)
    session = window.session()
    session.set_character_field("Gold", 4242, where="Gold")
    save = window.save
    saves_dir = save.folder.parent
    session.save_as(
        save.folder, overwrite=True,
        backup_dir=saves_dir.parent / "vaultkeeper_backups",
    )
    backups_screen.refresh()
    before = {p.name for p in saves_dir.iterdir()}

    # Yes confirms the restore. The switch that follows asks its own question with
    # Discard/Cancel, so this answer declines it and the old save stays selected —
    # which is the case that used to leave the window with no save at all.
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    backups_screen._restore_selected()

    after = {p.name for p in saves_dir.iterdir()}
    assert len(after) == len(before) + 1, "restored alongside, not over"
    assert before <= after, "nothing that existed was removed"
    assert backups_screen.backups(), "the backup itself is kept"
    assert window.save is not None, "a save is still selected"


def test_declining_to_drop_edits_keeps_the_current_save_selected(window, monkeypatch):
    """add_save nulls the selection before switching; if the switch is declined the
    window must not be left with no save at all."""
    from PySide6.QtWidgets import QMessageBox

    from tests.test_save_editor import _make_char_save_with_details

    window._edit_toggle.setChecked(True)
    window.session().set_character_field("Gold", 99, where="Gold")
    original = window.save

    other = _make_char_save_with_details(
        window.save.folder.parent, name="000009 - other"
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel
    )
    window.add_save(other)

    assert window.save is original, "the declined switch left the old save selected"
    assert window.session().has_edits, "and kept the staged edits"


def _find_scalar(raw, label: str):
    """Expand down to a named scalar under the player struct."""
    for index in range(raw._tree.topLevelItemCount()):
        node = raw._tree.topLevelItem(index)
        if node.text(0) != "Mod_PlayerList":
            continue
        raw._tree.expandItem(node)
        player = node.child(0)
        raw._tree.expandItem(player)
        for i in range(player.childCount()):
            child = player.child(i)
            if child.text(0) == label:
                return child
    return None
