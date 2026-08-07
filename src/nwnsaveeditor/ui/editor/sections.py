"""The editor's sidebar sections, and which staged edits belong to each.

Kept apart from the shell so a screen module can name its own section without
importing the window, and so the change-kind mapping — the thing that lights a
section's gold dirty dot — is stated in one place.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Section:
    """One sidebar entry: its key, label, 2-letter chip code and grouping."""

    key: str
    label: str
    code: str
    advanced: bool = False


#: Sidebar order as designed — Area Contents sits after Party & Campaign, and
#: the advanced screens are grouped under their own ``ADVANCED`` cap label.
SECTIONS: tuple[Section, ...] = (
    Section("character", "Character", "CH"),
    Section("inventory", "Inventory & Equipment", "IN"),
    Section("spellbook", "Spellbook", "SP"),
    Section("quests", "Quests & World State", "QW"),
    Section("party", "Party & Campaign", "PC"),
    Section("area", "Area Contents", "AR"),
    Section("raw", "Raw Data (GFF)", "RD", advanced=True),
    Section("backups", "Backups & Diff", "BK", advanced=True),
)

#: What each screen holds. Shown as the empty state until that screen is built,
#: so an unfinished section still tells the user what will live there.
SECTION_BLURBS: dict[str, str] = {
    "character": "The core character record — abilities, alignment, skills, feats and looks.",
    "inventory": "Equipped slots, the carried bag, and each item's magical properties.",
    "spellbook": "Known & memorized spells per caster class and level, with PRC "
                 "prestige spellbooks flagged.",
    "quests": "Journal entries and per-module local/global boolean, number and string variables.",
    "party": "Party-wide gold/XP and campaign-persistent global variables.",
    "area": "Browse an area's stores, creatures and containers — edit store pricing, "
            "add, remove and duplicate the items in the world, and change their "
            "magical properties.",
    "raw": "Advanced: browse and edit the underlying GFF struct/field tree directly, "
           "with the item-property reference foldable alongside it.",
    "backups": "Restore a previous auto-backup, or diff two saves field-by-field.",
}

#: :attr:`PendingChange.kind` -> the section whose dirty dot it lights.
_KIND_SECTIONS: dict[str, str] = {
    "char-field": "character",
    "skill": "character",
    "feat": "character",
    "spell": "spellbook",
    "property": "inventory",
    "prop-add": "inventory",
    "prop-remove": "inventory",
    "add-item": "inventory",
    "store": "area",
    "area-item": "area",
    "raw": "raw",
    "variable": "quests",
    "module-field": "party",
}


def section_for_kind(kind: str) -> str | None:
    """Which section a staged change belongs to, or ``None`` if it maps nowhere."""
    return _KIND_SECTIONS.get(kind)


def by_key(key: str) -> Section | None:
    """Look a section up by key."""
    return next((s for s in SECTIONS if s.key == key), None)
