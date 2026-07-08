"""Character (.bic) summary + discovery, ported from VB ``BicFileInfo``.

The heavy lifting — decoding the BIC's GFF struct — is done by
:mod:`vaultkeeper.core.formats.bic_reader`. This module adds the *presentation*
layer VB's ``BicFileInfo.CharacterSummary`` provides: faithful race/class display
names, the alignment title, and the multi-line summary text shown in the
Character Viewer and behind the status-bar character button.

Grounded against ``NWN Installer Tool/BicFileInfo.vb`` (Race/ClassInfo/
AlignmentTitle tables, TitleIndex = GoodEvil*100 + LawfulChaotic, and the
summary layout in ``CharacterSummary``).

Deferred (not yet decoded by bic_reader, so omitted from the summary rather than
guessed): Gold, Deity, ability stats, skills, feats. Adding them is a pure
extension of the reader + these format helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vaultkeeper.core.formats.bic_reader import (
    BicFileReader,
    CharacterClass,
    CharacterInfo,
    Gender,
    Race,
)

#: Race id -> display name (VB ``BicFileInfo.Race``).
RACE_NAMES: dict[int, str] = {
    0: "Dwarf", 1: "Elf", 2: "Gnome", 3: "Halfling", 4: "Half-Elf",
    5: "Half-Orc", 6: "Human", 7: "Aberration", 8: "Animal", 9: "Beast",
    10: "Construct", 11: "Dragon", 12: "Goblinoid", 13: "Monstrous", 14: "Orc",
    15: "Reptilian", 16: "Elemental", 17: "Fey", 18: "Giant",
    19: "Magical Beast", 20: "Outsider", 23: "Shapechanger", 24: "Undead",
    25: "Vermin", 29: "Ooze",
}

#: Class id -> display name (VB ``BicFileInfo.ClassInfo``).
CLASS_NAMES: dict[int, str] = {
    0: "Barbarian", 1: "Bard", 2: "Cleric", 3: "Druid", 4: "Fighter",
    5: "Monk", 6: "Paladin", 7: "Ranger", 8: "Rogue", 9: "Sorcerer",
    10: "Wizard", 11: "Aberration", 12: "Animal", 13: "Construct",
    14: "Humanoid", 15: "Monstrous", 16: "Elemental", 17: "Fey", 18: "Dragon",
    19: "Undead", 20: "Commoner", 21: "Beast", 22: "Giant", 23: "Magical Beast",
    24: "Outsider", 25: "Shapechanger", 26: "Vermin", 27: "Shadowdancer",
    28: "Harper Scout", 29: "Arcane Archer", 30: "Assassin", 31: "Blackguard",
    32: "Champion of Torm", 33: "Weapon Master", 34: "Pale Master",
    35: "Shifter", 36: "Dwarven Defender", 37: "Red Dragon Disciple",
    38: "Ooze", 41: "Purple Dragon Knight",
}

#: Gender id -> display name (VB ``Gender`` list order: Male/Female/Both/None).
GENDER_NAMES: dict[int, str] = {0: "Male", 1: "Female", 2: "Both"}

#: (LawfulChaotic, GoodEvil) corner/mid combos -> alignment title
#: (VB ``AlignmentTitle`` keyed by TitleIndex = GoodEvil*100 + LawfulChaotic).
ALIGNMENT_TITLES: dict[int, str] = {
    100 * 100 + 100: "Crusader",
    100 * 100 + 50: "Benefactor",
    100 * 100 + 0: "Rebel",
    50 * 100 + 100: "Judge",
    50 * 100 + 50: "Reconciler",
    50 * 100 + 0: "Free Spirit",
    0 * 100 + 100: "Dominator",
    0 * 100 + 50: "Malefactor",
    0 * 100 + 0: "Destroyer",
}


def _title_index(lawful_chaotic: int, good_evil: int) -> int:
    """VB ``TitleIndex`` — GoodEvil*100 + LawfulChaotic."""
    return good_evil * 100 + lawful_chaotic


def race_name(race: Race) -> str:
    return RACE_NAMES.get(race.value, f"Race {race.value}")


def class_name(cls: CharacterClass) -> str:
    return CLASS_NAMES.get(cls.value, f"Class {cls.value}")


def gender_name(gender: Gender) -> str:
    return GENDER_NAMES.get(gender.value, "")


def alignment_title(lawful_chaotic: int, good_evil: int) -> str:
    """The alignment title (e.g. "Crusader"), or "" for non-corner alignments."""
    return ALIGNMENT_TITLES.get(_title_index(lawful_chaotic, good_evil), "")


def _lawful_chaotic_word(value: int) -> str:
    if value < 31:
        return "Chaotic"
    if value < 70:
        return "Neutral"
    return "Lawful"


def _good_evil_word(value: int) -> str:
    if value < 31:
        return "Evil"
    if value < 70:
        return "Neutral"
    return "Good"


def level_summary(info: CharacterInfo) -> str:
    """One-line ``Level N (Class1 a, Class2 b)`` summary (VB ``LevelSummary``)."""
    parts = [f"{class_name(cls)} {max(level, 1)}" for cls, level in info.classes]
    return f"Level {info.level} ({', '.join(parts)})"


def character_summary(
    info: CharacterInfo,
    *,
    updated: datetime | None = None,
    default_value: str = "",
) -> str:
    """Multi-line character summary text (VB ``BicFileInfo.CharacterSummary``).

    Layout (fields bic_reader decodes)::

        FirstName LastName [the Title] (level)

        Gender Race, Lawful-Chaotic (v), Good-Evil (v)
        Class1 (level)
        Class2 (level)

        Experience: n
        Next Level Countdown: n

        Hit Points: n
        Portrait: resref
        Updated: dd MMM yyyy HH:MM

    On an unreadable file, returns ``default_value`` followed by the error.
    """
    if not info.is_valid:
        tail = f"\n\n{info.error_message}" if info.error_message else ""
        return f"{default_value}{tail}"

    lines: list[str] = []

    # FirstName LastName [the Title] (level)
    header = info.name.strip()
    title = alignment_title(info.alignment_lawful_chaotic, info.alignment_good_evil)
    if title:
        header += f" the {title}"
    header += f" ({info.level})"
    lines.append(header)
    lines.append("")

    # Gender Race, Lawful-Chaotic (v), Good-Evil (v)
    lc = info.alignment_lawful_chaotic
    ge = info.alignment_good_evil
    lines.append(
        f"{gender_name(info.gender)} {race_name(info.race)}, "
        f"{_lawful_chaotic_word(lc)} ({lc}), {_good_evil_word(ge)} ({ge})"
    )

    # Class n (level) lines.
    for cls, level in info.classes:
        lines.append(f"{class_name(cls)} ({max(level, 1)})")

    # Experience + next-level countdown.
    lines.append("")
    lines.append(f"Experience: {info.experience:,}")
    if info.level < 40:
        threshold = BicFileReader.LEVEL_XP[info.level]  # XP to reach the next level
        countdown = max(threshold - info.experience, 0)
        # VB ToNoneIfZero: "None" when zero, otherwise the thousands-formatted number.
        text = f"{countdown:,}" if countdown else "None"
        lines.append(f"Next Level Countdown: {text}")

    # Hit points + portrait.
    lines.append("")
    lines.append(f"Hit Points: {info.hit_points:,}")
    lines.append(f"Portrait: {info.portrait_resref}")
    if updated is not None:
        lines.append(f"Updated: {updated:%d %b %Y %H:%M}")

    return "\n".join(lines)


@dataclass
class CharacterFile:
    """A discovered character file plus its decoded info (info may be invalid)."""

    path: Path
    info: CharacterInfo

    @property
    def display_name(self) -> str:
        """The character's name, falling back to the file stem."""
        if self.info.is_valid and self.info.name.strip():
            return self.info.name.strip()
        return self.path.stem

    @property
    def updated(self) -> datetime | None:
        try:
            return datetime.fromtimestamp(self.path.stat().st_mtime)
        except OSError:
            return None

    def summary(self) -> str:
        return character_summary(
            self.info, updated=self.updated, default_value=self.path.name
        )


def scan_character_files(folder: Path) -> list[CharacterFile]:
    """Decode every ``.bic`` in ``folder`` (non-recursive), sorted by name.

    Save folders hold a single ``player.bic``; the local vault holds many.
    """
    reader = BicFileReader()
    found: list[CharacterFile] = []
    if not folder.is_dir():
        return found
    for path in folder.iterdir():
        if path.is_file() and path.suffix.lower() == ".bic":
            info = reader.read_file(path)
            if info is not None:
                found.append(CharacterFile(path=path, info=info))
    found.sort(key=lambda cf: cf.display_name.lower())
    return found
