"""Strict rule mode: what it enforces, and what it deliberately leaves alone."""

from __future__ import annotations

import pytest

from nwnfile.formats.gff import GffType
from nwnsaveeditor.rules import (
    Limits,
    limits_for,
    skill_limits,
    skill_rank_limit,
    storable_range,
)


# -- storable ranges -------------------------------------------------------- #
@pytest.mark.parametrize(
    ("gff_type", "expected"),
    [
        (GffType.BYTE, (0, 255)),
        (GffType.CHAR, (-128, 127)),
        (GffType.WORD, (0, 65535)),
        (GffType.SHORT, (-32768, 32767)),
        (GffType.INT, (-2147483648, 2147483647)),
    ],
)
def test_storable_range_matches_the_gff_type(gff_type, expected):
    assert storable_range(gff_type) == expected


def test_a_non_numeric_type_has_no_storable_range():
    assert storable_range(GffType.CEXOSTRING) is None


def test_free_mode_still_respects_what_the_field_can_hold():
    """Free mode is for breaking rules, not for corrupting the file."""
    limits = limits_for("Str", GffType.BYTE, strict=False)
    assert limits.maximum == 255, "a BYTE cannot hold more, in any mode"


# -- rules Strict enforces --------------------------------------------------- #
def test_strict_caps_current_hp_at_maximum_hp():
    limits = limits_for(
        "CurrentHitPoints", GffType.SHORT, strict=True, max_hit_points=1292
    )
    assert limits.maximum == 1292
    assert "cannot exceed" in limits.reason


def test_free_lets_current_hp_exceed_maximum_hp():
    limits = limits_for(
        "CurrentHitPoints", GffType.SHORT, strict=False, max_hit_points=1292
    )
    assert limits.maximum > 1292


def test_strict_holds_alignment_to_its_axis():
    limits = limits_for("GoodEvil", GffType.BYTE, strict=True)
    assert (limits.minimum, limits.maximum) == (0, 100)


def test_free_lets_alignment_run_to_the_byte_limit():
    limits = limits_for("GoodEvil", GffType.BYTE, strict=False)
    assert limits.maximum == 255


def test_skill_rank_caps_at_level_plus_three():
    assert skill_rank_limit(40) == 43
    assert skill_limits(strict=True, level=40).maximum == 43
    assert "level + 3" in skill_limits(strict=True, level=40).reason


def test_a_low_level_character_still_gets_a_sane_skill_cap():
    assert skill_rank_limit(0) == 3


def test_free_mode_lifts_the_skill_cap():
    assert skill_limits(strict=False, level=40).maximum == 255


# -- rules deliberately not invented ---------------------------------------- #
def test_strict_does_not_cap_ability_scores():
    """NWN has no fixed ceiling once items, levels and templates apply — inventing
    one would block legitimate edits on a real level-40 character."""
    limits = limits_for("Str", GffType.BYTE, strict=True)
    assert limits.maximum == 255
    assert limits.minimum == 1, "but a score below 1 is not a thing"


# -- clamping ---------------------------------------------------------------- #
def test_clamp_pins_a_value_into_range():
    limits = Limits(0, 100)
    assert limits.clamp(-5) == 0
    assert limits.clamp(250) == 100
    assert limits.clamp(50) == 50
