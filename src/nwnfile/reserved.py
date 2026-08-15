"""Whether a 2DA row's label marks a reserved / placeholder entry.

2DA tables are padded with rows that are not real choices: the ``****`` null row,
BioWare's and CEP's held-back ids (``bio_reserved``, ``cep_reserved``), deleted
entries (``DELETED_*``), and padding (``padding``, ``CEP_Padding``). They should
not be *offered* as selectable values, though a value that happens to store one is
still resolved for display.

The match is deliberately narrow. A substring filter would be actively wrong —
real entries like *Mind Blank*, *Point Blank Shot*, *Remove Disease* and *Empty
Body* contain reserved-sounding words — so this keys only on the exact markers the
tables actually use.
"""

from __future__ import annotations


def is_reserved_label(label: str | None) -> bool:
    """True when a 2DA label marks a reserved, deleted, padding or empty row.

    Separator-agnostic: a display label has often had ``_`` turned into a space
    (``bio_reserved`` -> ``bio reserved``), so both forms must match.
    """
    s = (label or "").strip().lower().replace(" ", "_")
    return (
        s in ("", "****")
        or s.startswith(("deleted", "reserved"))
        or s.endswith(("_reserved", "_padding"))
        or s == "padding"
    )
