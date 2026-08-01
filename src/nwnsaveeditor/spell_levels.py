"""Which spells a class can cast, and at what level.

A save's spellbook stores only ids, grouped into ``KnownList<n>`` /
``MemorizedList<n>`` fields where ``n`` is the spell level. Nothing in the save
says whether a given spell *belongs* at that level — so without this, adding a
spell to a level list happily stores a level-6 wizard spell in a bard's level-0
list, which the engine will not cast and which reads as data corruption.

``spells.2da`` carries one column per casting class holding that spell's level for
that class, or ``****`` when the class cannot cast it at all. That is the whole
answer, read straight from the game.
"""

from __future__ import annotations

#: Class id -> the ``spells.2da`` column naming that class's spell level.
#: Sorcerer and Wizard share one column, as the game does.
CLASS_COLUMNS: dict[int, str] = {
    1: "Bard",
    2: "Cleric",
    3: "Druid",
    6: "Paladin",
    7: "Ranger",
    9: "Wiz_Sorc",
    10: "Wiz_Sorc",
}


class SpellLevels:
    """``spells.2da`` read as "what can this class cast at this level?"."""

    def __init__(self, rows: dict[int, dict[str, str]] | None) -> None:
        self._rows = rows or {}

    @classmethod
    def for_install(cls, game_root, hak_dir=None) -> SpellLevels:
        """Read ``spells.2da``, preferring the PRC hak so its spells are covered."""
        from nwnfile.item_property_tables import ItemPropertyTables

        tables = ItemPropertyTables.for_install(game_root, hak_dir)
        return cls(tables._read("spells"))

    @property
    def available(self) -> bool:
        return bool(self._rows)

    def level_for(self, spell_id: int, class_id: int) -> int | None:
        """The spell's level for that class, or ``None`` if it cannot cast it."""
        column = CLASS_COLUMNS.get(class_id)
        if column is None:
            return None  # a PRC or non-casting class: not described by this table
        raw = (self._rows.get(spell_id) or {}).get(column, "****")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def spells_at(self, class_id: int, level: int) -> set[int]:
        """Every spell id the class casts at exactly ``level``."""
        column = CLASS_COLUMNS.get(class_id)
        if column is None:
            return set()
        found = set()
        for spell_id, row in self._rows.items():
            try:
                if int(row.get(column, "****")) == level:
                    found.add(spell_id)
            except (TypeError, ValueError):
                continue
        return found

    def describes(self, class_id: int) -> bool:
        """Whether this table can speak for the class at all.

        PRC prestige casters are not in ``spells.2da``'s columns, so their lists
        cannot be filtered and must not be silently emptied.
        """
        return CLASS_COLUMNS.get(class_id) is not None and self.available
