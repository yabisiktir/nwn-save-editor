"""Reader for NWN KEY/BIF archives — pull a base-game resource by resref + type.

The base game data (2da tables such as ``baseitems``, ``iprp_immuncost`` …) live in
BIF archives (``data/*.bif``) indexed by a KEY file (``data/nwn_base.key``). The KEY
maps ``(resref, restype)`` to a ``ResID`` whose top bits pick a BIF and whose low 20
bits pick the resource within that BIF's variable-resource table.

KEY V1.1: 0x40-byte header (``"KEY V1  "``, BIFCount, KeyCount, FileTableOffset,
KeyTableOffset, …); a BIF file table (12 bytes each: FileSize, FilenameOffset,
FilenameSize, Drives); a key table (22 bytes each: ResRef[16], ResType, ResID).
BIFF V1.1: header (``"BIFFV1  "``, VarResCount, FixedResCount, VarTableOffset) then
16-byte variable-resource entries (Id, Offset, FileSize, ResType).

This reads on demand (seek into the BIF), so nothing large is held in memory.
Best-effort: a missing/short file yields ``None`` rather than raising.
"""

from __future__ import annotations

import struct
from pathlib import Path

from vaultkeeper.core.log import get_logger

logger = get_logger(__name__)

RES_TYPE_2DA = 2017
_KEY_NAMES = ("nwn_base.key", "nwn_retail.key")


class KeyBifReader:
    """Indexes a KEY file and extracts resources from its BIF archives."""

    def __init__(self, game_root: Path, key_name: str = "nwn_base.key") -> None:
        self._root = game_root
        self._bifs: list[str] = []
        self._index: dict[tuple[str, int], int] = {}
        self._load(game_root / "data" / key_name)

    @classmethod
    def for_install(cls, game_root: Path | None) -> KeyBifReader | None:
        """A reader over the install's base KEY, or ``None`` if none is found."""
        if game_root is None:
            return None
        for name in _KEY_NAMES:
            if (game_root / "data" / name).is_file():
                reader = cls(game_root, name)
                if reader.available:
                    return reader
        return None

    @property
    def available(self) -> bool:
        return bool(self._index)

    def _load(self, key_path: Path) -> None:
        try:
            data = key_path.read_bytes()
        except OSError as exc:
            logger.warning(f"Could not read KEY {key_path}: {exc}")
            return
        if len(data) < 0x40 or data[:4] != b"KEY ":
            return
        bif_count, key_count, file_table_off, key_table_off = struct.unpack_from(
            "<IIII", data, 8
        )
        for i in range(bif_count):
            _size, name_off, name_len, _drives = struct.unpack_from(
                "<IIHH", data, file_table_off + i * 12
            )
            name = data[name_off:name_off + name_len].split(b"\x00", 1)[0]
            self._bifs.append(name.decode("latin-1"))
        for i in range(key_count):
            base = key_table_off + i * 22
            resref = data[base:base + 16].split(b"\x00", 1)[0].decode("latin-1").lower()
            res_type, res_id = struct.unpack_from("<HI", data, base + 16)
            self._index[(resref, res_type)] = res_id

    def read(self, resref: str, res_type: int) -> bytes | None:
        """The raw bytes of ``resref`` (of ``res_type``), or ``None`` if absent."""
        res_id = self._index.get((resref.lower(), res_type))
        if res_id is None:
            return None
        bif_index = res_id >> 20
        resource_index = res_id & 0xFFFFF
        if bif_index >= len(self._bifs):
            return None
        bif_path = self._root / self._bifs[bif_index].replace("\\", "/")
        try:
            with bif_path.open("rb") as fh:
                if fh.read(8)[:4] != b"BIFF":
                    return None
                var_count, _fixed_count, var_offset = struct.unpack("<III", fh.read(12))
                if resource_index >= var_count:
                    return None
                fh.seek(var_offset + resource_index * 16)
                _id, offset, size, _rtype = struct.unpack("<IIII", fh.read(16))
                fh.seek(offset)
                return fh.read(size)
        except OSError as exc:
            logger.warning(f"Could not read BIF {bif_path}: {exc}")
            return None

    def read_2da_text(self, resref: str) -> str | None:
        """A 2da resource decoded as text (Latin-1), or ``None``."""
        data = self.read(resref, RES_TYPE_2DA)
        return data.decode("latin-1") if data is not None else None
