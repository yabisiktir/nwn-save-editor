"""Which spells a class casts at which level (spells.2da)."""

from __future__ import annotations

from vaultkeeper.game.spell_levels import CLASS_COLUMNS, SpellLevels

# id -> {column: level}, shaped like the real 2da rows.
_ROWS = {
    0: {"Bard": "****", "Wiz_Sorc": "6", "Cleric": "****"},   # Acid Fog
    33: {"Bard": "0", "Wiz_Sorc": "****", "Cleric": "0"},     # Cure Minor Wounds
    100: {"Bard": "0", "Wiz_Sorc": "0", "Cleric": "0"},       # Light
    152: {"Bard": "****", "Wiz_Sorc": "****", "Cleric": "4"},  # Restoration
}


def _levels() -> SpellLevels:
    return SpellLevels(_ROWS)


def test_sorcerer_and_wizard_share_a_column_as_the_game_does():
    assert CLASS_COLUMNS[9] == CLASS_COLUMNS[10] == "Wiz_Sorc"


def test_a_spell_reports_its_level_for_a_class_that_casts_it():
    assert _levels().level_for(0, 10) == 6      # Acid Fog, wizard 6
    assert _levels().level_for(33, 1) == 0      # Cure Minor Wounds, bard 0


def test_a_class_that_cannot_cast_a_spell_reports_none():
    """The bug this exists to stop: a level-6 wizard spell in a bard's level-0."""
    assert _levels().level_for(0, 1) is None


def test_an_unknown_class_reports_none_rather_than_guessing():
    assert _levels().level_for(33, 500) is None


def test_spells_at_a_level_lists_only_that_level():
    assert _levels().spells_at(1, 0) == {33, 100}
    assert _levels().spells_at(10, 6) == {0}
    assert _levels().spells_at(2, 4) == {152}


def test_a_level_the_class_has_nothing_at_is_empty():
    assert _levels().spells_at(1, 9) == set()


def test_it_says_when_it_cannot_speak_for_a_class():
    """PRC prestige casters are not in spells.2da, so their lists must not be
    silently emptied — the caller falls back to offering everything."""
    levels = _levels()
    assert levels.describes(1)
    assert not levels.describes(500)


def test_an_empty_table_describes_nothing():
    assert not SpellLevels(None).available
    assert not SpellLevels(None).describes(1)
