"""Tests for item inventory-icon resolution (game/item_icons.py)."""

from __future__ import annotations

from vaultkeeper.game.item_icons import ItemIconSource


def test_icon_candidate_derivation():
    source = ItemIconSource(None)  # no install -> reader is None
    # ModelType 0 (simple): "i<ItemClass>_<part:03d>" then the DefaultIcon fallback.
    source._base_items = {
        52: ("it_ring", "iit_ring", 0),
        0: ("wswss", "iwswss", 2),  # weapon -> DefaultIcon only
    }
    assert source._candidates(52, 1) == ["iit_ring_001", "iit_ring"]
    assert source._candidates(52, 12) == ["iit_ring_012", "iit_ring"]
    assert source._candidates(0, 5) == ["iwswss"]
    assert source._candidates(999, 1) == []  # unknown base item


def test_icon_source_unavailable_without_install(tmp_path):
    source = ItemIconSource(tmp_path)  # no data/*.key here
    assert not source.available
    assert source.icon_bytes(52, 1) is None
    assert ItemIconSource(None).icon_bytes(52, 1) is None
