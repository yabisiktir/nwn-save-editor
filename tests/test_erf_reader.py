"""Tests for the ERF/HAK/MOD resource reader.

Uses a correctly-built synthetic ERF fixture (validated against the real layout)
plus a real-hak validation test grounded on the NIT Store CEP haks.
"""

from __future__ import annotations

import struct
from pathlib import Path

from nwnfile.formats.erf_reader import (
    ErfReader,
    extension_for_res_type,
)
from tests import real_data

NIT_STORE = real_data.nit_store()


def _build_erf(resources: list[tuple[str, int, bytes]], tag: bytes = b"HAK ") -> bytes:
    """Build a minimal valid ERF V1.0 with the given (resref, res_type, data) list.

    Layout: 32-byte header, key list (24 bytes/entry), resource list (8 bytes/entry),
    then the data blocks — matching the real NWN structure.
    """
    entry_count = len(resources)
    keys_offset = 32
    res_offset = keys_offset + entry_count * 24
    data_offset = res_offset + entry_count * 8

    header = tag + b"V1.0"
    header += struct.pack(
        "<6i", 0, 0, entry_count, keys_offset, keys_offset, res_offset
    )

    keys = b""
    reslist = b""
    blob = b""
    cursor = data_offset
    for res_id, (resref, res_type, data) in enumerate(resources):
        keys += resref.encode("ascii").ljust(16, b"\x00")
        keys += struct.pack("<iH", res_id, res_type)
        keys += b"\x00\x00"
        reslist += struct.pack("<Ii", cursor, len(data))
        blob += data
        cursor += len(data)

    return header + keys + reslist + blob


def test_list_resources_synthetic(tmp_path: Path) -> None:
    hak = tmp_path / "test.hak"
    hak.write_bytes(
        _build_erf([("worldmap", 3, b"TGADATA"), ("rules", 10, b"line\n")])
    )
    reader = ErfReader()
    info = reader.read_info(hak)
    assert info is not None and info.is_valid and info.tag == "HAK "
    by_ref = {r.resref: r for r in info.resources}
    assert by_ref["worldmap"].extension == "tga"
    assert by_ref["worldmap"].filename == "worldmap.tga"
    assert by_ref["rules"].size == len(b"line\n")


def test_find_and_extract_resource(tmp_path: Path) -> None:
    hak = tmp_path / "test.hak"
    hak.write_bytes(_build_erf([("portrait01", 3, b"IMAGEBYTES")]))
    reader = ErfReader()

    # Find by resref, by filename.
    assert reader.find_resource(hak, "portrait01").filename == "portrait01.tga"
    assert reader.find_resource(hak, "portrait01.tga") is not None
    assert reader.find_resource(hak, "missing") is None

    resource = reader.find_resource(hak, "portrait01")
    assert reader.read_resource_bytes(hak, resource) == b"IMAGEBYTES"
    out = reader.extract_resource(hak, resource, tmp_path / "out")
    assert out.name == "portrait01.tga"
    assert out.read_bytes() == b"IMAGEBYTES"


def test_extract_all_and_filter(tmp_path: Path) -> None:
    hak = tmp_path / "test.hak"
    hak.write_bytes(
        _build_erf([("a", 3, b"AAA"), ("b", 2017, b"2DA "), ("c", 3, b"CCC")])
    )
    reader = ErfReader()
    all_files = reader.extract_all(hak, tmp_path / "all")
    assert {p.name for p in all_files} == {"a.tga", "b.2da", "c.tga"}
    tgas = reader.extract_all(hak, tmp_path / "tga", res_type=3)
    assert {p.name for p in tgas} == {"a.tga", "c.tga"}


def test_bad_file_returns_none(tmp_path: Path) -> None:
    bad = tmp_path / "bad.hak"
    bad.write_bytes(b"NOT-AN-ERF")
    assert ErfReader().read_info(bad) is None  # too short → struct error → None


def test_extension_fallback_for_unknown_type() -> None:
    assert extension_for_res_type(3) == "tga"
    assert extension_for_res_type(99999) == "99999"


def test_real_hak_resources() -> None:
    """Validate against a real CEP hak: resource count, resref, type→extension."""
    import pytest

    if NIT_STORE is None:
        pytest.skip(real_data.REASON)
    hak = (
        NIT_STORE
        / "Profiles/Enhanced Edition Mods/CEP v2.x/.Mod Installer/hak/cep2_add_rules.hak"
    )
    if not hak.is_file():
        pytest.skip("that store has no CEP hak to compare against")

    reader = ErfReader()
    info = reader.read_info(hak)
    assert info is not None and info.tag == "HAK "
    assert len(info.resources) == 1
    res = info.resources[0]
    assert res.resref == "cep2_add_rules"
    assert res.res_type == 10 and res.extension == "txt"  # verified content is text
    assert reader.read_resource_bytes(hak, res) == b"cep2_add_rules.hak\n"


