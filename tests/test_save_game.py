"""Tests for the save-game reader + Save Game Viewer."""

from __future__ import annotations

from pathlib import Path

import pytest

from vaultkeeper.game.save_game import ModuleSaveInfo, SaveGame, scan_save_games


def test_save_game_paths(tmp_path):
    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    (folder / "Chapter Three.sav").write_bytes(b"sav")
    (folder / "player.bic").write_bytes(b"bic")
    (folder / "screen.tga").write_bytes(b"tga")
    save = SaveGame(folder=folder)
    assert save.name == "000000 - quicksave"
    assert save.sav_path is not None and save.sav_path.name == "Chapter Three.sav"
    assert save.player_bic is not None
    assert save.screenshot is not None and save.screenshot.name == "screen.tga"


def test_scan_save_games_skips_folders_without_a_sav(tmp_path):
    (tmp_path / "not-a-save").mkdir()  # no .sav inside
    real = tmp_path / "000000 - quicksave"
    real.mkdir()
    (real / "x.sav").write_bytes(b"sav")
    saves = scan_save_games(tmp_path)
    assert [s.name for s in saves] == ["000000 - quicksave"]
    assert scan_save_games(None) == []
    assert scan_save_games(tmp_path / "missing") == []


def test_module_save_info_game_time():
    info = ModuleSaveInfo(year=1372, month=10, day=1, hour=13, minute=5)
    assert info.game_time == "1372/10/01 13:05"
    assert ModuleSaveInfo().game_time == ""  # no year -> unknown


def test_save_game_viewer_lists_and_shows_detail(qtbot, tmp_path):
    from vaultkeeper.ui.dialogs.save_game_viewer import SaveGameViewer

    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    save = SaveGame(folder=folder, location="Aarin's Lodge")
    save.module_info = lambda: ModuleSaveInfo(  # type: ignore[method-assign]
        name="Chapter Three", tag="Chapter3", xp_scale=10,
        year=1372, month=10, day=1, hour=13, minute=0,
        areas=[("a1", "The Maze"), ("a2", "a2")], player_count=1,
    )
    view = SaveGameViewer([save])
    qtbot.addWidget(view)
    assert view._list.count() == 1
    view._list.setCurrentRow(0)

    text = view._detail.toPlainText()
    assert "Chapter Three" in text and "Aarin's Lodge" in text
    assert "1372/10/01 13:00" in text
    # The area contents tree lists each area as a top-level (lazy) node.
    assert view._areas.topLevelItemCount() == 2
    assert view._areas.topLevelItem(0).text(0) == "The Maze  (a1)"
    assert view._areas.topLevelItem(1).text(0) == "a2"  # name == resref -> resref only


def _mk_item(name, base=0):
    from vaultkeeper.core.formats.bic_reader import InventoryItem

    return InventoryItem(
        name=name, base_item=base, tag="", resref="rr", stack_size=1,
        identified=True, stolen=False, description="",
    )


