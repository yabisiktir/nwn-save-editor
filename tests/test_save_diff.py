"""Field-level diffing of two saves, and the backups an overwrite leaves behind."""

from __future__ import annotations

from datetime import datetime

from tests.test_save_editor import _make_char_save, _make_char_save_with_details
from vaultkeeper.game.backups import Backup, list_backups, restore
from vaultkeeper.game.save_diff import MISSING, diff_saves, flatten
from vaultkeeper.game.save_editor import SaveEditor


# -- flattening ------------------------------------------------------------- #
def test_flatten_indexes_lists_and_recurses_into_structs(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    flat = flatten(editor.raw_tree("module.ifo"))
    assert any(path.startswith("Mod_PlayerList[0]/") for path in flat)
    assert all(not isinstance(v, (dict, list)) for v in flat.values())


# -- diffing ---------------------------------------------------------------- #
def test_two_identical_saves_report_no_differences(tmp_path):
    save = _make_char_save(tmp_path)
    assert diff_saves(save, save).is_empty


def test_an_edited_field_is_reported_with_both_values(tmp_path):
    original = _make_char_save_with_details(tmp_path, name="000001 - before")
    editor = SaveEditor(original)
    editor.set_character_field("Gold", 4242, where="Gold")
    edited = editor.save_as(tmp_path / "000002 - after")

    diff = diff_saves(original, edited)
    assert not diff.is_empty
    changes = [c for resource in diff.resources for c in resource.fields]
    gold = next(c for c in changes if c.path.endswith("/Gold"))
    assert gold.after == 4242
    assert gold.before != 4242
    assert gold.kind == "changed"


def test_only_the_resources_that_changed_are_reported(tmp_path):
    """Most of a save is untouched; comparing bytes first keeps the diff honest."""
    original = _make_char_save_with_details(tmp_path, name="000001 - before")
    editor = SaveEditor(original)
    editor.set_character_field("Gold", 99, where="Gold")
    edited = editor.save_as(tmp_path / "000002 - after")

    diff = diff_saves(original, edited)
    names = [resource.name for resource in diff.resources]
    assert any(name.startswith("module") for name in names)
    assert len(names) <= 2, f"only the character resources should differ, got {names}"


def test_a_field_present_on_one_side_only_is_marked(tmp_path):
    from vaultkeeper.core.formats.gff import GffField, GffType

    original = _make_char_save_with_details(tmp_path, name="000001 - before")
    editor = SaveEditor(original)
    editor.set_character_field("Gold", 7, where="Gold")
    player = editor._player_struct(editor._module_tree())
    player.fields["BrandNewField"] = GffField(GffType.INT, 5)
    edited = editor.save_as(tmp_path / "000002 - after")

    diff = diff_saves(original, edited)
    changes = [c for resource in diff.resources for c in resource.fields]
    added = next(c for c in changes if c.path.endswith("/BrandNewField"))
    assert added.kind == "added"
    assert added.before is MISSING
    assert added.text(added.before) == "—"


def test_the_diff_respects_its_limit(tmp_path):
    original = _make_char_save_with_details(tmp_path, name="000001 - before")
    editor = SaveEditor(original)
    editor.set_character_field("Gold", 3, where="Gold")
    edited = editor.save_as(tmp_path / "000002 - after")

    diff = diff_saves(original, edited, limit=1)
    assert all(resource.count <= 1 for resource in diff.resources)


# -- backups ---------------------------------------------------------------- #
def test_no_backup_folder_lists_nothing(tmp_path):
    assert list_backups(None) == []
    assert list_backups(tmp_path / "nope") == []


def test_an_overwrite_archives_the_previous_save(tmp_path):
    saves = tmp_path / "saves"
    saves.mkdir()
    save = _make_char_save_with_details(saves, name="000001 - target")
    backup_dir = tmp_path / "vaultkeeper_backups"

    editor = SaveEditor(save)
    editor.set_character_field("Gold", 1234, where="Gold")
    editor.save_as(save.folder, overwrite=True, backup_dir=backup_dir)

    backups = list_backups(backup_dir)
    assert len(backups) == 1
    assert backups[0].original_name == "000001 - target"
    assert backups[0].taken is not None
    assert backups[0].size > 0


def test_backups_are_listed_newest_first(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for stamp in ("20260101-010101", "20260301-030303", "20260201-020202"):
        folder = backup_dir / f"{stamp} - save"
        _make_char_save(backup_dir, name=folder.name)
    stamps = [b.taken for b in list_backups(backup_dir)]
    assert stamps == sorted(stamps, reverse=True)


def test_a_folder_that_is_not_ours_is_still_listed(tmp_path):
    """A save folder dropped in by hand should be visible, not silently hidden."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _make_char_save(backup_dir, name="hand-copied save")
    backups = list_backups(backup_dir)
    assert [b.original_name for b in backups] == ["hand-copied save"]
    assert backups[0].taken is None


def test_restoring_copies_into_a_free_folder_and_keeps_the_backup(tmp_path):
    saves = tmp_path / "saves"
    saves.mkdir()
    _make_char_save(saves, name="000001 - existing")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    source = _make_char_save(backup_dir, name="20260101-010101 - old save")
    backup = Backup(
        folder=source.folder, original_name="old save", taken=datetime(2026, 1, 1)
    )

    restored = restore(backup, saves)
    assert restored.folder.parent == saves
    assert restored.folder.name.endswith("old save")
    assert restored.folder.name != "000001 - existing"
    assert (saves / "000001 - existing").is_dir(), "nothing existing was replaced"
    assert source.folder.is_dir(), "the backup itself is kept"
    assert restored.sav_path is not None


def test_two_overwrites_in_the_same_second_keep_separate_backups(tmp_path):
    """The stamp is second-resolution, and shutil.move onto an existing directory
    moves *into* it — which nested one backup inside another."""
    saves = tmp_path / "saves"
    saves.mkdir()
    save = _make_char_save_with_details(saves, name="000001 - target")
    backup_dir = tmp_path / "backups"

    for gold in (11, 22):
        editor = SaveEditor(save)
        editor.set_character_field("Gold", gold, where="Gold")
        editor.save_as(save.folder, overwrite=True, backup_dir=backup_dir)

    backups = list_backups(backup_dir)
    assert len(backups) == 2, [b.folder.name for b in backups]
    assert all(b.original_name == "000001 - target" for b in backups)
    for backup in backups:
        assert backup.save.sav_path is not None, "each backup is a save, not a nest"
