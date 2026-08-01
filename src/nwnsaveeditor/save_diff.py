"""Compare two saves field by field.

Used by the Backups & Diff screen to answer "what actually differs between this
backup and the save I have now?". Resources are compared by bytes first — most of
a save is identical between a backup and its successor, and there is no point
parsing what has not moved — and only the ones that differ are decoded and walked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from nwnfile.formats.erf_reader import ErfReader
from nwnfile.formats.gff import Gff, GffList, GffStruct, read_gff
from nwnsaveeditor.save_game import SaveGame

#: Value shown for a path that exists on only one side.
MISSING = object()


@dataclass
class FieldDiff:
    """One differing field, located by its path through the GFF tree."""

    path: str  #: e.g. "Mod_PlayerList[0]/Gold"
    before: object
    after: object

    @property
    def kind(self) -> str:
        if self.before is MISSING:
            return "added"
        if self.after is MISSING:
            return "removed"
        return "changed"

    def text(self, value: object) -> str:
        return "—" if value is MISSING else str(value)


@dataclass
class ResourceDiff:
    """The differences in one resource of the save."""

    name: str
    fields: list[FieldDiff] = field(default_factory=list)
    #: set when the resource differs but could not be decoded as GFF.
    opaque: bool = False

    @property
    def count(self) -> int:
        return len(self.fields)


@dataclass
class SaveDiff:
    """Every resource that differs between two saves."""

    resources: list[ResourceDiff] = field(default_factory=list)
    #: resources present on only one side, by name.
    only_in_a: list[str] = field(default_factory=list)
    only_in_b: list[str] = field(default_factory=list)

    @property
    def total_fields(self) -> int:
        return sum(resource.count for resource in self.resources)

    @property
    def is_empty(self) -> bool:
        return not self.resources and not self.only_in_a and not self.only_in_b


def flatten(gff: Gff) -> dict[str, object]:
    """The tree as ``path -> scalar value``, for diffing.

    Lists are indexed (``ItemList[3]``) and structs recursed into. Only leaf
    scalars are emitted; a container's identity is carried by its children's paths.
    """
    out: dict[str, object] = {}
    _walk_struct(gff.root, "", out)
    return out


def _walk_struct(struct: GffStruct, prefix: str, out: dict[str, object]) -> None:
    for label, entry in struct.fields.items():
        path = f"{prefix}/{label}" if prefix else label
        value = entry.value
        if isinstance(value, GffStruct):
            _walk_struct(value, path, out)
        elif isinstance(value, GffList):
            for index, child in enumerate(value.structs):
                _walk_struct(child, f"{path}[{index}]", out)
        else:
            out[path] = _scalar(value)


def _scalar(value: object) -> object:
    """Reduce a leaf to something comparable and printable."""
    substrings = getattr(value, "substrings", None)
    if substrings is not None:  # LocString
        text = getattr(value, "text", None)
        return text() if callable(text) else str(value)
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    return value


def diff_gff(before: Gff, after: Gff, *, limit: int = 500) -> list[FieldDiff]:
    """Field-level differences between two decoded resources."""
    left, right = flatten(before), flatten(after)
    diffs: list[FieldDiff] = []
    for path in sorted(set(left) | set(right)):
        a, b = left.get(path, MISSING), right.get(path, MISSING)
        if a is MISSING or b is MISSING or a != b:
            diffs.append(FieldDiff(path, a, b))
            if len(diffs) >= limit:
                break
    return diffs


def diff_saves(before: SaveGame, after: SaveGame, *, limit: int = 500) -> SaveDiff:
    """Compare two saves resource by resource, then field by field."""
    result = SaveDiff()
    if before.sav_path is None or after.sav_path is None:
        return result

    reader = ErfReader()
    left = _resources(reader, before.sav_path)
    right = _resources(reader, after.sav_path)

    result.only_in_a = sorted(set(left) - set(right))
    result.only_in_b = sorted(set(right) - set(left))

    for name in sorted(set(left) & set(right)):
        a_bytes = reader.read_resource_bytes(before.sav_path, left[name])
        b_bytes = reader.read_resource_bytes(after.sav_path, right[name])
        if a_bytes == b_bytes:
            continue  # identical: nothing to decode or report
        try:
            fields = diff_gff(read_gff(a_bytes), read_gff(b_bytes), limit=limit)
        except Exception:
            result.resources.append(ResourceDiff(name=name, opaque=True))
            continue
        result.resources.append(ResourceDiff(name=name, fields=fields))
    return result


def _resources(reader: ErfReader, sav_path: Path) -> dict[str, object]:
    """``"resref.ext" -> resource entry`` for every resource in a ``.sav``."""
    return {
        f"{res.resref}.{res.extension}": res for res in reader.list_resources(sav_path)
    }
