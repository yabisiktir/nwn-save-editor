"""Caching keyed on the install, so there is nothing to invalidate."""

from __future__ import annotations

from pathlib import Path

from nwnfile import cache


def test_the_same_install_is_read_once():
    calls = []

    @cache.by_install
    def build(root, hak=None):
        calls.append(root)
        return object()

    first = build(Path("/a"), Path("/a/hak"))
    assert build(Path("/a"), Path("/a/hak")) is first
    assert len(calls) == 1


def test_a_different_install_is_a_different_answer():
    """The whole point: a new folder is a new key, not a stale entry."""

    @cache.by_install
    def build(root, hak=None):
        return object()

    assert build(Path("/a")) is not build(Path("/b"))


def test_the_hak_folder_is_part_of_the_key():
    """PRC's hak changes what the tables say, so it cannot be ignored."""

    @cache.by_install
    def build(root, hak=None):
        return object()

    assert build(Path("/a"), Path("/one")) is not build(Path("/a"), Path("/two"))


def test_no_game_folder_is_a_key_like_any_other():
    @cache.by_install
    def build(root, hak=None):
        return object()

    assert build(None) is build(None)


def test_it_does_not_grow_without_bound():
    """The keys are folders a person chose, so a handful is plenty."""

    @cache.by_install
    def build(root, hak=None):
        return object()

    kept = [build(Path(f"/install{i}")) for i in range(cache.MAX_ENTRIES + 2)]
    assert build(Path("/install0")) is not kept[0], "the oldest was evicted"
    assert build(Path(f"/install{cache.MAX_ENTRIES + 1}")) is kept[-1], "the newest stays"


def test_use_keeps_an_entry_alive():
    @cache.by_install
    def build(root, hak=None):
        return object()

    first = build(Path("/a"))
    for i in range(cache.MAX_ENTRIES):
        build(Path(f"/filler{i}"))
        build(Path("/a"))  # keep touching it
    assert build(Path("/a")) is first


def test_clear_empties_every_cache():
    """For tests, and for a caller that knows the files on disk changed."""

    @cache.by_install
    def build(root, hak=None):
        return object()

    first = build(Path("/a"))
    cache.clear()
    assert build(Path("/a")) is not first


def test_the_real_factories_are_keyed():
    """If one of these loses its decorator, a folder change goes stale again."""
    from nwnfile.item_names import resolver_for
    from nwnfile.item_property_tables import ItemPropertyTables
    from nwnfile.look_tables import LookTables
    from nwnsaveeditor.spell_levels import SpellLevels

    for factory in (ItemPropertyTables.for_install, LookTables.for_install,
                    SpellLevels.for_install, resolver_for):
        assert hasattr(factory, "cache_clear"), f"{factory} is not install-keyed"


def test_the_icon_source_is_keyed_too():
    """It indexes the whole KEY/BIF, so rebuilding it per window is the slow one."""
    from nwnfile.item_icons import icon_source_for

    assert hasattr(icon_source_for, "cache_clear")