def test_save_viewer_area_contents_tree(qtbot, tmp_path, monkeypatch):
    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from vaultkeeper.core.formats.bic_reader import EquippedItem
    from vaultkeeper.game.save_area import (
        AreaContents,
        Container,
        CreatureRef,
        Faction,
        Store,
    )

    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    (folder / "x.sav").write_bytes(b"sav")
    save = SaveGame(folder=folder)
    save.module_info = lambda: ModuleSaveInfo(  # type: ignore[method-assign]
        name="M", areas=[("a1", "Town")]
    )

    area = AreaContents(
        resref="a1", name="Town", tileset="ttu01", width=8, height=8,
        stores=[Store(
            name="Nature Store", tag="NW_S", markup=200, markdown=35,
            items=[_mk_item("Hide Armor +2")],
        )],
        creatures=[CreatureRef(
            name="Guard", tag="g", gold=12,
            equipped=[EquippedItem(16, "Right Hand", _mk_item("Longsword"))],
            carried=[_mk_item("Torch")],
        )],
        containers=[Container(name="Chest", tag="c", items=[_mk_item("Gold Ring")])],
        counts={"placeables": 5},
    )
    monkeypatch.setattr(sgv, "read_area_contents", lambda *a, **k: area)
    monkeypatch.setattr(
        sgv, "read_factions", lambda *a, **k: [Faction(name="Commoner", reputation_to_pc=50)]
    )

    view = sgv.SaveGameViewer([save])
    qtbot.addWidget(view)
    tree = view._areas
    labels = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert labels == ["Town  (a1)", "Factions (1)"]

    area_node = tree.topLevelItem(0)
    area_node.setExpanded(True)  # triggers the lazy .git parse
    groups = [area_node.child(i).text(0) for i in range(area_node.childCount())]
    assert groups == ["Stores (1)", "Creatures (1)", "Containers (1)"]

    # Store -> its stock; selecting it shows the pricing detail.
    store_node = area_node.child(0).child(0)
    assert store_node.text(0) == "Nature Store  (1 items)"
    assert store_node.child(0).text(0) == "Hide Armor +2"
    tree.setCurrentItem(store_node)
    assert "markup: 200%" in view._content_detail.toPlainText()

    # Creature equipment carries a slot prefix.
    creature_node = area_node.child(1).child(0)
    assert creature_node.text(0) == "Guard  (2 items)"
    assert creature_node.child(0).text(0) == "[Right Hand] Longsword"

    # Area node (now loaded) shows its metadata.
    tree.setCurrentItem(area_node)
    assert "Tileset: ttu01" in view._content_detail.toPlainText()

    # Factions node shows the reputation band.
    tree.setCurrentItem(tree.topLevelItem(1))
    faction_text = view._content_detail.toPlainText()
    assert "Commoner" in faction_text and "neutral (50)" in faction_text


