"""Undo, redo and per-change discard on :class:`SaveEditor`.

These are built by replaying the command log rather than by inverting each edit,
so the tests deliberately cover several *kinds* of edit — the whole point of the
design is that no kind needs its own inverse.
"""

from __future__ import annotations

import pytest

from nwnsaveeditor.save_editor import SaveEditor
from tests.test_save_editor import _ifo_char, _make_char_save, _make_char_save_with_details


@pytest.fixture
def editor(tmp_path) -> SaveEditor:
    return SaveEditor(_make_char_save_with_details(tmp_path))


def _value(editor: SaveEditor, field: str):
    return next(f for f in editor.player_fields() if f.field == field).value


# -- the stack ------------------------------------------------------------- #
def test_a_fresh_editor_has_nothing_to_undo(editor):
    assert not editor.can_undo
    assert not editor.can_redo
    assert editor.undo() is False
    assert editor.redo() is False


def test_undo_reverses_the_last_edit_and_redo_reapplies_it(editor):
    before = _value(editor, "Gold")
    editor.set_character_field("Gold", before + 77, where="Gold")
    assert editor.can_undo and not editor.can_redo

    assert editor.undo() is True
    assert _value(editor, "Gold") == before
    assert not editor.has_edits
    assert editor.can_redo

    assert editor.redo() is True
    assert _value(editor, "Gold") == before + 77
    assert editor.has_edits


def test_undo_leaves_earlier_edits_alone(editor):
    gold, strength = _value(editor, "Gold"), _value(editor, "Str")
    editor.set_character_field("Gold", gold + 1, where="Gold")
    editor.set_character_field("Str", strength + 1, where="Strength")
    editor.undo()

    assert _value(editor, "Str") == strength, "the undone edit is reversed"
    assert _value(editor, "Gold") == gold + 1, "the earlier edit survives"
    assert [c.key for c in editor.pending_changes()] == ["Gold"]


def test_a_new_edit_drops_the_redo_branch(editor):
    gold = _value(editor, "Gold")
    editor.set_character_field("Gold", gold + 1, where="Gold")
    editor.undo()
    assert editor.can_redo

    editor.set_character_field("Str", _value(editor, "Str") + 1, where="Strength")
    assert not editor.can_redo
    assert editor.undone_changes() == []


# -- coalescing ------------------------------------------------------------ #
def test_a_run_of_edits_to_one_field_is_a_single_undo_step(editor):
    """A stepper fires per increment; each must not become its own undo step."""
    before = _value(editor, "Gold")
    for offset in range(1, 11):
        editor.set_character_field("Gold", before + offset, where="Gold")

    assert len(editor._log) == 1
    editor.undo()
    assert _value(editor, "Gold") == before
    assert not editor.has_edits


def test_edits_to_different_fields_stay_separate_steps(editor):
    editor.set_character_field("Gold", _value(editor, "Gold") + 1, where="Gold")
    editor.set_character_field("Str", _value(editor, "Str") + 1, where="Strength")
    assert len(editor._log) == 2


# -- undone entries stay visible ------------------------------------------- #
def test_undone_changes_are_reported_separately_from_staged_ones(editor):
    editor.set_character_field("Gold", _value(editor, "Gold") + 1, where="Gold")
    editor.set_character_field("Str", _value(editor, "Str") + 1, where="Strength")
    editor.undo()

    assert [c.where for c in editor.pending_changes()] == ["Gold"]
    assert [c.where for c in editor.undone_changes()] == ["Strength"]
    assert editor.undone_count == 1

    editor.redo()
    assert editor.undone_changes() == []


def test_undone_edits_are_not_written(editor, tmp_path):
    gold = _value(editor, "Gold")
    editor.set_character_field("Gold", gold + 500, where="Gold")
    editor.undo()
    editor.set_character_field("Str", _value(editor, "Str") + 2, where="Strength")

    new_save = editor.save_as(tmp_path / "out")
    char = _ifo_char(new_save.sav_path)
    assert char.fields["Gold"].value == gold, "an undone edit must not reach the file"


# -- per-row discard -------------------------------------------------------- #
def test_discarding_one_change_keeps_the_others(editor):
    gold, strength = _value(editor, "Gold"), _value(editor, "Str")
    editor.set_character_field("Gold", gold + 1, where="Gold")
    editor.set_character_field("Str", strength + 1, where="Strength")

    assert editor.discard_change(("char-field", "Gold")) is True
    assert _value(editor, "Gold") == gold
    assert _value(editor, "Str") == strength + 1
    assert [c.key for c in editor.pending_changes()] == ["Str"]


def test_discarding_a_change_edited_twice_drops_every_command_behind_it(editor):
    """Editing a field twice makes two commands but one ledger row; discarding the
    row has to drop both, or the first edit would silently survive."""
    gold = _value(editor, "Gold")
    editor.set_character_field("Gold", gold + 1, where="Gold")
    editor.set_character_field("Str", _value(editor, "Str") + 1, where="Strength")
    editor.set_character_field("Gold", gold + 2, where="Gold")

    editor.discard_change(("char-field", "Gold"))
    assert _value(editor, "Gold") == gold
    assert not any(c.key == "Gold" for c in editor.pending_changes())


def test_discarding_an_unknown_change_reports_false(editor):
    assert editor.discard_change(("char-field", "NotAField")) is False


# -- kinds that have no natural inverse ------------------------------------- #
def test_undo_reverses_a_feat_addition(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    before = {fid for fid, _n, _b in editor.player_feats()}
    new_id = next(i for i in range(1, 500) if i not in before)

    editor.add_feat(new_id)
    assert new_id in {fid for fid, _n, _b in editor.player_feats()}
    editor.undo()
    assert {fid for fid, _n, _b in editor.player_feats()} == before


def test_undo_reverses_an_item_clone(tmp_path):
    """A clone has no inverse operation — replay is what makes this work."""
    from tests.test_save_editor import _make_char_save_with_git

    editor = SaveEditor(_make_char_save_with_git(tmp_path))
    before = len(editor.player_items())
    editor.add_item_from_area("area1", "shopsword", where="Shop Sword")
    assert len(editor.player_items()) == before + 1

    editor.undo()
    assert len(editor.player_items()) == before
    assert not editor.has_edits


def test_undo_reverses_a_removed_item_property(tmp_path):
    """Removing a property discards a whole GFF struct; replay restores it."""
    editor = SaveEditor(_make_char_save(tmp_path))
    item = next(i for i in editor.player_items() if i.properties)
    before = len(item.properties)

    editor.remove_item_property(item.path, item.properties[0].index, where=item.name)
    after = next(i for i in editor.player_items() if tuple(i.path) == tuple(item.path))
    assert len(after.properties) == before - 1

    editor.undo()
    restored = next(i for i in editor.player_items() if tuple(i.path) == tuple(item.path))
    assert len(restored.properties) == before


def test_discard_clears_the_undo_history_too(editor):
    editor.set_character_field("Gold", _value(editor, "Gold") + 1, where="Gold")
    editor.discard()
    assert not editor.can_undo and not editor.can_redo
    assert editor.undone_changes() == []
