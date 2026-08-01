"""A full GFF (V3.2) tree reader **and writer** — the basis for editing saves.

The read-only :class:`nwnfile.formats.bic_reader._GFF` decodes fields on
demand for viewing; it is lossy (it never models the whole tree) so it cannot write
a file back. This module parses a GFF into a complete, mutable tree
(:class:`GffStruct` / :class:`GffList` / :class:`LocString`) and serialises it back
to bytes. Editing a save = read → mutate the tree → write, touching only what you
change and preserving everything else.

The writer reproduces BioWare's section layout so an **unmodified** tree round-trips
**byte-for-byte** (verified against real ``.bic`` / ``.git`` / ``module.ifo``), which
is the safety bar: if a no-op rewrite is identical, a small edit is a small diff.

Value representation by field type:

* BYTE/CHAR/WORD/SHORT/DWORD/INT/DWORD64/INT64 -> ``int``
* FLOAT/DOUBLE                                 -> ``float``
* CEXOSTRING/CRESREF                           -> ``str`` (bytes preserved via
  utf-8 + ``surrogateescape``)
* CEXOLOCSTRING                                -> :class:`LocString`
* VOID                                         -> ``bytes``
* STRUCT                                       -> :class:`GffStruct`
* LIST                                         -> :class:`GffList`
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum

_HEADER = struct.Struct("<12I")
_NO_STRREF = 0xFFFFFFFF


class GffType(IntEnum):
    """GFF field type ids."""

    BYTE = 0
    CHAR = 1
    WORD = 2
    SHORT = 3
    DWORD = 4
    INT = 5
    DWORD64 = 6
    INT64 = 7
    FLOAT = 8
    DOUBLE = 9
    CEXOSTRING = 10
    CRESREF = 11
    CEXOLOCSTRING = 12
    VOID = 13
    STRUCT = 14
    LIST = 15


#: Simple types whose value is stored inline in the field's 4-byte DataOrDataOffset.
_INLINE = {
    GffType.BYTE, GffType.CHAR, GffType.WORD, GffType.SHORT,
    GffType.DWORD, GffType.INT, GffType.FLOAT,
}
#: struct.pack code for each inline type (little-endian, padded to 4 bytes on write).
_INLINE_CODE = {
    GffType.BYTE: "<B", GffType.CHAR: "<b", GffType.WORD: "<H", GffType.SHORT: "<h",
    GffType.DWORD: "<I", GffType.INT: "<i", GffType.FLOAT: "<f",
}


def _encode(text: str) -> bytes:
    return text.encode("utf-8", "surrogateescape")


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


@dataclass
class LocString:
    """A CExoLocString — a StrRef plus zero or more localized substrings."""

    strref: int = -1  # -1 == none (stored as 0xFFFFFFFF)
    substrings: list[tuple[int, str]] = field(default_factory=list)  # (string id, text)

    def text(self) -> str:
        """The first substring's text (what the viewers show), or ``""``."""
        return self.substrings[0][1] if self.substrings else ""


@dataclass
class GffField:
    """One field: its GFF type and its (typed) value."""

    type: GffType
    value: object


@dataclass
class GffStruct:
    """A GFF struct: a programmer ``struct_type`` id + ordered ``label -> field``."""

    struct_type: int = 0
    fields: dict[str, GffField] = field(default_factory=dict)

    # -- convenient typed accessors (editing helpers) --------------------- #
    def get(self, label: str):
        f = self.fields.get(label)
        return f.value if f is not None else None

    def set_scalar(self, label: str, gtype: GffType, value) -> None:
        """Set (or add) a simple/int/float/string field, keeping its type."""
        self.fields[label] = GffField(gtype, value)


@dataclass
class GffList:
    """A GFF list of structs."""

    structs: list[GffStruct] = field(default_factory=list)


@dataclass
class Gff:
    """A parsed GFF file: its 4-char type, version and root struct."""

    file_type: str
    version: str
    root: GffStruct


