"""The Save Game Editor's advanced screens: Raw Data (GFF) and Backups & Diff."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from nwnsaveeditor.ui.editor.window import SaveEditorWindow

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
    from nwnsaveeditor.save_editor import SaveEditError

    session = window.session()
    path = (("Mod_PlayerList", 0), ("Gold", None))
    with pytest.raises(SaveEditError):
        session.set_raw_field("module.ifo", path, "not a number", where="bad")


def test_a_raw_edit_refuses_a_container(window):
    from nwnsaveeditor.save_editor import SaveEditError

    session = window.session()
    with pytest.raises(SaveEditError, match="scalar"):
        session.set_raw_field("module.ifo", (("Mod_PlayerList", None),), 1)


# -- Raw Data: list structure ----------------------------------------------- #
def _find_list(raw, label: str):
    """The list node named ``label`` under the player struct, expanded."""
    node = _find_scalar(raw, label)
    raw._tree.expandItem(node)
    return node


def _feat_ids(window):
    player = window.session().raw_tree("module.ifo").root
    feats = player.fields["Mod_PlayerList"].value.structs[0].fields["FeatList"]
    return [s.fields["Feat"].value for s in feats.value.structs]


@pytest.fixture
def yes(monkeypatch):
    """Answer every confirmation with Yes — an unstubbed modal hangs the run."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )


def test_list_buttons_are_gated_on_edit_mode(window, raw):
    node = _find_list(raw, "FeatList")
    raw._tree.setCurrentItem(node)
    assert not raw._buttons["blank"].isEnabled()

    window._edit_toggle.setChecked(True)
    node = _find_list(raw, "FeatList")
    raw._tree.setCurrentItem(node)
    assert raw._buttons["blank"].isEnabled()
    assert raw._buttons["duplicate"].isEnabled(), "the list has entries to copy"
    assert not raw._buttons["remove"].isEnabled(), "the list itself is not an entry"
    assert not raw._buttons["edit"].isEnabled()

    raw._tree.setCurrentItem(node.child(1))  # an entry
    assert raw._buttons["remove"].isEnabled()
    assert raw._buttons["duplicate"].isEnabled()


def test_a_scalar_offers_no_list_buttons(window, raw):
    window._edit_toggle.setChecked(True)
    raw._tree.setCurrentItem(_find_scalar(raw, "Gold"))
    assert raw._buttons["edit"].isEnabled()
    assert not any(raw._buttons[k].isEnabled() for k in ("blank", "duplicate", "remove"))


def test_adding_a_blank_entry_seeds_it_and_says_so(window, raw):
    window._edit_toggle.setChecked(True)
    before = _feat_ids(window)
    raw._tree.setCurrentItem(_find_list(raw, "FeatList"))
    raw._add_blank()

    assert _feat_ids(window) == before + [0]  # seeded: the sibling's field, zeroed
    assert "seeded" in raw._note.text()
    change = window.session().pending_changes()[-1]
    assert change.kind == "raw" and "seeded from [0]" in change.summary


def test_duplicating_an_entry_copies_it(window, raw):
    window._edit_toggle.setChecked(True)
    before = _feat_ids(window)
    node = _find_list(raw, "FeatList")
    raw._tree.setCurrentItem(node.child(2))
    raw._duplicate()

    assert _feat_ids(window) == before + [before[2]]
    assert "copy of [2]" in raw._note.text()


def test_removing_an_entry_confirms_first(window, raw, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window._edit_toggle.setChecked(True)
    before = _feat_ids(window)
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No,
    )
    node = _find_list(raw, "FeatList")
    raw._tree.setCurrentItem(node.child(0))
    raw._remove_selected()

    assert asked and "moves up one place" in asked[0]
    assert _feat_ids(window) == before, "declining changes nothing"


def test_removing_an_entry_stages_and_reveals_the_list(window, raw, yes):
    window._edit_toggle.setChecked(True)
    before = _feat_ids(window)
    node = _find_list(raw, "FeatList")
    raw._tree.setCurrentItem(node.child(0))
    raw._remove_selected()

    assert _feat_ids(window) == before[1:]
    assert "moved up one" in raw._note.text()
    # the rebuilt tree is back on the list, expanded — not collapsed to the root
    current = raw._tree.currentItem()
    assert current.text(0) == "FeatList" and current.isExpanded()
    assert current.childCount() == len(before) - 1


def test_a_new_entry_is_revealed_in_the_rebuilt_tree(window, raw):
    window._edit_toggle.setChecked(True)
    raw._tree.setCurrentItem(_find_list(raw, "FeatList"))
    raw._duplicate()
    current = raw._tree.currentItem()
    assert current.text(0) == "[3]"  # selected, and its parent expanded to show it


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


