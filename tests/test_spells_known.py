"""Known-spells budget from the SpellKnownTable (nwnfile/spells_known.py)."""

from __future__ import annotations

from nwnfile.spells_known import spells_known_gained


class _Reader:
    def __init__(self, tables):
        self.tables = tables

    def read_2da(self, name):
        return self.tables.get(name.lower())


def _bard_reader():
    return _Reader({
        "classes": {
            1: {"Label": "Bard", "SpellKnownTable": "CLS_SPKN_BARD"},
            4: {"Label": "Fighter", "SpellKnownTable": "****"},  # not a caster
        },
        "cls_spkn_bard": {
            0: {"Level": "1", "SpellLevel0": "4", "SpellLevel1": "****"},
            1: {"Level": "2", "SpellLevel0": "5", "SpellLevel1": "2"},
            2: {"Level": "3", "SpellLevel0": "6", "SpellLevel1": "3"},
        },
    })


def test_first_level_grants_the_cantrips():
    assert spells_known_gained(_bard_reader(), 1, 0, 1) == {0: 4}


def test_second_level_grants_a_cantrip_and_two_first_level():
    assert spells_known_gained(_bard_reader(), 1, 1, 2) == {0: 1, 1: 2}


def test_third_level_grants_one_of_each():
    assert spells_known_gained(_bard_reader(), 1, 2, 3) == {0: 1, 1: 1}


def test_a_non_caster_class_grants_nothing():
    assert spells_known_gained(_bard_reader(), 4, 0, 1) == {}


def test_an_unknown_class_grants_nothing():
    assert spells_known_gained(_bard_reader(), 999, 0, 1) == {}