# --------------------------------------------------------------------------- #
# reader
# --------------------------------------------------------------------------- #
class _Reader:
    def __init__(self, data: bytes) -> None:
        if len(data) < 56:
            raise ValueError("File too small to be a valid GFF file")
        self.data = data
        self.file_type = data[0:4].decode("ascii", "replace")
        self.version = data[4:8].decode("ascii", "replace")
        if self.version != "V3.2":
            raise ValueError(f"Unsupported GFF version {self.version!r} (expected 'V3.2')")
        (
            self.struct_off, self.struct_count,
            self.field_off, self.field_count,
            self.label_off, self.label_count,
            self.fielddata_off, self.fielddata_len,
            self.fieldindices_off, self.fieldindices_len,
            self.listindices_off, self.listindices_len,
        ) = _HEADER.unpack_from(data, 8)

    def label(self, index: int) -> str:
        start = self.label_off + index * 16
        return self.data[start:start + 16].split(b"\x00", 1)[0].decode("ascii", "replace")

    def struct(self, index: int) -> GffStruct:
        base = self.struct_off + index * 12
        type_id, data_or_off, field_count = struct.unpack_from("<3I", self.data, base)
        out = GffStruct(struct_type=type_id)
        if field_count == 1:
            field_ids = [data_or_off]
        elif field_count > 1:
            start = self.fieldindices_off + data_or_off
            field_ids = struct.unpack_from(f"<{field_count}I", self.data, start)
        else:
            field_ids = []
        for fid in field_ids:
            label, gfield = self.field(fid)
            out.fields[label] = gfield
        return out

    def field(self, field_id: int) -> tuple[str, GffField]:
        base = self.field_off + field_id * 12
        type_id, label_id = struct.unpack_from("<2I", self.data, base)
        raw = self.data[base + 8:base + 12]
        gtype = GffType(type_id)
        return self.label(label_id), GffField(gtype, self.value(gtype, raw))

    def value(self, gtype: GffType, raw: bytes):
        if gtype in _INLINE:
            if gtype == GffType.FLOAT:
                return struct.unpack("<f", raw)[0]
            return struct.unpack(_INLINE_CODE[gtype], raw[: struct.calcsize(_INLINE_CODE[gtype])])[0]
        offset = struct.unpack("<I", raw)[0]
        pos = self.fielddata_off + offset
        if gtype == GffType.DWORD64:
            return struct.unpack_from("<Q", self.data, pos)[0]
        if gtype == GffType.INT64:
            return struct.unpack_from("<q", self.data, pos)[0]
        if gtype == GffType.DOUBLE:
            return struct.unpack_from("<d", self.data, pos)[0]
        if gtype == GffType.CEXOSTRING:
            length = struct.unpack_from("<I", self.data, pos)[0]
            return _decode(self.data[pos + 4:pos + 4 + length])
        if gtype == GffType.CRESREF:
            length = self.data[pos]
            return _decode(self.data[pos + 1:pos + 1 + length])
        if gtype == GffType.CEXOLOCSTRING:
            return self._locstring(pos)
        if gtype == GffType.VOID:
            length = struct.unpack_from("<I", self.data, pos)[0]
            return bytes(self.data[pos + 4:pos + 4 + length])
        if gtype == GffType.STRUCT:
            return self.struct(offset)
        if gtype == GffType.LIST:
            return self._list(offset)
        raise ValueError(f"Unknown GFF field type {gtype}")

    def _locstring(self, pos: int) -> LocString:
        _total, strref, count = struct.unpack_from("<3I", self.data, pos)
        pos += 12
        subs: list[tuple[int, str]] = []
        for _ in range(count):
            sid, length = struct.unpack_from("<2I", self.data, pos)
            pos += 8
            subs.append((sid, _decode(self.data[pos:pos + length])))
            pos += length
        return LocString(strref=-1 if strref == _NO_STRREF else strref, substrings=subs)

    def _list(self, offset: int) -> GffList:
        pos = self.listindices_off + offset
        count = struct.unpack_from("<I", self.data, pos)[0]
        ids = struct.unpack_from(f"<{count}I", self.data, pos + 4) if count else ()
        return GffList(structs=[self.struct(i) for i in ids])


def read_gff(data: bytes) -> Gff:
    """Parse GFF bytes into a full mutable :class:`Gff` tree."""
    reader = _Reader(data)
    return Gff(reader.file_type, reader.version, reader.struct(0))


