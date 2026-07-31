"""The Save Game Editor's Inventory screen and its per-context item panels."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QPushButton

from vaultkeeper.core.formats.bic_reader import EQUIP_SLOT_NAMES
from vaultkeeper.ui.save_editor.screens.inventory import (
    CREATURE_SLOTS,
    PAPERDOLL,
    InventoryScreen,
)
from vaultkeeper.ui.save_editor.screens.item_panels import AreaItemPanel, PlayerItemPanel
from vaultkeeper.ui.save_editor.window import SaveEditorWindow


@pytest.fixture
def window(qtbot, tmp_path):
    from tests.test_save_editor import _make_char_save

    save = _make_char_save(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    editor = SaveEditorWindow([save], _Ctrl())
    qtbot.addWidget(editor)
    return editor


@pytest.fixture
def screen(window) -> InventoryScreen:
    return window._screens["inventory"]


def _buttons(widget) -> list[str]:
    return [b.text() for b in widget.findChildren(QPushButton)]


# -- the paperdoll --------------------------------------------------------- #
def test_paperdoll_covers_the_wearable_slots():
    """Every wearable slot needs a cell, or an item there would be invisible."""
    wearable = set(EQUIP_SLOT_NAMES) - set(CREATURE_SLOTS)
    assert set(PAPERDOLL) == wearable


def test_paired_slots_are_mirrored_across_the_body_axis():
    """The handoff asks for a humanoid, not a flat grid: pairs sit left and right."""
    for left_bit, right_bit in ((16, 32), (256, 128)):  # hands, rings
        left_row, left_col = PAPERDOLL[left_bit]
        right_row, right_col = PAPERDOLL[right_bit]
        assert left_row == right_row, "a pair must share a row"
        assert {left_col, right_col} == {0, 2}, "a pair must straddle the centre column"


def test_body_axis_slots_sit_in_the_centre_column():
    for bit in (1, 2, 1024, 4):  # head, chest, belt, boots
        assert PAPERDOLL[bit][1] == 1


# -- selection ------------------------------------------------------------- #
def test_selecting_an_item_shows_it_in_the_detail_panel(window, screen):
    item = window.session().player_items()[0]
    screen._select(tuple(item.path))
    panel = screen._detail_slot.findChild(PlayerItemPanel)
    assert panel is not None
    assert panel._item is item or panel._item.path == item.path


def test_the_detail_panel_starts_empty(screen):
    panel = screen._detail_slot.findChild(PlayerItemPanel)
    assert panel is not None and panel._item is None


# -- the edit gate --------------------------------------------------------- #
def test_property_actions_are_absent_until_edit_mode_is_on(window, screen):
    item = window.session().player_items()[0]
    screen._select(tuple(item.path))
    panel = screen._detail_slot.findChild(PlayerItemPanel)
    assert "Edit…" not in _buttons(panel)
    assert "Add a property…" not in _buttons(panel)

    window._edit_toggle.setChecked(True)
    screen._select(tuple(item.path))
    panel = screen._detail_slot.findChild(PlayerItemPanel)
    assert "Add a property…" in _buttons(panel)
    if item.properties:
        assert "Edit…" in _buttons(panel)


# -- the two panels are deliberately different ----------------------------- #
def test_an_area_item_panel_offers_no_property_editing(window, qtbot):
    """The handoff forbids sharing one panel across contexts."""
    item = window.session().player_items()[0]
    window._edit_toggle.setChecked(True)
    screen = window._screens["inventory"]

    panel = AreaItemPanel(screen, item, "area1")
    qtbot.addWidget(panel)
    labels = _buttons(panel)
    assert "Add a copy to my inventory" in labels
    assert "Edit…" not in labels
    assert "Add a property…" not in labels
    assert "×" not in labels


def test_the_area_panel_cannot_copy_while_edit_mode_is_off(window, qtbot):
    item = window.session().player_items()[0]
    screen = window._screens["inventory"]
    panel = AreaItemPanel(screen, item, "area1")
    qtbot.addWidget(panel)
    copy = next(b for b in panel.findChildren(QPushButton))
    assert not copy.isEnabled()


def test_copying_an_area_item_confirms_in_place(window, qtbot, monkeypatch):
    """After a copy the button is replaced by the design's gold confirmation."""
    from PySide6.QtWidgets import QLabel

    window._edit_toggle.setChecked(True)
    screen = window._screens["inventory"]
    item = window.session().player_items()[0]
    panel = AreaItemPanel(screen, item, "area1")
    qtbot.addWidget(panel)

    copied = []
    monkeypatch.setattr(
        window.session(), "add_item_from_area",
        lambda *a, **k: copied.append((a, k)),
    )
    panel._copy_to_inventory()
    assert copied, "the copy must go through the session, not touch the area"
    assert not panel._action_slot.findChildren(QPushButton)
    text = " ".join(label.text() for label in panel._action_slot.findChildren(QLabel))
    assert "Copy added to inventory" in text