def test_real_hak_type_mapping() -> None:
    """Spot-check the restype→extension registry against a mixed real hak."""
    import pytest

    if NIT_STORE is None:
        pytest.skip(real_data.REASON)
    hak = (
        NIT_STORE
        / "Profiles/Enhanced Edition Mods/CEP v2.x/.Mod Installer/hak/cep2_top_v21.hak"
    )
    if not hak.is_file():
        pytest.skip("that store has no CEP hak to compare against")

    exts = {r.extension for r in ErfReader().list_resources(hak)}
    # This hak holds 2DA and item-palette (itp) resources.
    assert "2da" in exts
    assert "itp" in exts


def _bump_mtime(path: Path) -> None:
    """Push a file's mtime forward so a rewrite is unambiguously a new version.

    Rewriting within one filesystem timestamp tick can otherwise leave mtime
    unchanged, which would make these tests flaky rather than meaningful.
    """
    import os

    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))


def test_read_info_is_cached_per_instance(tmp_path: Path) -> None:
    """A reader parses one archive's directory once — reading several resources
    out of a .sav used to re-parse the whole key table per lookup."""
    path = tmp_path / "cached.hak"
    path.write_bytes(_build_erf([("a", 2017, b"AA"), ("b", 2017, b"BB")]))

    reader = ErfReader()
    parses = 0
    original = reader._parse_info

    def counting(p):
        nonlocal parses
        parses += 1
        return original(p)

    reader._parse_info = counting
    # A cached directory must still yield the *right* bytes: the offsets it hands
    # back are used to seek into the file, so a stale or crossed entry would read
    # the wrong resource rather than fail loudly.
    for _ in range(5):
        assert reader.read_resource_bytes(path, reader.find_resource(path, "a")) == b"AA"
        assert reader.read_resource_bytes(path, reader.find_resource(path, "b")) == b"BB"
    assert parses == 1  # ten lookups, one directory parse

    # A separate reader does its own parse — the cache is not global.
    assert ErfReader().find_resource(path, "a") is not None


def test_one_reader_keeps_two_archives_apart(tmp_path: Path) -> None:
    """The cache is keyed by path, so archives read through one reader can't
    answer for each other."""
    first = tmp_path / "first.hak"
    second = tmp_path / "second.hak"
    # Same resref in both, different payloads and different sizes.
    first.write_bytes(_build_erf([("shared", 2017, b"FIRST")]))
    second.write_bytes(_build_erf([("shared", 2017, b"SECOND"), ("extra", 2017, b"X")]))

    reader = ErfReader()
    assert reader.read_resource_bytes(first, reader.find_resource(first, "shared")) == b"FIRST"
    assert reader.read_resource_bytes(second, reader.find_resource(second, "shared")) == b"SECOND"
    # and again, now that both are cached
    assert reader.read_resource_bytes(first, reader.find_resource(first, "shared")) == b"FIRST"
    assert reader.find_resource(first, "extra") is None
    assert reader.find_resource(second, "extra") is not None


def test_cache_notices_a_changed_archive(tmp_path: Path) -> None:
    """The cache keys on the file's identity, so a rewritten archive is re-read."""
    path = tmp_path / "changing.hak"
    path.write_bytes(_build_erf([("before", 2017, b"AA")]))

    reader = ErfReader()
    assert reader.find_resource(path, "before") is not None
    assert reader.find_resource(path, "after") is None

    path.write_bytes(_build_erf([("after", 2017, b"BBBB")]))
    _bump_mtime(path)

    assert reader.find_resource(path, "after") is not None
    assert reader.find_resource(path, "before") is None


def test_a_same_size_rewrite_is_still_noticed(tmp_path: Path) -> None:
    """Size alone would not distinguish these — the mtime in the key does."""
    path = tmp_path / "samesize.hak"
    path.write_bytes(_build_erf([("aaa", 2017, b"AA")]))

    reader = ErfReader()
    assert reader.find_resource(path, "aaa") is not None

    path.write_bytes(_build_erf([("bbb", 2017, b"BB")]))  # identical length
    _bump_mtime(path)

    assert reader.find_resource(path, "bbb") is not None
    assert reader.find_resource(path, "aaa") is None


def test_a_missing_file_is_not_negatively_cached(tmp_path: Path) -> None:
    """An unreadable path returns None without caching, so an archive that shows
    up later is read rather than remembered as absent."""
    path = tmp_path / "appears-later.hak"

    reader = ErfReader()
    assert reader.read_info(path) is None
    assert reader.list_resources(path) == []

    path.write_bytes(_build_erf([("now", 2017, b"HERE")]))
    assert reader.read_resource_bytes(path, reader.find_resource(path, "now")) == b"HERE"


def test_an_unparseable_archive_returns_none_each_time(tmp_path: Path) -> None:
    path = tmp_path / "junk.hak"
    path.write_bytes(b"not an ERF")

    reader = ErfReader()
    assert reader.read_info(path) is None
    assert reader.read_info(path) is None  # cached negative, still None
    assert reader.list_resources(path) == []

    path.write_bytes(_build_erf([("fixed", 2017, b"OK")]))
    _bump_mtime(path)
    assert reader.find_resource(path, "fixed") is not None  # repaired, re-read
