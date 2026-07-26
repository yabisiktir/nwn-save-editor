"""Rewrite an ERF archive (``.sav``/``.mod``/``.hak``) with edited resources.

Editing a save means changing one or more resources *inside* its ``.sav`` ERF
(e.g. ``module.ifo`` for the character/stores, an ``<area>.git`` for a store). This
rebuilds the container faithfully: the header (build date, description StrRef,
reserved bytes), the localized-string block and the key list (order, resrefs,
types, ids) are all preserved verbatim; only the resource-data section is re-laid
out, substituting the bytes of any overridden resource. A no-op rewrite (no
overrides) reproduces the original **byte-for-byte** for standard-layout files.

Read-only source: the original file is never modified — output goes to a new path.
"""

from __future__ import annotations

import struct
from pathlib import Path

_HEADER_SIZE = 160
_KEY_ENTRY_SIZE = 24  # 16 resref + 4 res-id + 2 res-type + 2 unused
_RES_ENTRY_SIZE = 8  # 4 offset + 4 size


def _resref_key(resref: str, res_type: int) -> tuple[str, int]:
    return resref.rstrip("\x00").lower(), res_type


def build_erf(src: bytes, overrides: dict[tuple[str, int], bytes]) -> bytes:
    """Return a rebuilt ERF from ``src`` with ``{(resref, res_type): bytes}`` swapped.

    ``resref`` keys are matched case-insensitively. Everything ahead of the data
    region — header, localized strings, the key list and the resource list
    (including the game's pre-allocated spare slots and inter-section gaps) — is
    preserved byte-for-byte; only the resource data is re-laid out, in the original
    storage order, with overridden resources substituted and the resource list's
    offset/size entries updated. A no-op rewrite is therefore byte-identical, and a
    same-size edit differs only in that resource's bytes.
    """
    if len(src) < _HEADER_SIZE:
        raise ValueError("File too small to be a valid ERF")
    # header @ +16: EntryCount, OffsetToLocalizedString, OffsetToKeyList, OffsetToResList
    entry_count, _loc_offset, keys_offset, res_offset = struct.unpack_from("<4i", src, 16)

    # key list: res_id -> (resref, res_type)
    key_by_id: dict[int, tuple[str, int]] = {}
    for i in range(entry_count):
        base = keys_offset + i * _KEY_ENTRY_SIZE
        resref = src[base:base + 16].rstrip(b"\x00").decode("ascii", "replace").lower()
        res_id, res_type = struct.unpack_from("<iH", src, base + 16)
        key_by_id[res_id] = (resref, res_type)

    # resource list: original (offset, size) per res_id
    orig = [struct.unpack_from("<Ii", src, res_offset + i * _RES_ENTRY_SIZE)
            for i in range(entry_count)]
    data_start = min((off for off, size in orig if size > 0), default=len(src))

    overrides = {_resref_key(r, t): b for (r, t), b in overrides.items()}
    out = bytearray(src[:data_start])  # header + loc + keys + gaps + res list (verbatim)

    # Re-emit data in the original storage order (ascending offset) so an unchanged
    # file is reproduced exactly; update each res-list entry's offset/size.
    data = bytearray()
    cursor = data_start
    for res_id in sorted(range(entry_count), key=lambda i: orig[i][0]):
        resref, res_type = key_by_id.get(res_id, ("", -1))
        blob = overrides.get((resref, res_type))
        if blob is None:
            off, size = orig[res_id]
            blob = src[off:off + size]
        struct.pack_into("<Ii", out, res_offset + res_id * _RES_ENTRY_SIZE, cursor, len(blob))
        data += blob
        cursor += len(blob)
    return bytes(out + data)


def rewrite_erf(
    src_path: Path, overrides: dict[tuple[str, int], bytes], dst_path: Path
) -> None:
    """Rewrite ``src_path`` into ``dst_path`` with the given resource overrides.

    The source is read-only; ``dst_path`` must differ from it.
    """
    if dst_path.resolve() == src_path.resolve():
        raise ValueError("refusing to overwrite the source ERF in place")
    dst_path.write_bytes(build_erf(src_path.read_bytes(), overrides))
