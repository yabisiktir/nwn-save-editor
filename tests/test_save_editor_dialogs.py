"""The Save Game Editor's Open Save and Save dialogs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel

from nwnsaveeditor.ui.editor.dialogs import (
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


#: Whether clearing a folder's write bit actually stops anything here.
#:
#: The check under test is ``os.access(folder, W_OK)``, a POSIX permission
#: question. Windows has no directory write bit for ``chmod`` to clear and
#: answers that call True however the folder is marked, so the test could only
#: fail there — and root ignores the bit as well. Evaluated defensively because
#: ``os.geteuid`` **does not exist** on Windows, and this runs at import time:
#: calling it unguarded took the whole module down before collection, which is
#: how one platform-specific line failed an entire CI job.
_WRITE_BIT_MEANS_SOMETHING = not sys.platform.startswith("win") and not (
    hasattr(os, "geteuid") and os.geteuid() == 0
)


@pytest.mark.skipif(
    not _WRITE_BIT_MEANS_SOMETHING,
    reason="needs a filesystem where clearing a folder's write bit denies writing",
)
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


# -- a big folder loads progressively -------------------------------------- #
def _many_good_saves(tmp_path, count):
    from nwnsaveeditor.save_game import SaveGame
    from tests.test_save_game import _sav_with_areas

    saves = []
    for i in range(count):
        folder = tmp_path / f"{i:06d} - save {i}"
        folder.mkdir()
        _sav_with_areas(folder, area_count=1)
        saves.append(SaveGame(folder=folder))
    return saves


def test_only_a_screenful_is_decoded_before_the_dialog_paints(qtbot, tmp_path):
    from nwnsaveeditor.ui.editor.dialogs import _EAGER_ROWS

    saves = _many_good_saves(tmp_path, _EAGER_ROWS + 6)
    dialog = OpenSaveDialog(saves)
    qtbot.addWidget(dialog)
    # The first screenful is resolved up front; the rest start pending so the
    # dialog can appear at once on a folder of hundreds.
    assert all(s.resolved for s in dialog._states[:_EAGER_ROWS])
    assert all(not s.resolved for s in dialog._states[_EAGER_ROWS:])
    # A pending row shows a loading cue, not an empty or scary one.
    assert "Reading…" in _texts(dialog)


def test_the_pump_resolves_the_rest_and_names_their_modules(qtbot, tmp_path):
    from nwnsaveeditor.ui.editor.dialogs import _EAGER_ROWS

    saves = _many_good_saves(tmp_path, _EAGER_ROWS + 6)
    dialog = OpenSaveDialog(saves)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: all(s.resolved for s in dialog._states), timeout=2000)
    assert all(s.module == "Test Module" for s in dialog._states)
    assert "Reading…" not in _texts(dialog)
    # A module named only after the pump is still searchable.
    dialog._apply_filter("test module")
    assert all(not row.isHidden() for _h, row, _s in dialog._rows)


def test_a_healthy_save_past_the_screenful_becomes_openable_after_the_pump(
    qtbot, tmp_path
):
    from nwnsaveeditor.ui.editor.dialogs import _EAGER_ROWS

    # Fill the first screenful with corrupt saves and put the only good one
    # beyond it, so nothing is openable until the pump reaches it.
    saves = []
    for i in range(_EAGER_ROWS):
        good = _many_good_saves(tmp_path, 1)[0]
        good.folder.rename(good.folder.parent / f"corrupt-{i}")
        from nwnsaveeditor.save_game import SaveGame

        folder = tmp_path / f"corrupt-{i}"
        (next(folder.glob("*.sav"))).write_bytes(b"corrupt")
        saves.append(SaveGame(folder=folder))
    good = _many_good_saves(tmp_path, 1)[0]
    saves.append(good)

    dialog = OpenSaveDialog(saves)
    qtbot.addWidget(dialog)
    assert dialog.selected_save() is None  # every resolved save so far is corrupt
    assert not dialog._open.isEnabled()

    qtbot.waitUntil(lambda: dialog._chosen is not None, timeout=2000)
    assert dialog.selected_save().folder == good.folder
    assert dialog._open.isEnabled()


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


# -- what opening the dialog is allowed to cost ---------------------------- #
def test_listing_saves_does_not_read_area_names(tmp_path, monkeypatch):
    """The Open dialog shows a save's *module*, never its areas.

    Naming areas costs one archive lookup per area, per save, and this list is
    built before the dialog can paint — which is what made opening it hang. If a
    future change drops the read_area_names=False here, this fails rather than
    quietly costing seconds again.
    """
    from nwnsaveeditor import save_game
    from tests.test_save_game import _sav_with_areas

    calls = 0
    original = save_game._read_area_name

    def counting(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(save_game, "_read_area_name", counting)

    saves = []
    for i in range(3):
        folder = tmp_path / f"00000{i} - save {i}"
        folder.mkdir()
        _sav_with_areas(folder, area_count=10)
        saves.append(save_game.SaveGame(folder=folder))

    states = [inspect_save(save) for save in saves]

    assert calls == 0, f"the Open list named areas {calls} times"
    # and it still shows what it is supposed to show
    assert [s.module for s in states] == ["Test Module"] * 3
    assert all(s.state == "normal" for s in states)


def test_the_open_dialog_still_names_each_module(qtbot, tmp_path):
    """The end the person actually sees: a real dialog, listing real module names."""
    from nwnsaveeditor.save_game import SaveGame
    from tests.test_save_game import _sav_with_areas

    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    _sav_with_areas(folder, area_count=4)

    dialog = OpenSaveDialog([SaveGame(folder=folder)], None)
    qtbot.addWidget(dialog)
    assert "Test Module" in _texts(dialog)


def test_opening_a_save_still_gets_named_areas(tmp_path):
    """The lean read must not leak into the screens: once a save is opened, the
    area list carries real names, not the resrefs it falls back to."""
    from nwnsaveeditor.save_game import SaveGame
    from tests.test_save_game import _sav_with_areas

    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    _sav_with_areas(folder, area_count=3)
    save = SaveGame(folder=folder)

    inspect_save(save)  # the dialog measures it first, memoizing a lean read
    info = save.module_info()  # then a screen asks for the full one
    assert [name for _resref, name in info.areas] == [
        "The area00 Room", "The area01 Room", "The area02 Room"
    ]
