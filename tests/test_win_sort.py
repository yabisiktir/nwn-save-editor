"""Tests for the Windows natural-sort reproduction (win_compare)."""

from __future__ import annotations

from functools import cmp_to_key

import pytest

from vaultkeeper.core.win_sort import win_compare


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("a", "a", 0),
        ("a", "b", -1),
        ("b", "a", 1),
        # Case-insensitive
        ("Mod", "mod", 0),
        ("ABC", "abc", 0),
        # Numeric-aware (the whole point): 2 < 10, not "10" < "2"
        ("Mod 2", "Mod 10", -1),
        ("Mod 10", "Mod 2", 1),
        ("file9", "file10", -1),
        ("100", "99", 1),
        # Prefix is shorter -> earlier
        ("abc", "abcd", -1),
        ("abcd", "abc", 1),
        # Leading zeros: equal value, fewer zeros first
        ("01", "1", 1),
        ("1", "01", -1),
        # Mixed digit/letter position compares as chars
        ("a1", "ab", -1),  # '1' (0x31) < 'b'
    ],
)
def test_win_compare(a: str, b: str, expected: int) -> None:
    assert _sign(win_compare(a, b)) == expected


def test_total_order_matches_expected_sequence() -> None:
    names = ["Mod 10", "Mod 2", "mod 1", "Mod 100", "Alpha", "beta"]
    ordered = sorted(names, key=cmp_to_key(win_compare))
    assert ordered == ["Alpha", "beta", "mod 1", "Mod 2", "Mod 10", "Mod 100"]


def test_antisymmetry_and_consistency() -> None:
    samples = ["800. Worth Playing", "80. Ok", "8. Meh", "8a", "8", "aardvark", "Zeta"]
    for a in samples:
        for b in samples:
            assert _sign(win_compare(a, b)) == -_sign(win_compare(b, a))
