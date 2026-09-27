"""A character whose portrait is stored only as ``PortraitId``.

NIT's ``BicFileInfo.CharacterSummary`` falls back to ``po_`` + the row's name in
``PortraitNames.txt`` (portraits.2da's BaseResRef, one line per row) when the
``Portrait`` resref is blank. The reader ignored ``PortraitId``, so such a
character had no portrait (Vaultkeeper logic audit, stage 3j).
"""

from __future__ import annotations

from pathlib import Path

from nwnfile.formats.bic_reader import BicFileReader, portrait_from_id
from nwnfile.formats.gff import Gff, GffField, GffStruct, GffType, write_gff


def _bic(tmp_path: Path, *, portrait: str, portrait_id: int) -> Path:
    root = GffStruct(struct_type=0xFFFFFFFF)
    root.fields["Portrait"] = GffField(GffType.CRESREF, portrait)
    root.fields["PortraitId"] = GffField(GffType.WORD, portrait_id)
    path = tmp_path / "pc.bic"
    path.write_bytes(write_gff(Gff("BIC ", "V3.2", root)))
    return path


def test_rows_map_one_to_one_as_in_nit() -> None:
    # LazWorks String.ToList keeps the blank first line, so line N is row N.
    assert portrait_from_id(0) == ""
    assert portrait_from_id(1) == "po_dw_f_01_"
    assert portrait_from_id(-1) == ""
    assert portrait_from_id(99999) == ""


def test_a_blank_portrait_uses_the_portrait_id(tmp_path: Path) -> None:
    info = BicFileReader().read_file(_bic(tmp_path, portrait="", portrait_id=1))
    assert info.portrait_id == 1
    assert info.portrait_resref == "po_dw_f_01_"


def test_a_portrait_resref_wins(tmp_path: Path) -> None:
    info = BicFileReader().read_file(_bic(tmp_path, portrait="po_custom_", portrait_id=1))
    assert info.portrait_resref == "po_custom_"
