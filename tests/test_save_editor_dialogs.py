"""The Save Game Editor's Open Save and Save dialogs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel

from vaultkeeper.ui.save_editor.dialogs import (
    OpenSaveDialog,
    SaveDialog,
    _human_size,
    inspect_save,
)


def _texts(widget) -> str:
    return "\n".join(label.text() for label in widget.findChildren(QLabel))


# -- measuring a save's state ---------------------------------------------- #
def test_a_readable_writable_save_is_normal(tmp_path):
    from tests.test_save_editor import _make_char_save

    state = inspect_save(_make_char_save(tmp_path))
    assert state.state == "normal"
    assert state.action_label == "Open"
    assert state.openable
    assert state.size > 0


def test_an_undecodable_save_is_corrupt(tmp_path):
    """'Corrupt' is measured — the .sav's module.ifo genuinely will not decode."""
    from tests.test_save_editor import _make_char_save

    save = _make_char_save(tmp_path)
    save.sav_path.write_bytes(b"not an ERF at all")

    state = inspect_save(save)
    assert state.state == "corrupt"
    assert not state.openable


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores the write bit")
def test_an_unwritable_save_folder_is_readonly(tmp_path):
    from tests.test_save_editor import _make_char_save

    save = _make_char_save(tmp_path)
    save.folder.chmod(0o500)
    try:
        state = inspect_save(save)
        assert state.state == "readonly"
        assert state.openable, "read-only still opens, it just cannot be overwritten"
        assert state.action_label == "Open read-only"
    finally:
        save.folder.chmod(0o700)


def test_human_size_reads_in_the_right_unit():
    assert _human_size(2048) == "2 KB"
    assert _human_size(5 << 20) == "5 MB"
    assert _human_size(3 << 30) == "3.0 GB"


# -- the Open dialog -------------------------------------------------------- #
@pytest.fixture
def saves(tmp_path):
    from tests.test_save_editor import _make_char_save

    good = _make_char_save(tmp_path, name="000001 - good")
    broken = _make_char_save(tmp_path, name="000002 - broken")
    broken.sav_path.write_bytes(b"corrupt")
    return [good, broken]


def test_the_open_dialog_lists_every_save(qtbot, saves):
    dialog = OpenSaveDialog(saves)
    qtbot.addWidget(dialog)
    text = _texts(dialog)
    assert "000001 - good" in text
    assert "000002 - broken" in text


def test_a_corrupt_save_is_shown_but_cannot_be_chosen(qtbot, saves):
    dialog = OpenSaveDialog(saves)
    qtbot.addWidget(dialog)
    assert "corrupt" in _texts(dialog)

    broken = next(s for s in dialog._states if s.state == "corrupt")
    dialog._choose(broken)
    assert dialog.selected_save().name != "000002 - broken"
    assert dialog._open.isEnabled(), "the healthy save is still selected"


def test_the_first_healthy_save_is_preselected(qtbot, saves):
    dialog = OpenSaveDialog(saves)
    qtbot.addWidget(dialog)
    assert dialog.selected_save().name == "000001 - good"


def test_the_open_button_is_disabled_when_nothing_can_be_opened(qtbot, saves):
    for save in saves:
        save.sav_path.write_bytes(b"corrupt")
    dialog = OpenSaveDialog(saves)
    qtbot.addWidget(dialog)
    assert dialog.selected_save() is None
    assert not dialog._open.isEnabled()


def test_the_search_filters_the_list(qtbot, saves):
    dialog = OpenSaveDialog(saves)
    qtbot.addWidget(dialog)
    dialog._apply_filter("broken")
    visible = [row for _h, row, _s in dialog._rows if not row.isHidden()]
    assert len(visible) == 1


# -- the Save dialog -------------------------------------------------------- #
def _save_dialog(qtbot, **overrides):
    kwargs = dict(
        mode="new", save_name="000001 - test", default_name="test (edited)",
        change_count=3, undone_count=0, rule_mode="strict",
        backup_dir=Path("/tmp/vaultkeeper_backups"),
    )
    kwargs.update(overrides)
    dialog = SaveDialog(**kwargs)
    qtbot.addWidget(dialog)
    return dialog


def test_new_mode_promises_the_original_is_untouched(qtbot):
    dialog = _save_dialog(qtbot, mode="new")
    text = _texts(dialog)
    assert "Save as a new file" in text
    assert "original file is left untouched" in text
    assert dialog._commit.text() == "Write new file"
    assert dialog.new_name() == "test (edited)"


def test_overwrite_mode_names_the_file_it_replaces(qtbot):
    dialog = _save_dialog(qtbot, mode="overwrite")
    text = _texts(dialog)
    assert "Overwrite this save" in text
    assert "000001 - test will be rewritten in place" in text
    assert dialog._commit.text() == "Overwrite save"


def test_the_writing_list_reports_what_will_and_will_not_be_written(qtbot):
    dialog = _save_dialog(qtbot, change_count=4, undone_count=2)
    text = _texts(dialog)
    assert "Changes to write" in text and "4" in text
    assert "Undone (not written)" in text and "2" in text


def test_commit_is_disabled_with_nothing_to_write(qtbot):
    dialog = _save_dialog(qtbot, change_count=0)
    assert not dialog._commit.isEnabled()


def test_commit_is_disabled_without_a_new_file_name(qtbot):
    dialog = _save_dialog(qtbot, mode="new")
    assert dialog._commit.isEnabled()
    dialog._name_edit.setText("   ")
    assert not dialog._commit.isEnabled()


def test_the_backup_path_and_its_guarantee_are_shown_when_backing_up(qtbot):
    dialog = _save_dialog(qtbot, mode="overwrite")
    assert dialog._backup.isChecked(), "backing up is the default"
    text = _texts(dialog)
    assert "vaultkeeper_backups" in text
    assert "verified" in text
    assert not dialog._no_backup_warning.isVisible()


def test_unchecking_the_backup_warns_it_cannot_be_undone(qtbot):
    dialog = _save_dialog(qtbot, mode="overwrite")
    dialog.show()
    dialog._backup.setChecked(False)
    assert dialog._no_backup_warning.isVisible()
    assert "cannot be undone" in _texts(dialog)
    assert not dialog.backup_wanted()


def test_free_rule_mode_carries_its_warning(qtbot):
    strict = _save_dialog(qtbot, rule_mode="strict")
    assert not strict._free_warning.isVisible()
    assert "Strict — derived values recomputed" in _texts(strict)

    free = _save_dialog(qtbot, rule_mode="free")
    free.show()
    assert free._free_warning.isVisible()
    assert "Free — raw values written as entered" in _texts(free)
    assert "may clamp or reject" in _texts(free)


def test_review_changes_closes_without_writing(qtbot):
    dialog = _save_dialog(qtbot)
    dialog._on_review()
    assert dialog.review_requested
    assert dialog.result() == SaveDialog.DialogCode.Rejected