def test_a_failed_copy_reports_instead_of_claiming_success(window, qtbot, monkeypatch):
    from PySide6.QtWidgets import QLabel, QMessageBox

    window._edit_toggle.setChecked(True)
    screen = window._screens["inventory"]
    item = window.session().player_items()[0]
    panel = AreaItemPanel(screen, item, "area1")
    qtbot.addWidget(panel)

    def _boom(*_a, **_k):
        raise RuntimeError("no such item in that area")

    monkeypatch.setattr(window.session(), "add_item_from_area", _boom)
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a))
    panel._copy_to_inventory()
    assert shown, "a failed copy must be reported"
    text = " ".join(label.text() for label in panel._action_slot.findChildren(QLabel))
    assert "Copy added to inventory" not in text


# -- the shell keeps screens in step --------------------------------------- #
def test_screens_populate_after_a_save_is_selected(window, screen):
    """Screens are built before any save is selected, so the shell must re-render
    them on selection — otherwise the inventory stays permanently empty."""
    from PySide6.QtWidgets import QLabel

    items = window.session().player_items()
    assert items, "the fixture character should carry items"

    cells = [
        label for label in screen._scroll.widget().findChildren(QLabel)
        if label.width() or label.toolTip()
    ]
    named = {label.toolTip().splitlines()[0] for label in cells if label.toolTip()}
    for item in items:
        assert item.name in named, f"{item.name} has no cell on the screen"


def test_toggling_edit_mode_re_renders_the_screens(window, screen):
    item = window.session().player_items()[0]
    screen._select(tuple(item.path))
    assert "Add a property…" not in _buttons(screen._detail_slot)
    window._edit_toggle.setChecked(True)
    assert "Add a property…" in _buttons(screen._detail_slot)


# -- sorting ---------------------------------------------------------------- #
def test_carried_items_group_by_type_by_default(window, screen):
    """The game's own inventory groups by item type, so that is the default."""
    from vaultkeeper.game.item_names import base_item_type

    assert screen._sort == "type"
    carried = [i for i in window.session().player_items() if i.slot is None]
    if len(carried) < 2:
        pytest.skip("the fixture character carries too little to order")
    ordered = screen._sorted(carried)
    types = [(base_item_type(i.base_item) or "").lower() for i in ordered]
    assert types == sorted(types), "items are not grouped by type"


def test_sorting_by_name_is_a_flat_alphabetical_list(window, screen):
    carried = [i for i in window.session().player_items() if i.slot is None]
    if len(carried) < 2:
        pytest.skip("the fixture character carries too little to order")
    screen._sort = "name"
    names = [screen._name(i).lower() for i in screen._sorted(carried)]
    assert names == sorted(names)


def test_switching_the_sort_re_renders(window, screen):
    screen._set_sort("name")
    assert screen._sort == "name"
    screen._set_sort("type")
    assert screen._sort == "type"


# -- adding a property from the item panel ---------------------------------- #
def test_adding_a_property_stages_what_the_dialog_built(window, screen, monkeypatch):
    """The panel called dialog.values(), which the dialog has never had — so
    pressing OK raised AttributeError instead of adding anything."""
    from PySide6.QtWidgets import QDialog

    window._edit_toggle.setChecked(True)
    item = window.session().player_items()[0]
    screen._select(tuple(item.path))
    panel = screen._detail_slot.findChild(PlayerItemPanel)

    class _Dialog:
        def __init__(self, *a, **k):
            self.tables = k.get("tables")

        def setStyleSheet(self, _qss):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def result_property(self):
            return {
                "property_name": 1, "subtype": 0, "cost_value": 6,
                "cost_table": 2, "param1": None, "label": "AC Bonus +6",
            }

    monkeypatch.setattr(
        "vaultkeeper.ui.dialogs.add_property_dialog.AddPropertyDialog", _Dialog
    )
    before = len(window.session().player_items()[0].properties)
    panel._add_property()

    staged = [c for c in window.session().pending_changes() if c.kind == "prop-add"]
    assert [c.summary for c in staged] == ["add AC Bonus +6"]
    assert len(window.session().player_items()[0].properties) == before + 1


def test_the_add_dialog_is_given_the_games_property_tables(window, screen, monkeypatch):
    """Without them it falls back to 14 curated types and cannot add a bonus feat."""
    from PySide6.QtWidgets import QDialog

    window._edit_toggle.setChecked(True)
    item = window.session().player_items()[0]
    screen._select(tuple(item.path))
    panel = screen._detail_slot.findChild(PlayerItemPanel)
    seen = {}

    class _Dialog:
        def __init__(self, *a, **k):
            seen["tables"] = k.get("tables", "missing")

        def setStyleSheet(self, _qss):
            pass

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        "vaultkeeper.ui.dialogs.add_property_dialog.AddPropertyDialog", _Dialog
    )
    monkeypatch.setattr(screen, "property_tables", lambda: "the tables")
    panel._add_property()
    assert seen["tables"] == "the tables"
