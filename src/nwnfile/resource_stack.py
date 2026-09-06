"""A read-any-resource view over a set of haks plus the base game.

:class:`~nwnfile.item_icons.ItemIconSource` only indexes icons; relocating an
item's *worn* appearance needs its model (``.mdl``) and the textures the model
references (``.tga`` / ``.plt`` / ``.dds`` / ``.txi``), which live anywhere in the
hak set. This indexes those types once (earlier haks win, matching load order),
reads raw bytes on demand, and can tell whether a resource is present — enough to
copy an item's model and only the dependency textures the target module lacks.
"""
from __future__ import annotations

import re
from pathlib import Path

from nwnfile.formats.erf_reader import ErfReader
from nwnfile.formats.key_bif_reader import KeyBifReader

MDL = 2002
TGA, PLT, TXI, DDS1, DDS2 = 3, 6, 2005, 2064, 2065
ART_TYPES = frozenset({MDL, TGA, PLT, TXI, DDS1, DDS2})
_TEX_TYPES = (PLT, TGA, DDS1, DDS2, TXI)  # tried in this order for a dependency
#: model resref tokens that could name a texture (also catches node names, which
#: simply never resolve as a texture and are skipped).
_TOKEN = re.compile(rb"[A-Za-z0-9_]{3,16}")
_NOT_TEXTURE = {"null", "black", "white", "default"}


class ResourceStack:
    def __init__(self, hak_paths, game_root: Path | None,
                 res_types=ART_TYPES) -> None:
        self._erf = ErfReader()
        self._index: dict[tuple[str, int], tuple[Path, object]] = {}
        for hak in hak_paths:
            try:
                for res in self._erf.list_resources(hak):
                    if res.res_type in res_types:
                        self._index.setdefault((res.resref.lower(), res.res_type), (hak, res))
            except Exception:  # noqa: BLE001 — a bad hak just contributes nothing
                continue
        self._base = KeyBifReader.for_install(game_root)

    def read(self, resref: str, res_type: int) -> bytes | None:
        entry = self._index.get((resref.lower(), res_type))
        if entry is not None:
            try:
                return self._erf.read_resource_bytes(*entry)
            except Exception:  # noqa: BLE001
                return None
        return self._base.read(resref, res_type) if self._base is not None else None

    def has(self, resref: str, res_type: int) -> bool:
        if (resref.lower(), res_type) in self._index:
            return True
        return self._base is not None and self._base.read(resref, res_type) is not None

    def matching(self, pattern: str, res_type: int) -> list[str]:
        """Indexed resrefs of ``res_type`` whose name matches ``pattern`` (a regex).
        Only searches the hak index (not base) — used to enumerate the gender/pheno
        variants of a part or cloak the source ships."""
        rx = re.compile(pattern)
        return sorted(
            resref for (resref, rt) in self._index
            if rt == res_type and rx.match(resref)
        )

    def has_texture(self, resref: str) -> bool:
        return any(self.has(resref, t) for t in _TEX_TYPES)

    def texture_type(self, resref: str) -> int | None:
        """The type a texture resref resolves as here, or ``None``."""
        for t in _TEX_TYPES:
            if self.has(resref, t):
                return t
        return None


def rename_model(data: bytes, new_name: str) -> bytes:
    """Return an ``.mdl`` with its own internal model name set to ``new_name``.

    A model is loaded by filename but identified/linked by the name *inside* it, so
    relocating one to a new resref (a free appearance slot) without rewriting that
    name leaves the file named ``wswsc_b_254`` but calling itself ``wswsc_b_112`` —
    and the engine then fails to render it (weapons especially). Only the model's
    *own* name is changed; a ``setsupermodel`` parent reference is left alone.
    """
    name = new_name.encode("latin1")[:63]
    if data[:4] == b"\x00\x00\x00\x00":  # binary MDL: name is 64 bytes at offset 20
        if len(data) < 84:
            return data
        b = bytearray(data)
        b[20:84] = name.ljust(64, b"\x00")
        return bytes(b)
    # ASCII MDL: the name follows newmodel / donemodel, and is the first token of
    # setsupermodel (whose second token, the parent, must be preserved).
    data = re.sub(rb"(?im)^(\s*(?:newmodel|donemodel)\s+)\S+", rb"\g<1>" + name, data)
    return re.sub(rb"(?im)^(\s*setsupermodel\s+)\S+", rb"\g<1>" + name, data)


def model_texture_candidates(model_bytes: bytes) -> list[str]:
    """Lower-cased tokens in a model that might name a texture. Works for ASCII and
    binary models alike; non-texture tokens (node names) are harmless because the
    caller only copies the ones that actually resolve as a texture."""
    seen: list[str] = []
    for m in _TOKEN.finditer(model_bytes):
        tok = m.group(0).decode("latin1").lower()
        if tok not in _NOT_TEXTURE and tok not in seen:
            seen.append(tok)
    return seen
