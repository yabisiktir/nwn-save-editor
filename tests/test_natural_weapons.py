"""PRC's natural weapons — the claws and bites a character keeps in its VarTable."""

from __future__ import annotations

from nwnsaveeditor.natural_weapons import natural_weapons

# The shape read off the owner's real save: a claw in hand, two bites recorded.
_REAL = [
    ("ARRAY_NAT_SEC_WEAP_RESREF_1", "prc_raks_bite_m"),
    ("ARRAY_NAT_PRI_WEAP_RESREF_0", "prc_claw_1d6l_m"),
    ("ARRAY_NAT_SEC_WEAP_RESREF_0", "prc_rdd_bite_m"),
    ("PRC_PrereqDragon", "1"),
    ("X2_L_LAST_ATTACKER", "0"),
]


def test_it_finds_the_weapons_among_the_other_variables():
    found = natural_weapons(_REAL)
    assert [weapon.resref for weapon in found] == [
        "prc_claw_1d6l_m", "prc_rdd_bite_m", "prc_raks_bite_m",
    ], "primaries first, then PRC's own array order"


def test_a_recorded_weapon_that_is_not_equipped_is_still_reported():
    """This is the whole point: a Dragon Disciple's bite is part of the character
    even when the creature slots hold something else."""
    found = natural_weapons(_REAL, {"prc_claw_1d6l_m": 16384})
    by_ref = {weapon.resref: weapon for weapon in found}
    assert by_ref["prc_claw_1d6l_m"].equipped
    assert by_ref["prc_claw_1d6l_m"].equipped_slot == 16384
    assert not by_ref["prc_rdd_bite_m"].equipped


def test_the_equipped_match_ignores_case():
    found = natural_weapons([("ARRAY_NAT_PRI_WEAP_RESREF_0", "PRC_Claw_1d6l_M")],
                            {"prc_claw_1d6l_m": 16384})
    assert found[0].equipped


def test_groups_are_reported_so_secondary_attacks_read_as_secondary():
    groups = {w.resref: w.group for w in natural_weapons(_REAL)}
    assert groups["prc_claw_1d6l_m"] == "primary"
    assert groups["prc_rdd_bite_m"] == "secondary"


def test_the_label_tidies_the_resref_and_names_the_size():
    labels = {w.resref: w.label for w in natural_weapons(_REAL)}
    assert labels["prc_rdd_bite_m"] == "rdd bite (medium)"
    assert labels["prc_claw_1d6l_m"] == "claw 1d6l (medium)"


def test_an_empty_value_is_not_a_weapon():
    assert natural_weapons([("ARRAY_NAT_PRI_WEAP_RESREF_0", "")]) == []


def test_a_name_that_is_not_numbered_is_skipped_rather_than_crashing():
    assert natural_weapons([("ARRAY_NAT_PRI_WEAP_RESREF_x", "prc_claw_1d6l_m")]) == []


def test_a_character_with_none_reports_none():
    assert natural_weapons([("X2_L_LAST_ATTACKER", "0")]) == []