def test_save_viewer_edit_store_writes_new_save(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _git_with_store, _make_save, _store_struct
    from vaultkeeper.config.settings import Settings
    from vaultkeeper.game.save_area import read_area_contents

    save = _make_save(tmp_path, _git_with_store(_store_struct(markup=200)))
    store = read_area_contents(save.sav_path, "area1").stores[0]

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._edit_toggle.setChecked(True)  # enter edit mode
    view._edit_target = ("store", "area1", 0, store)

    class _FakeDialog:
        def __init__(self, _store, _parent=None):
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def values(self):
            return {"markup": 111, "black_market": True}

    monkeypatch.setattr(
        "vaultkeeper.ui.dialogs.store_edit_dialog.StoreEditDialog", _FakeDialog
    )
    monkeypatch.setattr(sgv.QInputDialog, "getText", lambda *a, **k: ("My Edit", True))
    monkeypatch.setattr(sgv.QMessageBox, "information", lambda *a, **k: None)

    # 1) staging the edit does NOT write anything yet — it's pending
    before = view._list.count()
    view._edit_selected()
    assert view._session is not None and view._session.has_edits
    assert view._pending_list.count() == 1
    assert not (tmp_path / "000001 - My Edit").exists()

    # 2) committing writes a new save carrying the edit; original untouched
    view._save_as_new()
    new_folder = tmp_path / "000001 - My Edit"
    assert new_folder.is_dir()
    assert view._list.count() == before + 1
    assert view._session is None  # session cleared after save
    edited = read_area_contents(next(new_folder.glob("*.sav")), "area1").stores[0]
    assert edited.markup == 111
    assert edited.black_market is True
    assert read_area_contents(save.sav_path, "area1").stores[0].markup == 200


def test_save_viewer_overwrite_current(qtbot, tmp_path, monkeypatch):
    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _git_with_store, _make_save, _store_struct
    from vaultkeeper.game.save_area import read_area_contents

    # a save inside a saves/ dir so the backup dir lands beside it (saves/../backups)
    saves = tmp_path / "saves"
    saves.mkdir()
    save = _make_save(saves, _git_with_store(_store_struct(markup=200)), name="000000 - s")

    view = sgv.SaveGameViewer([save])
    qtbot.addWidget(view)
    view._current = save
    view._editing = True
    view._ensure_session().set_store_fields("area1", 0, markup=150)
    view._refresh_pending()

    monkeypatch.setattr(
        sgv.QMessageBox, "warning",
        lambda *a, **k: sgv.QMessageBox.StandardButton.Yes,  # confirm overwrite
    )
    monkeypatch.setattr(sgv.QMessageBox, "information", lambda *a, **k: None)

    view._overwrite_current()
    # the SAME save folder now carries the edit; session cleared; a backup exists
    assert read_area_contents(save.sav_path, "area1").stores[0].markup == 150
    assert view._session is None
    backup_dir = tmp_path / "vaultkeeper_backups"
    assert backup_dir.is_dir() and len(list(backup_dir.iterdir())) == 1


def test_save_viewer_discard_clears_pending(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _git_with_store, _make_save, _store_struct
    from vaultkeeper.config.settings import Settings
    from vaultkeeper.game.save_area import read_area_contents

    save = _make_save(tmp_path, _git_with_store(_store_struct(markup=200)))
    store = read_area_contents(save.sav_path, "area1").stores[0]

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._editing = True
    view._edit_target = ("area1", 0, store)
    view._ensure_session().set_store_fields("area1", 0, markup=1)
    view._refresh_pending()
    assert view._pending_list.count() == 1

    monkeypatch.setattr(
        sgv.QMessageBox, "question", lambda *a, **k: sgv.QMessageBox.StandardButton.Yes
    )
    view._discard_all()
    assert view._session is None
    assert view._pending_list.count() == 0
    # nothing was written
    assert not any(p.name.startswith("000001") for p in tmp_path.iterdir())


def test_save_viewer_character_node_edits_item_property(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _ifo_char, _make_char_save
    from vaultkeeper.config.settings import Settings

    save = _make_char_save(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._edit_toggle.setChecked(True)

    # find + expand the Player character node
    tree = view._areas
    char = next(
        tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
        if tree.topLevelItem(i).data(0, sgv._NODE_ROLE)[0] == "character"
    )
    char.setExpanded(True)  # lazily populates details/equipped/carried + properties
    equipped = next(
        char.child(i) for i in range(char.childCount())
        if char.child(i).text(0) == "Equipped (1)"
    )
    helm = equipped.child(0)
    ability = helm.child(0)  # the Ability Bonus property node
    assert ability.data(0, sgv._NODE_ROLE)[0] == "property"

    tree.setCurrentItem(ability)  # sets the edit target
    assert view._edit_target is not None and view._edit_target[0] == "property"

    # edit its magnitude via the (monkeypatched) property dialog
    class _FakeDialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def value(self):
            return 8

    monkeypatch.setattr(
        "vaultkeeper.ui.dialogs.property_edit_dialog.PropertyEditDialog", _FakeDialog
    )
    monkeypatch.setattr(sgv.QInputDialog, "getText", lambda *a, **k: ("My Char Edit", True))
    monkeypatch.setattr(sgv.QMessageBox, "information", lambda *a, **k: None)

    view._edit_selected()
    assert view._pending_list.count() == 1
    view._save_as_new()
    new = tmp_path / "000001 - My Char Edit"
    assert new.is_dir()
    # the ability bonus magnitude landed in module.ifo of the new save
    char_struct = _ifo_char(next(new.glob("*.sav")))
    helm_struct = char_struct.fields["Equip_ItemList"].value.structs[0]
    assert helm_struct.fields["PropertiesList"].value.structs[0].fields["CostValue"].value == 8


def test_save_viewer_add_item_copy(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _ifo_char, _make_char_save
    from vaultkeeper.config.settings import Settings

    save = _make_char_save(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._editing = True

    bag = next(it for it in view._ensure_session().player_items() if it.name == "Bag")

    class _Item:  # minimal stand-in with the attrs _add_item_copy needs
        path = bag.path
        name = "Bag"

    monkeypatch.setattr(sgv.QInputDialog, "getText", lambda *a, **k: ("Added Item", True))
    monkeypatch.setattr(sgv.QMessageBox, "information", lambda *a, **k: None)

    view._add_item_copy(_Item())
    assert view._pending_list.count() == 1
    view._save_as_new()
    carried = _ifo_char(next((tmp_path / "000001 - Added Item").glob("*.sav"))).fields["ItemList"]
    assert len(carried.value.structs) == 2  # bag + its clone


def test_save_viewer_edit_skill_rank(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _ifo_char, _make_char_save
    from vaultkeeper.config.settings import Settings

    save = _make_char_save(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._editing = True
    view._edit_target = ("skill", 3, "Discipline", 43)  # skill id 3

    class _FakeDialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def value(self):
            return 50

    monkeypatch.setattr(
        "vaultkeeper.ui.dialogs.property_edit_dialog.PropertyEditDialog", _FakeDialog
    )
    monkeypatch.setattr(sgv.QInputDialog, "getText", lambda *a, **k: ("Skilled", True))
    monkeypatch.setattr(sgv.QMessageBox, "information", lambda *a, **k: None)

    view._edit_selected()
    assert view._pending_list.count() == 1
    view._save_as_new()
    char = _ifo_char(next((tmp_path / "000001 - Skilled").glob("*.sav")))
    assert char.fields["SkillList"].value.structs[3].fields["Rank"].value == 50


def test_editing_guide_dialog_opens(qtbot):
    from PySide6.QtWidgets import QTextBrowser

    from vaultkeeper.ui.dialogs.save_editor_help import SaveEditorHelpDialog

    dialog = SaveEditorHelpDialog()
    qtbot.addWidget(dialog)
    body = dialog.findChildren(QTextBrowser)[0].toPlainText()
    assert "Save as New Save" in body and "PRC" in body and "never touched" in body


class _FakeTables:
    available = True

    def subtype_options(self, pn):
        return {0: "Str", 1: "Dex", 2: "Con"} if pn == 0 else None

    def cost_options(self, ct):
        return {1: "+1", 2: "+2", 5: "+5", 7: "+7"}

    def param1_options(self, pn):
        return None

    def property_name_label(self, pn):
        return "Ability Bonus"


def test_save_viewer_edit_character_field(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _ifo_char, _make_char_save_with_details
    from vaultkeeper.config.settings import Settings

    save = _make_char_save_with_details(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._editing = True
    gold = next(f for f in view._ensure_session().player_fields() if f.field == "Gold")
    view._edit_target = ("char-field", gold)

    class _Dialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def value(self):
            return 9999

    monkeypatch.setattr(
        "vaultkeeper.ui.dialogs.property_edit_dialog.PropertyEditDialog", _Dialog
    )
    monkeypatch.setattr(sgv.QInputDialog, "getText", lambda *a, **k: ("Gold Edit", True))
    monkeypatch.setattr(sgv.QMessageBox, "information", lambda *a, **k: None)

    view._edit_selected()
    assert view._pending_list.count() == 1
    view._save_as_new()
    char = _ifo_char(next((tmp_path / "000001 - Gold Edit").glob("*.sav")))
    assert char.fields["Gold"].value == 9999


class _FakeLook:
    def appearance_options(self):
        return {6: "Human", 1: "Elf", 2: "Gnome"}

    def appearance_name(self, i):
        return self.appearance_options().get(i, f"#{i}")

    def portrait_resrefs(self):
        return ["po_hu_m_11_", "po_el_f_02_", "po_dw_m_03_"]


def test_save_viewer_edit_portrait(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _ifo_char, _make_char_save_with_details
    from vaultkeeper.config.settings import Settings

    save = _make_char_save_with_details(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._editing = True
    monkeypatch.setattr(view, "_look_tables", lambda: _FakeLook())
    portrait = next(f for f in view._ensure_session().player_fields() if f.field == "Portrait")
    view._edit_target = ("char-field", portrait)

    class _Picker:  # picks index 1 -> "po_el_f_02_"
        def __init__(self, *a, **k):
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def selected_id(self):
            return 1

    monkeypatch.setattr("vaultkeeper.ui.dialogs.id_picker_dialog.IdPickerDialog", _Picker)
    monkeypatch.setattr(sgv.QInputDialog, "getText", lambda *a, **k: ("Look Edit", True))
    monkeypatch.setattr(sgv.QMessageBox, "information", lambda *a, **k: None)

    view._edit_selected()
    assert view._pending_list.count() == 1
    view._save_as_new()
    char = _ifo_char(next((tmp_path / "000001 - Look Edit").glob("*.sav")))
    assert char.fields["Portrait"].value == "po_el_f_02_"


def test_property_editor_dialog_builds_edits(qtbot):
    from vaultkeeper.core.formats.bic_reader import ItemProperty
    from vaultkeeper.ui.dialogs.property_editor_dialog import PropertyEditorDialog

    prop = ItemProperty(
        property_name=0, subtype=0, cost_table=1, cost_value=2, param1=255, param1_value=0
    )
    dialog = PropertyEditorDialog(prop, _FakeTables(), 255)
    qtbot.addWidget(dialog)
    dialog._subtype_combo.setCurrentIndex(dialog._subtype_combo.findData(2))  # Con
    dialog._cost_combo.setCurrentIndex(dialog._cost_combo.findData(5))  # +5
    result = dialog.edits()
    assert result == {"subtype": 2, "cost_value": 5}


def test_save_viewer_edit_property_full(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _ifo_char, _make_char_save
    from vaultkeeper.config.settings import Settings

    save = _make_char_save(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._editing = True
    helm = next(it for it in view._ensure_session().player_items() if it.slot == 1)
    prop = helm.properties[0]  # Ability Bonus, subtype 0, cost 2

    monkeypatch.setattr(view, "_property_tables", lambda: _FakeTables())

    class _Dialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def edits(self):
            return {"subtype": 2, "cost_value": 7}

    monkeypatch.setattr(
        "vaultkeeper.ui.dialogs.property_editor_dialog.PropertyEditorDialog", _Dialog
    )
    monkeypatch.setattr(sgv.QInputDialog, "getText", lambda *a, **k: ("PropFull", True))
    monkeypatch.setattr(sgv.QMessageBox, "information", lambda *a, **k: None)

    view._edit_property(helm.path, prop.index, prop, "Helm")
    assert view._pending_list.count() == 1
    view._save_as_new()
    p = _ifo_char(next((tmp_path / "000001 - PropFull").glob("*.sav"))).fields[
        "Equip_ItemList"].value.structs[0].fields["PropertiesList"].value.structs[0]
    assert p.fields["Subtype"].value == 2 and p.fields["CostValue"].value == 7


def test_add_property_dialog_builds_property(qtbot):
    from vaultkeeper.ui.dialogs.add_property_dialog import AddPropertyDialog

    dialog = AddPropertyDialog()
    qtbot.addWidget(dialog)
    # select "AC Bonus" (a magnitude, no subtype) and set +7
    index = next(
        i for i in range(dialog._type.count()) if dialog._type.itemText(i) == "AC Bonus"
    )
    dialog._type.setCurrentIndex(index)
    dialog._magnitude.setValue(7)
    result = dialog.result_property()
    assert result["property_name"] == 1 and result["cost_value"] == 7
    assert result["label"] == "AC Bonus +7"
    assert not dialog._subtype.isVisible()  # no subtype for AC Bonus


def test_save_viewer_add_property(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _ifo_char, _make_char_save
    from vaultkeeper.config.settings import Settings

    save = _make_char_save(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._editing = True
    helm = next(it for it in view._ensure_session().player_items() if it.slot == 1)
    before = len(helm.properties)

    class _Dialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def result_property(self):
            return {
                "property_name": 1, "subtype": 0, "cost_value": 6, "cost_table": 2,
                "label": "AC Bonus +6",
            }

    monkeypatch.setattr("vaultkeeper.ui.dialogs.add_property_dialog.AddPropertyDialog", _Dialog)
    monkeypatch.setattr(sgv.QInputDialog, "getText", lambda *a, **k: ("Prop Edit", True))
    monkeypatch.setattr(sgv.QMessageBox, "information", lambda *a, **k: None)

    view._add_property(helm)
    assert view._pending_list.count() == 1
    view._save_as_new()
    char = _ifo_char(next((tmp_path / "000001 - Prop Edit").glob("*.sav")))
    props = char.fields["Equip_ItemList"].value.structs[0].fields["PropertiesList"].value.structs
    assert len(props) == before + 1 and props[-1].fields["CostValue"].value == 6


def test_save_viewer_clone_store_item(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _ifo_char, _make_char_save_with_git
    from vaultkeeper.config.settings import Settings
    from vaultkeeper.core.formats.bic_reader import InventoryItem

    save = _make_char_save_with_git(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._editing = True

    monkeypatch.setattr(sgv.QInputDialog, "getText", lambda *a, **k: ("Cloned", True))
    monkeypatch.setattr(sgv.QMessageBox, "information", lambda *a, **k: None)

    shop_item = InventoryItem(
        name="Shop Sword", base_item=3, tag="", resref="shopsword", stack_size=1,
        identified=True, stolen=False, description="",
    )
    view._clone_from_area("area1", shop_item)  # as the context menu would
    assert view._pending_list.count() == 1
    view._save_as_new()
    carried = _ifo_char(next((tmp_path / "000001 - Cloned").glob("*.sav"))).fields["ItemList"]
    assert any(s.fields["TemplateResRef"].value == "shopsword" for s in carried.value.structs)


def test_save_viewer_add_and_remove_feat(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _ifo_char, _make_char_save
    from vaultkeeper.config.settings import Settings

    save = _make_char_save(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._editing = True

    # add feat 5 via the (monkeypatched) picker; remove base feat 1 directly
    class _Picker:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def selected_id(self):
            return 5

    monkeypatch.setattr(
        "vaultkeeper.ui.dialogs.id_picker_dialog.IdPickerDialog", _Picker
    )
    monkeypatch.setattr(sgv.QInputDialog, "getText", lambda *a, **k: ("Feats Edit", True))
    monkeypatch.setattr(sgv.QMessageBox, "information", lambda *a, **k: None)

    view._add_feat()
    view._remove_feat(1, True)  # base feat -> no PRC confirm
    assert view._pending_list.count() == 2
    view._save_as_new()
    ids = {
        s.fields["Feat"].value
        for s in _ifo_char(next((tmp_path / "000001 - Feats Edit").glob("*.sav")))
        .fields["FeatList"].value.structs
    }
    assert 5 in ids and 1 not in ids


def test_save_viewer_remove_prc_feat_warns(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _make_char_save
    from vaultkeeper.config.settings import Settings

    save = _make_char_save(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._editing = True

    calls = []
    monkeypatch.setattr(
        sgv.QMessageBox, "warning",
        lambda *a, **k: calls.append(a) or sgv.QMessageBox.StandardButton.No,
    )
    view._remove_feat(9000, False)  # PRC feat -> must prompt; No -> no change
    assert calls  # a warning was shown
    assert view._session is None or not view._session.has_edits


def test_save_viewer_add_and_remove_spell(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _ifo_char, _make_char_save
    from vaultkeeper.config.settings import Settings

    save = _make_char_save(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._editing = True
    bard = next(b for b in view._ensure_session().player_spellbook() if b.class_id == 1)

    class _Picker:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def selected_id(self):
            return 300

    monkeypatch.setattr("vaultkeeper.ui.dialogs.id_picker_dialog.IdPickerDialog", _Picker)
    monkeypatch.setattr(sgv.QInputDialog, "getText", lambda *a, **k: ("Spells Edit", True))
    monkeypatch.setattr(sgv.QMessageBox, "information", lambda *a, **k: None)

    view._add_spell(bard.class_index, "KnownList0", True)  # base class -> no confirm
    view._remove_spell(bard.class_index, "KnownList0", 100, True)
    assert view._pending_list.count() == 2
    view._save_as_new()
    kl0 = {
        s.fields["Spell"].value
        for s in _ifo_char(next((tmp_path / "000001 - Spells Edit").glob("*.sav")))
        .fields["ClassList"].value.structs[bard.class_index].fields["KnownList0"].value.structs
    }
    assert 300 in kl0 and 100 not in kl0


def test_save_viewer_prc_class_spell_warns(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from tests.test_save_editor import _make_char_save
    from vaultkeeper.config.settings import Settings

    save = _make_char_save(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def _settings(self):
            return Settings()

        def set_inventory_nwn_style(self, _v):
            pass

    view = sgv.SaveGameViewer([save], _Ctrl())
    qtbot.addWidget(view)
    view._current = save
    view._editing = True
    prc = next(b for b in view._ensure_session().player_spellbook() if b.class_id == 500)

    calls = []
    monkeypatch.setattr(
        sgv.QMessageBox, "warning",
        lambda *a, **k: calls.append(a) or sgv.QMessageBox.StandardButton.No,
    )
    view._remove_spell(prc.class_index, "KnownList0", 200, False)  # PRC class -> prompt
    assert calls
    assert view._session is None or not view._session.has_edits


# Real saves on the developer's machine (skipped when absent).
_SAVES = Path.home() / "Documents" / "Neverwinter Nights" / "saves"


@pytest.mark.skipif(not _SAVES.is_dir(), reason="no local NWN saves on this box")
def test_real_save_module_info_decodes():
    saves = scan_save_games(_SAVES)
    assert saves
    info = next((s.module_info() for s in saves if s.sav_path), None)
    assert info is not None
    assert info.name and info.areas  # module name + at least one named area
