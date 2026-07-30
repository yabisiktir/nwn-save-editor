"""The Save Game Editor's Area Contents screen."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QPushButton

from vaultkeeper.ui.save_editor.screens.area import AreaScreen
from vaultkeeper.ui.save_editor.screens.item_panels import AreaItemPanel, PlayerItemPanel
from vaultkeeper.ui.save_editor.window import SaveEditorWindow


@pytest.fixture
def window(qtbot, tmp_path):
    from tests.test_save_editor import _make_char_save_with_git

    save = _make_char_save_with_git(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    editor = SaveEditorWindow([save], _Ctrl())
    qtbot.addWidget(editor)
    return editor


@pytest.fixture
def screen(window) -> AreaScreen:
    return window._screens["area"]


def _tree_labels(screen) -> list[str]:
    labels = []

    def walk(node):
        for i in range(node.childCount()):
            child = node.child(i)
            labels.append(child.text(0))
            walk(child)

    for i in range(screen._tree.topLevelItemCount()):
        top = screen._tree.topLevelItem(i)
        labels.append(top.text(0))
        walk(top)
    return labels


def test_an_area_is_chosen_and_decoded(window, screen):
    assert screen._area_resref is not None
    assert screen._area is not None, "the fixture area should decode"


def test_the_tree_groups_stores_creatures_and_containers(screen):
    labels = _tree_labels(screen)
    area = screen._area
    if area.stores:
        assert any(label.startswith(f"Stores ({len(area.stores)})") for label in labels)
    if area.creatures:
        assert any(label.startswith(f"Creatures ({len(area.creatures)})") for label in labels)
    if area.containers:
        assert any(label.startswith(f"Containers ({len(area.containers)})") for label in labels)


def test_selecting_an_area_item_shows_the_copy_only_panel(window, screen):
    """An item found in the world must never get the player item panel."""
    item_node = _first_item_node(screen)
    if item_node is None:
        pytest.skip("the fixture area holds no items")
    screen._tree.setCurrentItem(item_node)

    assert screen._detail_slot.findChild(AreaItemPanel) is not None
    assert screen._detail_slot.findChild(PlayerItemPanel) is None
    labels = [b.text() for b in screen._detail_slot.findChildren(QPushButton)]
    assert "Add a copy to my inventory" in labels
    assert "Edit…" not in labels and "Add a property…" not in labels


def test_edit_store_is_gated_on_edit_mode_and_on_selecting_a_store(window, screen):
    store_node = _first_store_node(screen)
    if store_node is None:
        pytest.skip("the fixture area holds no store")

    screen._tree.setCurrentItem(store_node)
    assert not screen._store_button.isEnabled(), "edit mode is off"

    # Toggling the gate rebuilds the tree, so the old node handle is stale; the
    # screen restores the selection itself.
    window._edit_toggle.setChecked(True)
    assert screen._store_button.isEnabled()

    item_node = _first_item_node(screen)
    if item_node is not None:
        screen._tree.setCurrentItem(item_node)
        assert not screen._store_button.isEnabled(), "an item is not a store"


def test_editing_a_store_stages_it_against_the_chosen_area(window, screen, monkeypatch):
    from PySide6.QtWidgets import QDialog

    if _first_store_node(screen) is None:
        pytest.skip("the fixture area holds no store")
    screen._tree.setCurrentItem(_first_store_node(screen))
    window._edit_toggle.setChecked(True)

    class _Dialog:
        def __init__(self, *a, **k):
            pass

        def setStyleSheet(self, _qss):  # noqa: N802 - the editor themes its dialogs
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def values(self):
            return {"markup": 133}

    monkeypatch.setattr(
        "vaultkeeper.ui.dialogs.store_edit_dialog.StoreEditDialog", _Dialog
    )
    screen._edit_store()
    changes = window.session().pending_changes()
    assert [c.kind for c in changes] == ["store"]
    assert changes[0].key[0] == screen._area_resref


def test_a_store_that_cannot_be_edited_reports_instead_of_staging(
    window, screen, monkeypatch
):
    """SaveEditor refuses to invent a field a store does not carry; the screen must
    surface that rather than silently claiming the edit was staged."""
    from PySide6.QtWidgets import QDialog, QMessageBox

    from vaultkeeper.game.save_editor import SaveEditError

    if _first_store_node(screen) is None:
        pytest.skip("the fixture area holds no store")
    screen._tree.setCurrentItem(_first_store_node(screen))
    window._edit_toggle.setChecked(True)

    class _Dialog:
        def __init__(self, *a, **k):
            pass

        def setStyleSheet(self, _qss):  # noqa: N802 - the editor themes its dialogs
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def values(self):
            return {"markup": 133}

    monkeypatch.setattr(
        "vaultkeeper.ui.dialogs.store_edit_dialog.StoreEditDialog", _Dialog
    )

    def _refuse(*_a, **_k):
        raise SaveEditError("store has no 'MarkUp' field to edit")

    monkeypatch.setattr(window.session(), "set_store_fields", _refuse)
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a))

    screen._edit_store()
    assert shown, "the failure must be reported"
    assert not window.session().has_edits


def test_switching_area_reloads_the_tree(window, screen):
    areas = screen._areas()
    if len(areas) < 2:
        pytest.skip("the fixture save has a single area")
    screen._choose_area(areas[1][0])
    assert screen._area_resref == areas[1][0]


def _first_store_node(screen):
    for i in range(screen._tree.topLevelItemCount()):
        top = screen._tree.topLevelItem(i)
        if top.text(0).startswith("Stores") and top.childCount():
            return top.child(0)
    return None


def _first_item_node(screen):
    from PySide6.QtCore import Qt

    def walk(node):
        for i in range(node.childCount()):
            child = node.child(i)
            role = child.data(0, Qt.ItemDataRole.UserRole)
            if role and role[0] == "item":
                return child
            found = walk(child)
            if found is not None:
                return found
        return None

    for i in range(screen._tree.topLevelItemCount()):
        found = walk(screen._tree.topLevelItem(i))
        if found is not None:
            return found
    return None
