"""Tests for the KEY/BIF reader (extract a base-game resource by resref + type)."""

from __future__ import annotations

import struct

from nwnfile.formats.key_bif_reader import RES_TYPE_2DA, KeyBifReader


def _write_key_bif(root, resref: str, res_type: int, payload: bytes) -> None:
    """Write a minimal one-resource ``data/nwn_base.key`` + ``data/test.bif`` under root."""
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)

    # BIF: 20-byte header, one 16-byte var entry, then the payload.
    data_offset = 20 + 16
    entry = struct.pack("<IIII", 0, data_offset, len(payload), res_type)
    bif = struct.pack("<8sIII", b"BIFFV1  ", 1, 0, 20) + entry + payload
    (data / "test.bif").write_bytes(bif)

    # KEY: 0x40 header, one 12-byte file entry, one 22-byte key entry, then filename.
    bif_name = b"data/test.bif"
    file_table_off = 0x40
    key_table_off = file_table_off + 12
    name_off = key_table_off + 22
    header = struct.pack(
        "<8sIIII", b"KEY V1  ", 1, 1, file_table_off, key_table_off
    ) + b"\x00" * (0x40 - 24)
    file_entry = struct.pack("<IIHH", len(bif), name_off, len(bif_name), 0)
    key_entry = resref.encode("latin-1").ljust(16, b"\x00") + struct.pack("<HI", res_type, 0)
    (data / "nwn_base.key").write_bytes(header + file_entry + key_entry + bif_name)


def test_reads_2da_resource(tmp_path):
    payload = b"2DA V2.0\n\n   Name\n0   Foo\n"
    _write_key_bif(tmp_path, "baseitems", RES_TYPE_2DA, payload)
    reader = KeyBifReader.for_install(tmp_path)
    assert reader is not None and reader.available
    assert reader.read_2da_text("baseitems") == payload.decode("latin-1")
    assert reader.read_2da_text("BASEITEMS") == payload.decode("latin-1")  # case-insensitive


def test_missing_resource_returns_none(tmp_path):
    _write_key_bif(tmp_path, "baseitems", RES_TYPE_2DA, b"2DA V2.0\n")
    reader = KeyBifReader.for_install(tmp_path)
    assert reader.read("nope", RES_TYPE_2DA) is None


def test_no_install_returns_none(tmp_path):
    assert KeyBifReader.for_install(tmp_path) is None  # no data/*.key
    assert KeyBifReader.for_install(None) is None
