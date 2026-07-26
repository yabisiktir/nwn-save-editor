"""Reader for NWN talk-table (``.tlk``) files — StrRef -> localized string.

Many GFF ``CExoLocString`` fields (e.g. a base item's ``LocalizedName``) carry no
inline text, only a *StrRef* pointing into a talk table. ``dialog.tlk`` (in the
game install under ``lang/<lang>/data/``) holds the base strings; custom content
uses its own module tlk, addressed by StrRefs from ``0x01000000`` upward.

Format (TLK V3.0): a 20-byte header (``"TLK V3.0"``, LanguageID, StringCount,
StringEntriesOffset) followed by ``StringCount`` 40-byte entries; each entry's
``OffsetToString``/``StringSize`` (at +28/+32) locate the text after
``StringEntriesOffset``. The whole file is read once and strings are sliced out on
demand.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from vaultkeeper.core.log import get_logger

logger = get_logger(__name__)

#: StrRefs at/above this value address the module's custom tlk, not ``dialog.tlk``.
CUSTOM_TLK_BASE = 0x01000000

_HEADER = struct.Struct("<8sIII")
_ENTRY = struct.Struct("<40s")
_TEXT_PRESENT = 0x0001


@dataclass
class TlkTable:
    """A loaded talk table; :meth:`get` resolves a StrRef to its string."""

    _data: bytes
    count: int
    _entries_offset: int

    def get(self, strref: int) -> str | None:
        """The string for ``strref``, ``""`` if the entry has no text, else ``None``."""
        if strref < 0 or strref >= self.count:
            return None
        base = 20 + strref * 40
        flags = struct.unpack_from("<I", self._data, base)[0]
        if not flags & _TEXT_PRESENT:
            return ""
        offset, size = struct.unpack_from("<II", self._data, base + 28)
        start = self._entries_offset + offset
        return self._data[start:start + size].decode("latin-1")


class TlkReader:
    """Loads a ``.tlk`` file into a :class:`TlkTable`."""

    def read(self, path: Path) -> TlkTable | None:
        try:
            data = path.read_bytes()
        except OSError as exc:
            logger.warning(f"Could not read tlk {path}: {exc}")
            return None
        if len(data) < 20:
            return None
        signature, _language, count, entries_offset = _HEADER.unpack_from(data, 0)
        if signature[:4] != b"TLK ":
            logger.warning(f"{path} is not a TLK file (sig {signature!r})")
            return None
        return TlkTable(data, count, entries_offset)
