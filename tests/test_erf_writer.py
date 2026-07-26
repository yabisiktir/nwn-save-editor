"""Tests for the ERF rewriter (core/formats/erf_writer.py)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from vaultkeeper.core.formats.erf_reader import ErfReader
from vaultkeeper.core.formats.erf_writer import build_erf, rewrite_erf


def _make_erf(resources: list[tuple[str, int, bytes]]) -> bytes:
    """A minimal but standard-layout ERF (160-byte header, no localized strings)."""
    entry_count = len(resources)
    keys_offset = 160
    res_offset = keys_offset + entry_count * 24
    data_start = res_offset + entry_count * 8
    header = b"MOD " + b"V1.0"
    header += struct.pack(
        "<9i", 0, 0, entry_count, 160, keys_offset, res_offset, 0, 0, -1
    )
    header += b"\x00" * 116
    keys = b""
    reslist = b""
    data = b""
    cursor = data_start
    for i, (ref, rtype, blob) in enumerate(resources):
        keys += ref.encode("ascii").ljust(16, b"\x00") + struct.pack("<iH", i, rtype) + b"\x00\x00"
        reslist += struct.pack("<Ii", cursor, len(blob))
        data += blob
        cursor += len(blob)
    return header + keys + reslist + data


def test_noop_rewrite_is_byte_identical():
    erf = _make_erf([("module", 2014, b"IFO-DATA"), ("area01", 2023, b"GIT-DATA")])
    assert build_erf(erf, {}) == erf


def test_same_size_override_changes_only_that_resource():
    erf = _make_erf([("module", 2014, b"AAAA"), ("area01", 2023, b"BBBB")])
    out = build_erf(erf, {("module", 2014): b"ZZZZ"})
    assert len(out) == len(erf)
    assert sum(1 for a, b in zip(out, erf, strict=True) if a != b) == 4


def test_override_read_back(tmp_path):
    erf = _make_erf([("module", 2014, b"AAAA"), ("area01", 2023, b"original-git")])
    out = build_erf(erf, {("area01", 2023): b"a-much-longer-git-blob"})
    p = tmp_path / "out.sav"
    p.write_bytes(out)
    er = ErfReader()
    git = er.read_resource_bytes(p, er.find_resource(p, "area01", res_type=2023))
    assert git == b"a-much-longer-git-blob"
    # the untouched resource is intact and the count is preserved
    assert er.read_resource_bytes(p, er.find_resource(p, "module", res_type=2014)) == b"AAAA"
    assert len(er.list_resources(p)) == 2


def test_override_matching_is_case_insensitive():
    erf = _make_erf([("Module", 2014, b"AAAA")])
    out = build_erf(erf, {("MODULE", 2014): b"ZZZZ"})
    er = ErfReader()
    # read back via a temp file
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as f:
        f.write(out)
        path = Path(f.name)
    assert er.read_resource_bytes(path, er.find_resource(path, "module", res_type=2014)) == b"ZZZZ"


def test_rewrite_refuses_to_overwrite_source(tmp_path):
    src = tmp_path / "a.sav"
    src.write_bytes(_make_erf([("module", 2014, b"AAAA")]))
    with pytest.raises(ValueError, match="overwrite the source"):
        rewrite_erf(src, {}, src)


def test_too_small_rejected():
    with pytest.raises(ValueError, match="too small"):
        build_erf(b"MOD V1.0", {})


# -- real saves (skipped when absent) ---------------------------------------- #
_SAVES = Path.home() / "Documents" / "Neverwinter Nights" / "saves"


@pytest.mark.skipif(not _SAVES.is_dir(), reason="no local NWN saves on this box")
def test_real_sav_noop_byte_identical():
    sav = next(iter(_SAVES.glob("*/*.sav")), None)
    assert sav is not None
    src = sav.read_bytes()
    # A faithful rewrite of the real container reproduces it byte-for-byte, which is
    # the safety bar: a no-op is a no-op, so a targeted edit is a minimal diff.
    assert build_erf(src, {}) == src
