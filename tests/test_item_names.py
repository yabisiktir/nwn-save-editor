"""Tests for the TLK reader + item-name resolution (dialog.tlk StrRef -> name)."""

from __future__ import annotations

import struct

from vaultkeeper.core.formats.bic_reader import InventoryItem
from vaultkeeper.core.formats.tlk_reader import TlkReader
from vaultkeeper.game.item_names import (
    ItemNameResolver,
    base_item_type,
    default_base_item_names,
    resolver_for,
)


def _make_tlk(strings: list[str]) -> bytes:
    count = len(strings)
    entries_offset = 20 + count * 40
    out = struct.pack("<8sIII", b"TLK V3.0", 0, count, entries_offset)
    data = b""
    offset = 0
    for text in strings:
        raw = text.encode("latin-1")
        entry = bytearray(40)
        struct.pack_into("<I", entry, 0, 1)  # TEXT_PRESENT
        struct.pack_into("<I", entry, 28, offset)
        struct.pack_into("<I", entry, 32, len(raw))
        out += bytes(entry)
        data += raw
        offset += len(raw)
    return out + data


def _item(name: str, strref: int = -1, contents=()) -> InventoryItem:
    return InventoryItem(
        name=name, base_item=0, tag="", resref="", stack_size=1, identified=True,
        stolen=False, description="", name_strref=strref, properties=[],
        contents=list(contents),
    )


def test_tlk_strings_decode_as_cp1252(tmp_path):
    """TLK text is Windows-1252, where 0x92 is a curly apostrophe.

    Decoded as latin-1 that byte becomes an unprintable C1 control and renders as
    a box: "Greater Archer\x92s Belt" is a real item in the owner's save, and it
    showed as "Greater Archer[]s Belt" everywhere a strref was resolved.
    """
    path = tmp_path / "dialog.tlk"
    path.write_bytes(_make_tlk(["Greater Archer\x92s Belt"]))
    table = TlkReader().read(path)
    assert table.get(0) == "Greater Archer\u2019s Belt"


def test_tlk_reader_resolves_strrefs(tmp_path):
    path = tmp_path / "dialog.tlk"
    path.write_bytes(_make_tlk(["Bag of Holding", "Ring of Nine Lives"]))
    table = TlkReader().read(path)
    assert table is not None and table.count == 2
    assert table.get(0) == "Bag of Holding"
    assert table.get(1) == "Ring of Nine Lives"
    assert table.get(2) is None  # out of range


def test_tlk_reader_rejects_non_tlk(tmp_path):
    path = tmp_path / "x.tlk"
    path.write_bytes(b"NOPE not a tlk file")
    assert TlkReader().read(path) is None


def test_resolver_names_strref_items_recursively(tmp_path):
    path = tmp_path / "dialog.tlk"
    path.write_bytes(_make_tlk(["Bag of Holding"]))
    resolver = ItemNameResolver(TlkReader().read(path))
    bag = _item("(unnamed: nw_it_contain006)", strref=0, contents=[_item("(unnamed: y)", strref=0)])
    named = _item("Custom Sword", strref=-1)
    resolver.resolve_items([bag, named])
    assert bag.name == "Bag of Holding"
    assert bag.contents[0].name == "Bag of Holding"  # recurses into containers
    assert named.name == "Custom Sword"  # inline name left untouched


def test_resolver_leaves_custom_tlk_strrefs(tmp_path):
    path = tmp_path / "dialog.tlk"
    path.write_bytes(_make_tlk(["Base"]))
    resolver = ItemNameResolver(TlkReader().read(path))
    item = _item("(unnamed: mod_item)", strref=0x01000005)  # >= custom tlk base
    resolver.resolve_items([item])
    assert item.name == "(unnamed: mod_item)"


def test_resolver_unavailable_without_tlk(tmp_path):
    resolver = resolver_for(tmp_path)  # no dialog.tlk under here
    assert not resolver.available
    item = _item("(unnamed: x)", strref=0)
    resolver.resolve_items([item])
    assert item.name == "(unnamed: x)"  # unchanged


def test_bundled_base_item_types():
    names = default_base_item_names()
    assert len(names) > 50
    assert base_item_type(52) == "Ring"
    assert base_item_type(16) == "Armor"
    assert base_item_type(999999) is None
