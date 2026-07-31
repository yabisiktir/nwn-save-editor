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


# -- editing an item that lives in the area --------------------------------- #
def _shop_item(window):
    from vaultkeeper.game.save_area import read_area_contents

    area = read_area_contents(window.save.sav_path, "area1")
    return area.stores[0].items[0]


def _panel(window, screen, qtbot):
    from PySide6.QtWidgets import QApplication

    # widgets.retire() holds a Python wrapper until the next event-loop turn; in
    # a test the loop may not spin between widgets, so drain it before building
    # a new panel or PySide can hand back a stale wrapper for a reused address.
    QApplication.processEvents()
    panel = AreaItemPanel(screen, _shop_item(window), "area1")
    qtbot.addWidget(panel)
    return panel


def test_an_area_item_knows_where_it_lives_in_the_git(window):
    """Without this path there is nothing to write to, so it stays read-only."""
    assert _shop_item(window).git_path == (
        ("StoreList", 0), ("StoreList", 0), ("ItemList", 0)
    )


def test_the_panel_offers_property_editing_in_edit_mode(window, screen, qtbot):
    window._edit_toggle.setChecked(True)
    labels = [b.text() for b in _panel(window, screen, qtbot).findChildren(QPushButton)]
    assert "Add a property…" in labels
    assert "Edit…" in labels
    assert "×" in labels
    assert "Add a copy to my inventory" in labels, "copying is still offered"


def test_the_panel_stays_read_only_with_edit_mode_off(window, screen, qtbot):
    panel = _panel(window, screen, qtbot)
    assert not panel._editable(), "the edit gate governs area items too"


def test_removing_a_property_stages_an_area_change(window, screen, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window._edit_toggle.setChecked(True)
    panel = _panel(window, screen, qtbot)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    panel._remove_property(0, _shop_item(window).properties[0])

    staged = window.session().pending_changes()
    assert [c.kind for c in staged] == ["area-item"]
    assert staged[0].where == _shop_item(window).name


def test_declining_the_confirmation_stages_nothing(window, screen, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window._edit_toggle.setChecked(True)
    panel = _panel(window, screen, qtbot)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
    )
    panel._remove_property(0, _shop_item(window).properties[0])
    assert not window.session().has_edits


def test_a_failed_area_edit_reports_instead_of_passing_silently(
    window, screen, qtbot, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    window._edit_toggle.setChecked(True)
    panel = _panel(window, screen, qtbot)
    panel._item.git_path = (("StoreList", 99),)  # no longer resolves
    told = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: told.append(a))
    panel._area_edit("remove_area_property", 0, label="x")
    assert told, "a silent no-op would look like a successful edit"


def test_an_area_edit_lights_the_area_sections_dot(window, screen, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window._edit_toggle.setChecked(True)
    panel = _panel(window, screen, qtbot)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    panel._remove_property(0, _shop_item(window).properties[0])
    assert not window._nav_rows["area"]._dot.isHidden()


# -- adding and removing whole items in the world --------------------------- #
def _yes(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )


def test_the_world_actions_appear_only_in_edit_mode(window, screen, qtbot):
    panel = _panel(window, screen, qtbot)
    assert not panel._editable()

    window._edit_toggle.setChecked(True)
    labels = [b.text() for b in _panel(window, screen, qtbot).findChildren(QPushButton)]
    assert "Duplicate here" in labels
    assert "Remove from the world…" in labels


def test_removing_an_item_from_the_world_stages_it(window, screen, qtbot, monkeypatch):
    window._edit_toggle.setChecked(True)
    panel = _panel(window, screen, qtbot)
    _yes(monkeypatch)
    panel._remove_from_world()

    staged = window.session().pending_changes()
    assert [c.kind for c in staged] == ["area-item"]
    assert "remove item" in staged[0].summary


def test_declining_the_removal_stages_nothing(window, screen, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window._edit_toggle.setChecked(True)
    panel = _panel(window, screen, qtbot)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
    )
    panel._remove_from_world()
    assert not window.session().has_edits


def test_duplicating_an_item_needs_no_confirmation(window, screen, qtbot):
    """It adds; it destroys nothing, so a modal would only be in the way."""
    window._edit_toggle.setChecked(True)
    _panel(window, screen, qtbot)._duplicate_in_world()
    assert [c.summary for c in window.session().pending_changes()] == ["duplicate item"]


def test_a_holder_node_can_take_one_of_your_items(window, screen, monkeypatch):
    from PySide6.QtWidgets import QDialog

    import vaultkeeper.ui.dialogs.id_picker_dialog as idp

    window._edit_toggle.setChecked(True)
    node = _find_node(screen, lambda n: n.data(0, _holder_role()) is not None)
    assert node is not None, "a store, creature or container must be placeable-into"
    screen._tree.setCurrentItem(node)
    assert screen._place_button.isEnabled()

    offered = {}

    class _Chose(idp.IdPickerDialog):
        def __init__(self, title, items, **kw):
            offered["items"] = list(items)
            super().__init__(title, items, **kw)

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_id(self):
            return 0

    monkeypatch.setattr(idp, "IdPickerDialog", _Chose)
    screen._place_item()

    assert offered["items"], "your own items are what it offers"
    staged = window.session().pending_changes()
    assert [c.kind for c in staged] == ["area-item"]
    assert "place a copy" in staged[0].summary


def test_the_place_button_is_dead_without_a_holder_selected(window, screen):
    window._edit_toggle.setChecked(True)
    screen._tree.setCurrentItem(None)
    screen._sync_gate()
    assert not screen._place_button.isEnabled()


def _holder_role():
    from vaultkeeper.ui.save_editor.screens.area import _HOLDER

    return _HOLDER


def _find_node(screen, predicate):
    def walk(node):
        if predicate(node):
            return node
        for i in range(node.childCount()):
            hit = walk(node.child(i))
            if hit is not None:
                return hit
        return None

    for i in range(screen._tree.topLevelItemCount()):
        hit = walk(screen._tree.topLevelItem(i))
        if hit is not None:
            return hit
    return None