# -- keeping your place in the tree ----------------------------------------- #
def _top(raw, label):
    return next(
        raw._tree.topLevelItem(i) for i in range(raw._tree.topLevelItemCount())
        if raw._tree.topLevelItem(i).text(0) == label
    )


def _open_to_gold(raw):
    """Expand Mod_PlayerList → [0] and select the character's Gold field."""
    players = _top(raw, "Mod_PlayerList")
    raw._tree.expandItem(players)
    character = players.child(0)
    raw._tree.expandItem(character)
    gold = next(
        character.child(i) for i in range(character.childCount())
        if character.child(i).text(0) == "Gold"
    )
    raw._tree.setCurrentItem(gold)
    return players, character, gold


def test_an_edit_leaves_the_tree_open_where_it_was(window, raw):
    """refresh() rebuilds the whole tree, so without this every edit collapsed it
    and threw you back to the top, several expansions from what you just changed."""
    window._edit_toggle.setChecked(True)
    players, character, gold = _open_to_gold(raw)
    _kind, path, _entry = gold.data(0, _ROLE)

    window.session().set_raw_field("module.ifo", path, 4321, where="Gold")
    raw.refresh()

    players = _top(raw, "Mod_PlayerList")
    assert players.isExpanded(), "the list you opened is still open"
    assert players.child(0).isExpanded(), "and so is the struct inside it"
    current = raw._tree.currentItem()
    assert current is not None and current.data(0, _ROLE)[1] == path, "still selected"
    assert current.text(2) == "4321", "showing the new value"


def test_a_collapsed_tree_stays_collapsed(raw):
    raw.refresh()
    players = _top(raw, "Mod_PlayerList")
    assert not players.isExpanded()


def test_switching_resource_does_not_carry_the_old_expansion_over(window, raw):
    """The paths belong to the resource they came from; another resource's tree
    must not be forced open at whatever happens to share a label."""
    _open_to_gold(raw)
    targets = [t for t in raw._targets() if t != "module.ifo"]
    if not targets:
        pytest.skip("this save has a single resource")
    raw._choose_target(targets[0])
    assert raw._target == targets[0]


# -- double-click ------------------------------------------------------------ #
def test_double_clicking_a_scalar_opens_the_editor(window, raw, monkeypatch):
    window._edit_toggle.setChecked(True)
    opened = []
    monkeypatch.setattr(raw, "_edit_selected", lambda: opened.append(1))
    node = _find_scalar(raw, "Gold")
    raw._on_double_click(node, 0)

    assert opened, "a double-click is how a tree row is edited everywhere else"
    assert raw._tree.currentItem() is node, "and it selects what you clicked"


def test_double_clicking_a_container_does_not_open_the_editor(window, raw, monkeypatch):
    window._edit_toggle.setChecked(True)
    opened = []
    monkeypatch.setattr(raw, "_edit_selected", lambda: opened.append(1))
    raw._on_double_click(_top(raw, "Mod_PlayerList"), 0)
    assert not opened, "a list expands on double-click; there is no value to edit"


# -- themed prompts ---------------------------------------------------------- #
def test_the_value_editor_wears_the_editors_theme(window, raw, monkeypatch):
    """It was built without style_dialog, so inside a light-themed editor it drew
    the app's dark input field — dark text on a dark box."""
    from PySide6.QtWidgets import QDialog

    import nwnsaveeditor.ui.dialogs.property_edit_dialog as ped

    window._edit_toggle.setChecked(True)
    seen = {}

    class _Spy(ped.PropertyEditDialog):
        def setStyleSheet(self, qss):  # noqa: N802 - Qt override
            seen["qss"] = qss
            super().setStyleSheet(qss)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ped, "PropertyEditDialog", _Spy)
    raw._tree.setCurrentItem(_find_scalar(raw, "Gold"))
    raw._edit_selected()

    assert "QSpinBox" in seen.get("qss", ""), "its inputs must be styled"


def test_the_value_editor_is_not_called_a_property(window, raw, monkeypatch):
    """A raw GFF field is not an item property; the shared dialog said it was."""
    from PySide6.QtWidgets import QDialog

    import nwnsaveeditor.ui.dialogs.property_edit_dialog as ped

    window._edit_toggle.setChecked(True)
    titles = []

    class _Spy(ped.PropertyEditDialog):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            titles.append(self.windowTitle())

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ped, "PropertyEditDialog", _Spy)
    raw._tree.setCurrentItem(_find_scalar(raw, "Gold"))
    raw._edit_selected()
    assert titles == ["Edit Value"]
