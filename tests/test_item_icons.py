"""Tests for item inventory-icon resolution (game/item_icons.py)."""

from __future__ import annotations

from tests.test_erf_reader import _build_erf

from nwnfile.item_icons import ItemIconSource


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


# -- armour, cloaks and helms: the three that had no per-variant icon ---------- #
#: Real rows from the installed baseitems.2da: (ItemClass, DefaultIcon, ModelType).
_ARMOUR = ("AArCl", "iit_chest", 3)
_CLOAK = ("cloak", "icloak_m_001", 1)
_HELM = ("helm", "ihelm", 1)


def _dressed() -> ItemIconSource:
    source = ItemIconSource(None)
    source._base_items = {16: _ARMOUR, 80: _CLOAK, 17: _HELM}
    return source


def test_armour_is_pictured_as_the_torso_it_puts_on_the_wearer():
    """Armour has no ModelPart1 at all — every suit shared one generic breastplate.

    Its icon is the chest part drawn on a body, so it comes from ArmorPart_Torso
    and differs by the wearer's gender.
    """
    source = _dressed()
    assert source._candidates(16, 0, armor_torso=29)[:2] == [
        "ipm_chest029", "ipf_chest029"
    ]
    # A woman's copy of the same suit is a different picture, hers first.
    assert source._candidates(16, 0, armor_torso=29, female=True)[:2] == [
        "ipf_chest029", "ipm_chest029"
    ]
    # The generic per-type icon stays, last, for anything that resolves to nothing.
    assert source._candidates(16, 0, armor_torso=29)[-1] == "iit_chest"


def test_a_suit_that_wears_a_robe_is_pictured_as_the_robe():
    source = _dressed()
    assert source._candidates(16, 0, armor_torso=29, armor_robe=5)[0] == "ipm_robe005"


def test_a_cloaks_variant_number_lives_inside_its_default_icon():
    """``icloak_m_001`` — the number is in the DefaultIcon, not after ItemClass."""
    source = _dressed()
    assert "icloak_m_006" in source._candidates(80, 6)
    assert source._candidates(80, 6)[-1] == "icloak_m_001"  # fallback still last


def test_a_helm_gets_its_own_picture_rather_than_the_generic_one():
    """Helms are ModelType 1, which the old rule excluded along with weapons."""
    source = _dressed()
    assert source._candidates(17, 13) == ["ihelm_013", "ihelm"]


def test_a_composite_weapon_still_gets_only_its_default_icon():
    """A weapon icon is assembled from three parts (``iwswss_b_011``).

    Nothing here attempts that, so it must not start guessing ``iwswss_005``.
    """
    source = ItemIconSource(None)
    source._base_items = {0: ("wswss", "iwswss", 2)}
    assert source._candidates(0, 5) == ["iwswss"]


class _FakeReader:
    """A stand-in KEY/BIF holding a few resources, by (resref, res type)."""

    def __init__(self, resources):
        self._resources = resources

    def read(self, resref, res_type):
        return self._resources.get((resref, res_type))


def test_each_candidate_is_tried_in_both_formats_before_the_next_one():
    """The bug under the bug: the right icon is a PLT, the fallback a TGA.

    Asking for every candidate's TGA first handed back the generic ``iit_chest``
    every time and never reached ``ipm_chest028`` — which looked exactly like the
    resrefs being wrong, and survived fixing them.
    """
    source = _dressed()
    source._reader = _FakeReader({
        ("ipm_chest028", ItemIconSource.PLT_RES_TYPE): b"PLT-FOR-THIS-SUIT",
        ("iit_chest", 3): b"TGA-GENERIC-BREASTPLATE",
    })
    seen = []
    source._plt_image = lambda resref: seen.append(resref) or (
        "coloured" if resref == "ipm_chest028" else None
    )
    assert source.icon_image(16, 0, armor_torso=28) == "coloured"
    assert seen[0] == "ipm_chest028"  # asked before the generic TGA was considered


def test_two_suits_of_armour_do_not_share_one_cached_picture():
    """The variant has to be in the cache key, not just in the lookup."""
    source = _dressed()
    source._plt_image = lambda resref: f"image:{resref}"
    source._reader = _FakeReader({})
    assert source.icon_image(16, 0, armor_torso=28) == "image:ipm_chest028"
    assert source.icon_image(16, 0, armor_torso=33) == "image:ipm_chest033"
