"""ERF/HAK/MOD reader — enumerate and extract the resources inside an ERF archive.

Neverwinter Nights packs game resources (models, textures, 2DAs, scripts, …) into
*ERF* containers with the type tags ``ERF``/``HAK``/``MOD``/``SAV``. This reader
parses the V1.0 layout and can list every resource and extract its bytes. It is a
faithful port of the structural half of ``ErfFileReader.vb`` and shares its layout
with the validated module reader above it (which reads ``module.ifo``
out of a ``.mod``); this module is the general-purpose extractor the hak-facing
tools (portrait/loadscreen extraction, backup inspection) build on.

**Layout (V1.0)** — 8-byte header tag + version, then six ``Int32`` header fields
(localized-string count/size, entry count, and the offsets of the localized-string
list, the key list and the resource list). Each *key* entry is a 16-byte resref +
``Int32`` resource id + ``UInt16`` resource type + 2 unused bytes (24 bytes). Each
*resource* entry (indexed by the key's resource id) is a ``UInt32`` offset + ``Int32``
size (8 bytes). The prior salvaged port never read the resource list at all (it left
every offset/size at 0), so extraction was impossible — this is a correct rewrite,
validated against real CEP haks.

**Resource types** — the ``UInt16`` type code maps to a file extension via the
standard NWN Aurora resource-type registry (:data:`RES_TYPE_EXTENSIONS`), a documented
format constant. The entries used here were spot-checked against real haks
(``3→tga``, ``10→txt``, ``2010→ncs``, ``2017→2da``, ``2025→uti``, ``2030→itp``,
``2033→dds``, ``2044→utp`` …); unknown codes fall back to ``.<code>`` so a wrong
extension is never asserted.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from nwnfile.log import get_logger

logger = get_logger(__name__)

#: Recognised ERF container tags (4-char, space-padded).
ERF_TAGS = frozenset({"ERF ", "HAK ", "MOD ", "SAV ", "NWM "})

_KEY_ENTRY_SIZE = 24  # 16 resref + 4 res-id + 2 res-type + 2 unused
_RES_ENTRY_SIZE = 8  # 4 offset + 4 size

#: Standard NWN Aurora resource-type code → file extension (no leading dot).
#: Documented registry; the commonly-encountered entries were verified against real
#: CEP haks. Extend as further codes are confirmed.
RES_TYPE_EXTENSIONS: dict[int, str] = {
    1: "bmp", 3: "tga", 4: "wav", 6: "plt", 7: "ini", 10: "txt", 2002: "mdl",
    2009: "nss", 2010: "ncs", 2012: "are", 2013: "set", 2014: "ifo", 2015: "bic",
    2016: "wok", 2017: "2da", 2022: "txi", 2023: "git", 2025: "uti", 2027: "utc",
    2029: "dlg", 2030: "itp", 2032: "utt", 2033: "dds", 2035: "uts", 2036: "ltr",
    2037: "gff", 2038: "fac", 2040: "ute", 2042: "utd", 2044: "utp", 2045: "dft",
    2046: "gic", 2047: "gui", 2051: "utm", 2052: "dwk", 2053: "pwk", 2056: "jrl",
    2058: "utw", 2060: "ssf", 2064: "ndb", 2065: "ptm", 2066: "ptt",
}


def extension_for_res_type(res_type: int) -> str:
    """The file extension (no dot) for a resource-type code (``bin`` fallback name)."""
    return RES_TYPE_EXTENSIONS.get(res_type, str(res_type))


@dataclass(frozen=True)
class ErfResource:
    """One resource inside an ERF archive."""

    resref: str  #: base name (no extension), lower-cased
    res_type: int  #: NWN resource-type code
    offset: int  #: byte offset of the resource data in the file
    size: int  #: resource data length in bytes

    @property
    def extension(self) -> str:
        return extension_for_res_type(self.res_type)

    @property
    def filename(self) -> str:
        """``resref.ext`` — the file name the resource would extract to."""
        return f"{self.resref}.{self.extension}"


@dataclass
class ErfInfo:
    """The contents of an ERF archive: its tag/version and resource list."""

    path: Path
    tag: str
    version: str
    resources: list[ErfResource]

    @property
    def is_valid(self) -> bool:
        return self.tag in ERF_TAGS


class ErfReader:
    """Reads and extracts resources from an NWN ERF/HAK/MOD archive.

    Parsed directories are cached **per reader instance**, keyed by the file's
    identity (path + size + mtime). Reading several resources out of one archive
    is the normal case — a save's ``module.ifo`` plus one ``.are`` per area — and
    each :meth:`find_resource` otherwise re-parsed the whole key table, making
    that pattern cost *areas x resources*.

    The cache is deliberately instance-scoped rather than global: a reader is
    cheap and short-lived, so a caller that wants fresh bytes after a write just
    uses a new one, and there is no cross-call staleness to invalidate. The
    identity key means even a reused reader notices an archive that changed
    underneath it.
    """

    def __init__(self) -> None:
        self._info_cache: dict[tuple[str, int, int], ErfInfo | None] = {}

    @staticmethod
    def _identity(path: Path) -> tuple[str, int, int] | None:
        """A key that changes when the file does, or ``None`` if it can't be stat'd."""
        try:
            stat = path.stat()
        except OSError:
            return None
        return (str(path), stat.st_size, stat.st_mtime_ns)

    def read_info(self, path: Path) -> ErfInfo | None:
        """Parse ``path`` and return its :class:`ErfInfo`, or ``None`` on failure.

        Cached per instance — see the class docstring.
        """
        key = self._identity(path)
        if key is not None and key in self._info_cache:
            return self._info_cache[key]
        info = self._parse_info(path)
        if key is not None:
            self._info_cache[key] = info
        return info

    def _parse_info(self, path: Path) -> ErfInfo | None:
        """Read and parse the archive's header + key/resource lists (uncached)."""
        try:
            with open(path, "rb") as f:
                tag = f.read(4).decode("ascii", "replace")
                version = f.read(4).decode("ascii", "replace")
                (
                    _loc_count,
                    _loc_size,
                    entry_count,
                    _loc_offset,
                    keys_offset,
                    res_offset,
                ) = struct.unpack("<6i", f.read(24))

                resources = self._read_resources(f, entry_count, keys_offset, res_offset)
                return ErfInfo(path=path, tag=tag, version=version, resources=resources)
        except (OSError, struct.error) as ex:
            logger.error("Unable to read ERF %s: %s", path, ex)
            return None

    @staticmethod
    def _read_resources(
        f, entry_count: int, keys_offset: int, res_offset: int
    ) -> list[ErfResource]:
        # Read all key entries first (contiguous), then resolve each id's location.
        f.seek(keys_offset)
        keys = []
        for _ in range(entry_count):
            entry = f.read(_KEY_ENTRY_SIZE)
            if len(entry) < _KEY_ENTRY_SIZE:
                break
            resref = entry[:16].rstrip(b"\x00").decode("ascii", "replace").lower()
            res_id, res_type = struct.unpack("<iH", entry[16:22])
            keys.append((resref, res_id, res_type))

        resources = []
        for resref, res_id, res_type in keys:
            f.seek(res_offset + res_id * _RES_ENTRY_SIZE)
            location = f.read(_RES_ENTRY_SIZE)
            if len(location) < _RES_ENTRY_SIZE:
                continue
            offset, size = struct.unpack("<Ii", location)
            resources.append(
                ErfResource(resref=resref, res_type=res_type, offset=offset, size=size)
            )
        return resources

    def list_resources(self, path: Path) -> list[ErfResource]:
        """Every resource in the archive (empty list on failure)."""
        info = self.read_info(path)
        return info.resources if info else []

    def find_resource(
        self, path: Path, name: str, *, res_type: int | None = None
    ) -> ErfResource | None:
        """Find a resource by ``resref`` (extension optional) or ``resref.ext``.

        Matching is case-insensitive; ``res_type`` narrows to a specific type when
        two resources share a resref across types.
        """
        target = name.lower()
        stem = target.rsplit(".", 1)[0]
        for resource in self.list_resources(path):
            if res_type is not None and resource.res_type != res_type:
                continue
            if resource.resref == stem or resource.filename == target:
                return resource
        return None

    def read_resource_bytes(self, path: Path, resource: ErfResource) -> bytes:
        """Read a resource's raw bytes from the archive."""
        with open(path, "rb") as f:
            f.seek(resource.offset)
            return f.read(resource.size)

    def extract_resource(
        self, path: Path, resource: ErfResource, dest_dir: Path
    ) -> Path | None:
        """Extract one resource to ``dest_dir/<resref.ext>``; return the path."""
        try:
            data = self.read_resource_bytes(path, resource)
            dest_dir.mkdir(parents=True, exist_ok=True)
            out = dest_dir / resource.filename
            out.write_bytes(data)
            return out
        except OSError as ex:
            logger.error("Unable to extract %s: %s", resource.filename, ex)
            return None

    def extract_all(
        self, path: Path, dest_dir: Path, *, res_type: int | None = None
    ) -> list[Path]:
        """Extract every resource (optionally filtered to ``res_type``) to ``dest_dir``."""
        extracted = []
        for resource in self.list_resources(path):
            if res_type is not None and resource.res_type != res_type:
                continue
            out = self.extract_resource(path, resource, dest_dir)
            if out is not None:
                extracted.append(out)
        return extracted
