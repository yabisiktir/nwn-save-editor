"""Tests for the ERF/HAK/MOD resource reader.

Uses a correctly-built synthetic ERF fixture (validated against the real layout)
plus a real-hak validation test grounded on the NIT Store CEP haks.
"""

from __future__ import annotations

import struct
from pathlib import Path

from vaultkeeper.core.formats.erf_reader import (
    ErfReader,
    extension_for_res_type,
)

NIT_STORE = Path("/Users/example/Documents/NIT Store")


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
    hak = (
        NIT_STORE
        / "Profiles/Enhanced Edition Mods/CEP v2.x/.Mod Installer/hak/cep2_add_rules.hak"
    )
    if not hak.is_file():
        import pytest

        pytest.skip("NIT Store CEP hak not present")

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
    hak = (
        NIT_STORE
        / "Profiles/Enhanced Edition Mods/CEP v2.x/.Mod Installer/hak/cep2_top_v21.hak"
    )
    if not hak.is_file():
        import pytest

        pytest.skip("NIT Store CEP hak not present")

    exts = {r.extension for r in ErfReader().list_resources(hak)}
    # This hak holds 2DA and item-palette (itp) resources.
    assert "2da" in exts
    assert "itp" in exts