# --------------------------------------------------------------------------- #
# writer
# --------------------------------------------------------------------------- #
class _Writer:
    """Serialise a :class:`Gff` tree, reproducing BioWare's section ordering.

    A single depth-first pass assigns each struct its index on entry (pre-order)
    and emits field entries as it goes, so a child's field entries land right after
    the field that references it (the field array is DFS-*interleaved*, not grouped
    by struct). Labels are de-duplicated in first-seen order. This layout makes an
    unmodified tree round-trip byte-for-byte with BioWare's own writer.
    """

    def __init__(self, gff: Gff) -> None:
        self.gff = gff
        self.struct_types: list[int] = []
        self.struct_field_ids: list[list[int]] = []  # per struct, its own field ids
        self.fields: list[bytes | None] = []  # 12-byte entries (placeholder during DFS)
        self.labels: list[str] = []
        self.label_index: dict[str, int] = {}
        self.field_data = bytearray()
        self.field_indices = bytearray()
        self.list_indices = bytearray()

    def _label(self, name: str) -> int:
        if name not in self.label_index:
            self.label_index[name] = len(self.labels)
            self.labels.append(name)
        return self.label_index[name]

    def build(self) -> bytes:
        self._emit_struct(self.gff.root)
        return self._assemble()

    def _emit_struct(self, node: GffStruct) -> int:
        """Assign this struct's index (pre-order) and emit its fields (DFS)."""
        index = len(self.struct_types)
        self.struct_types.append(node.struct_type)
        self.struct_field_ids.append([])  # filled once its fields are emitted
        field_ids = [self._emit_field(label, gf) for label, gf in node.fields.items()]
        self.struct_field_ids[index] = field_ids
        return index

    def _emit_field(self, label: str, gfield: GffField) -> int:
        field_id = len(self.fields)
        self.fields.append(None)  # reserve the slot before recursing into children
        label_id = self._label(label)
        data_or_off = self._field_payload(gfield)
        self.fields[field_id] = struct.pack("<3I", int(gfield.type), label_id, data_or_off)
        return field_id

    def _field_payload(self, gfield: GffField) -> int:
        """Return the 4-byte DataOrDataOffset word (as an int) for a field."""
        gtype, value = gfield.type, gfield.value
        if gtype in _INLINE:
            packed = struct.pack(_INLINE_CODE[gtype], value)
            return struct.unpack("<I", packed.ljust(4, b"\x00"))[0]
        if gtype == GffType.STRUCT:
            return self._emit_struct(value)  # child index (recurses, DFS)
        if gtype == GffType.LIST:
            return self._emit_list(value)
        # Complex data lives in the field-data block; return its offset.
        offset = len(self.field_data)
        self.field_data += self._complex_bytes(gtype, value)
        return offset

    def _complex_bytes(self, gtype: GffType, value) -> bytes:
        if gtype == GffType.DWORD64:
            return struct.pack("<Q", value)
        if gtype == GffType.INT64:
            return struct.pack("<q", value)
        if gtype == GffType.DOUBLE:
            return struct.pack("<d", value)
        if gtype == GffType.CEXOSTRING:
            raw = _encode(value)
            return struct.pack("<I", len(raw)) + raw
        if gtype == GffType.CRESREF:
            raw = _encode(value)
            return struct.pack("<B", len(raw)) + raw
        if gtype == GffType.VOID:
            return struct.pack("<I", len(value)) + bytes(value)
        if gtype == GffType.CEXOLOCSTRING:
            return self._locstring_bytes(value)
        raise ValueError(f"Cannot serialise field type {gtype}")

    def _locstring_bytes(self, loc: LocString) -> bytes:
        body = bytearray()
        strref = _NO_STRREF if loc.strref < 0 else loc.strref
        body += struct.pack("<2I", strref, len(loc.substrings))
        for sid, text in loc.substrings:
            raw = _encode(text)
            body += struct.pack("<2I", sid, len(raw)) + raw
        return struct.pack("<I", len(body)) + bytes(body)

    def _emit_list(self, glist: GffList) -> int:
        offset = len(self.list_indices)
        count = len(glist.structs)
        self.list_indices += struct.pack("<I", count) + b"\x00\x00\x00\x00" * count
        # DFS: assign+emit each element's whole subtree in order, backfilling its id.
        start = offset + 4
        for n, child in enumerate(glist.structs):
            struct.pack_into("<I", self.list_indices, start + n * 4, self._emit_struct(child))
        return offset

    def _assemble(self) -> bytes:
        # Build per-struct DataOrDataOffset + the field-indices block.
        struct_entries = bytearray()
        for struct_type, field_ids in zip(self.struct_types, self.struct_field_ids, strict=True):
            if len(field_ids) == 1:
                data_or_off = field_ids[0]
            elif len(field_ids) > 1:
                data_or_off = len(self.field_indices)
                self.field_indices += struct.pack(f"<{len(field_ids)}I", *field_ids)
            else:
                data_or_off = _NO_STRREF  # 0-field struct: BioWare stores 0xffffffff
            struct_entries += struct.pack("<3I", struct_type, data_or_off, len(field_ids))

        labels_block = b"".join(
            _encode(name)[:16].ljust(16, b"\x00") for name in self.labels
        )
        fields_block = b"".join(self.fields)

        struct_off = 56
        field_off = struct_off + len(struct_entries)
        label_off = field_off + len(fields_block)
        fielddata_off = label_off + len(labels_block)
        fieldindices_off = fielddata_off + len(self.field_data)
        listindices_off = fieldindices_off + len(self.field_indices)

        header = self.gff.file_type.encode("ascii").ljust(4)[:4]
        header += self.gff.version.encode("ascii").ljust(4)[:4]
        header += _HEADER.pack(
            struct_off, len(self.struct_types),
            field_off, len(self.fields),
            label_off, len(self.labels),
            fielddata_off, len(self.field_data),
            fieldindices_off, len(self.field_indices),
            # ListIndicesCount is a *byte* length, not an element count (a GFF quirk;
            # every other count in the header is an element count).
            listindices_off, len(self.list_indices),
        )
        return (
            header + bytes(struct_entries) + fields_block + labels_block
            + bytes(self.field_data) + bytes(self.field_indices) + bytes(self.list_indices)
        )


def write_gff(gff: Gff) -> bytes:
    """Serialise a :class:`Gff` tree back to GFF V3.2 bytes."""
    return _Writer(gff).build()
