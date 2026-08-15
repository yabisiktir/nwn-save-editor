"""The reserved-2DA-row matcher (nwnfile/reserved.py)."""

from __future__ import annotations

import pytest

from nwnfile.reserved import is_reserved_label


@pytest.mark.parametrize("label", [
    "", "****", "DELETED", "DELETED_SMOOTH_TALK", "RESERVED_alchemy",
    "ReservedForISCAndESS", "bio_reserved", "cep_reserved", "D20MODERN_RESERVED",
    "padding", "CEP_Padding", None,
])
def test_reserved_labels_match(label):
    assert is_reserved_label(label)


@pytest.mark.parametrize("label", [
    "Mind_Blank", "Lesser_Mind_Blank", "PointBlank", "RemoveDisease",
    "Empty_Body", "empty_potion", "blank_scroll", "Rapier", "Fire", "Whirlwind Attack",
])
def test_real_entries_are_not_reserved(label):
    assert not is_reserved_label(label)


@pytest.mark.parametrize("label", [
    "bio reserved", "cep reserved", "D20MODERN RESERVED", "CEP Padding",
])
def test_space_separated_display_labels_also_match(label):
    assert is_reserved_label(label)


@pytest.mark.parametrize("label", ["mind blank", "point blank", "remove disease"])
def test_space_separated_real_names_do_not_match(label):
    assert not is_reserved_label(label)
