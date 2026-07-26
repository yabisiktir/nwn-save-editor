"""Tests for item inventory-icon resolution (game/item_icons.py)."""

from __future__ import annotations

from tests.test_erf_reader import _build_erf
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


def test_hak_lookup_disabled_without_hak_dir():
    # No hak_dir (the opt-in default) -> hak search is a no-op.
    source = ItemIconSource(None)
    assert source._hak_dir is None
    assert source._hak_bytes("iit_ring_100") is None


def test_hak_dir_ignored_when_missing(tmp_path):
    # A hak_dir that isn't a real directory is treated as "no hak search".
    source = ItemIconSource(None, hak_dir=tmp_path / "does-not-exist")
    assert source._hak_dir is None


def test_hak_lookup_finds_custom_icon(tmp_path):
    # A ring's per-variant icon lives only in a hak; the base install lacks it.
    hak_dir = tmp_path / "hak"
    hak_dir.mkdir()
    (hak_dir / "custom.hak").write_bytes(
        _build_erf([("iit_ring_100", 3, b"CUSTOM-RING-TGA")])
    )
    source = ItemIconSource(None, hak_dir=hak_dir)  # reader is None (no base game)
    source._base_items = {52: ("it_ring", "iit_ring", 0)}  # candidates -> ring_100
    assert source.icon_bytes(52, 100) == b"CUSTOM-RING-TGA"
    # Cached + index built once.
    assert source._hak_index is not None and "iit_ring_100" in source._hak_index
    # A resref no hak carries stays unresolved.
    assert source.icon_bytes(52, 7) is None
