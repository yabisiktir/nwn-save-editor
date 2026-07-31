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
    ABILITY_LABELS,
    BicFileReader,
    CharacterInfo,
    Gender,
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

#: Class id -> name string-ref (VB ``BicFileInfo.ClassInfo`` Ref values). A class
#: whose ref equals ``NON_PC_CLASS_REF`` is a non-selectable creature class.
NON_PC_CLASS_REF = 8154
CLASS_REFS: dict[int, int] = {
    0: 240, 1: 241, 2: 242, 3: 243, 4: 244, 5: 245, 6: 246, 7: 247, 8: 248,
    9: 249, 10: 250, 11: 8154, 12: 8154, 13: 8154, 14: 8154, 15: 8154, 16: 8154,
    17: 8154, 18: 8154, 19: 8154, 20: 8155, 21: 8154, 22: 8154, 23: 8154,
    24: 8154, 25: 8154, 26: 8154, 27: 2947, 28: 2959, 29: 9006, 30: 9010,
    31: 9014, 32: 9018, 33: 9022, 34: 9025, 35: 9029, 36: 76422, 37: 83492,
    38: 8154, 41: 111713,
}

#: Gender id -> display name (VB ``Gender`` list order: Male/Female/Both/None).
GENDER_NAMES: dict[int, str] = {0: "Male", 1: "Female", 2: "Both"}


def pc_class_names() -> list[str]:
    """Player-selectable class names, sorted (VB ``CharacterFilter`` class list).

    VB fills the class filter from ``ClassInfo.Values Where info.Ref <> NonPc`` —
    every class whose name string-ref isn't the shared non-PC placeholder (8154).
    Commoner (ref 8155) is therefore included, faithfully to the VB.
    """
    names = [
        CLASS_NAMES[cid]
        for cid, ref in CLASS_REFS.items()
        if ref != NON_PC_CLASS_REF and cid in CLASS_NAMES
    ]
    return sorted(names)

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


def race_name(race_id: int, reference=None) -> str:
    """Display name for a race id — base ``RACE_NAMES`` first, then the bundled PRC
    race extension, then ``Race <id>`` (so PRC custom races like Bralani Eladrin
    show by name instead of falling back to Human).
    """
    if race_id in RACE_NAMES:
        return RACE_NAMES[race_id]
    from vaultkeeper.game.character_reference import default_reference

    ref = reference if reference is not None else default_reference()
    return ref.prc_race_names.get(race_id, f"Race {race_id}")


def is_base_race(race_id: int) -> bool:
    """Whether this is a stock race rather than one PRC added.

    PRC builds its races out of scripts and the creature skin, so changing a
    character *to* or *from* one is not the simple byte swap it looks like.
    """
    return race_id in RACE_NAMES


def race_options(reference=None) -> dict[int, str]:
    """Every race id the app can name, for a picker — base first, then PRC's."""
    from vaultkeeper.game.character_reference import default_reference

    ref = reference if reference is not None else default_reference()
    options = dict(RACE_NAMES)
    for race_id, name in ref.prc_race_names.items():
        options.setdefault(race_id, name)
    return dict(sorted(options.items()))


def class_name(class_id: int, reference=None) -> str:
    """Display name for a class id — base ``CLASS_NAMES`` first, then the bundled
    PRC class extension, then ``Class <id>`` (mirrors the feat/skill three-tier
    resolve so community/PRC prestige classes show by name instead of vanishing).
    """
    if class_id in CLASS_NAMES:
        return CLASS_NAMES[class_id]
    from vaultkeeper.game.character_reference import default_reference

    ref = reference if reference is not None else default_reference()
    return ref.prc_class_names.get(class_id, f"Class {class_id}")


def is_base_class(class_id: int) -> bool:
    """True for a base-game class. PRC prestige classes route spellcasting through
    PRC's own scripted spellbook, so editing their KnownList/MemorizedList may not
    persist — warn for those.
    """
    return class_id in CLASS_NAMES


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
    parts = [f"{class_name(cid)} {max(level, 1)}" for cid, level in info.classes]
    return f"Level {info.level} ({', '.join(parts)})"


def character_summary(
    info: CharacterInfo,
    *,
    updated: datetime | None = None,
    default_value: str = "",
    show_stats: bool = False,
) -> str:
    """Multi-line character summary text (VB ``BicFileInfo.CharacterSummary``).

    Layout (fields bic_reader decodes)::

        FirstName LastName [the Title] (level)

        Gender Race [(Subrace)], Lawful-Chaotic (v), Good-Evil (v)
        Class1 (level)
        Class2 (level)

        Experience: n
        Next Level Countdown: n

        Hit Points: [current /] max
        Gold / Deity
        [show_stats: abilities, Age, Armor Class, BAB, Saving Throws]
        Portrait: resref
        Updated: dd MMM yyyy HH:MM
        [show_stats: Biography]

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

    # Gender Race [(Subrace)], Lawful-Chaotic (v), Good-Evil (v)
    lc = info.alignment_lawful_chaotic
    ge = info.alignment_good_evil
    subrace = f" ({info.subrace})" if info.subrace else ""
    lines.append(
        f"{gender_name(info.gender)} {race_name(info.race_id)}{subrace}, "
        f"{_lawful_chaotic_word(lc)} ({lc}), {_good_evil_word(ge)} ({ge})"
    )

    # Class n (level) lines.
    for cid, level in info.classes:
        lines.append(f"{class_name(cid)} ({max(level, 1)})")

    # Experience + next-level countdown.
    lines.append("")
    lines.append(f"Experience: {info.experience:,}")
    if info.level < 40:
        threshold = BicFileReader.LEVEL_XP[info.level]  # XP to reach the next level
        countdown = max(threshold - info.experience, 0)
        # VB ToNoneIfZero: "None" when zero, otherwise the thousands-formatted number.
        text = f"{countdown:,}" if countdown else "None"
        lines.append(f"Next Level Countdown: {text}")

    # Hit points, gold, deity (VB order), optional ability-score + combat block.
    lines.append("")
    if info.current_hit_points and info.current_hit_points != info.hit_points:
        lines.append(f"Hit Points: {info.current_hit_points:,} / {info.hit_points:,}")
    else:
        lines.append(f"Hit Points: {info.hit_points:,}")
    lines.append(f"Gold: {info.gold:,}" if info.gold else "Gold: None")
    if info.deity:
        lines.append(f"Deity: {info.deity}")
    if show_stats and info.abilities:
        lines.append("")
        for stat in ABILITY_LABELS:
            lines.append(f"{stat}: {info.abilities.get(stat, 0)}")
    if show_stats:
        lines.append("")
        if info.age:
            lines.append(f"Age: {info.age}")
        lines.append(f"Armor Class: {info.armor_class}")
        lines.append(f"Base Attack Bonus: +{info.base_attack_bonus}")
        lines.append(
            f"Saving Throws — Fortitude: {info.save_fortitude}, "
            f"Reflex: {info.save_reflex}, Will: {info.save_will}"
        )

    lines.append("")
    lines.append(f"Portrait: {info.portrait_resref}")
    if updated is not None:
        lines.append(f"Updated: {updated:%d %b %Y %H:%M}")

    # Biography last, and only in the detailed view (kept out of the plain summary
    # so its freeform text can't accidentally match the class filter).
    if show_stats and info.biography.strip():
        lines.append("")
        lines.append("Biography:")
        lines.append(info.biography.strip())

    return "\n".join(lines)


#: Portrait size suffix letters, smallest → largest (NWN po_*<size>.tga).
PORTRAIT_SIZES = ("t", "s", "m", "l", "h")


def portrait_filename(resref: str, size_char: str = "m") -> str:
    """The portrait TGA filename for a resref + size (VB ``{Portrait}{size}.tga``)."""
    return f"{resref}{size_char}.tga"


def resolve_portrait(
    resref: str, search_dirs: list[Path], size_char: str = "m"
) -> Path | None:
    """Find a character's portrait TGA across the NWN search folders.

    VB (``CharacterSummary``) looks for ``{resref}{size}.tga`` in override / hak
    portrait / portraits folders in priority order. We do the same, then (only as
    a graceful fallback, never showing a wrong portrait) try the other sizes so a
    portrait still displays when the configured size isn't on disk.
    """
    if not resref:
        return None
    name = portrait_filename(resref, size_char)
    for folder in search_dirs:
        candidate = Path(folder) / name
        if candidate.is_file():
            return candidate
    for size in PORTRAIT_SIZES:
        if size == size_char:
            continue
        for folder in search_dirs:
            candidate = Path(folder) / portrait_filename(resref, size)
            if candidate.is_file():
                return candidate
    return None


@dataclass
class PortraitEntry:
    """An installed portrait: its base resref and the size variants on disk."""

    resref: str  # base resref without the trailing size letter
    sizes: dict[str, Path]  # size_char -> file

    def path(self, size_char: str) -> Path | None:
        """The file for ``size_char``, falling back to the largest available."""
        if size_char in self.sizes:
            return self.sizes[size_char]
        for size in reversed(PORTRAIT_SIZES):  # largest first
            if size in self.sizes:
                return self.sizes[size]
        return None


def scan_portraits(folders: list[Path]) -> list[PortraitEntry]:
    """List installed portraits across ``folders``, grouped by base resref.

    Portrait TGAs come in a size set (``<base>t/s/m/l/h.tga``); VB's Portrait
    Manager keys off the huge (``h``) files. We group every ``*<size>.tga`` by its
    base resref so each portrait appears once with all its available sizes. Later
    folders don't override earlier ones (search-order priority). Sorted by resref.
    """
    by_resref: dict[str, dict[str, Path]] = {}
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if not path.is_file() or path.suffix.lower() != ".tga":
                continue
            stem = path.stem
            if not stem or stem[-1].lower() not in PORTRAIT_SIZES:
                continue
            base = stem[:-1]
            size = stem[-1].lower()
            sizes = by_resref.setdefault(base, {})
            sizes.setdefault(size, path)  # first folder wins
    return [
        PortraitEntry(resref=base, sizes=sizes)
        for base, sizes in sorted(by_resref.items(), key=lambda kv: kv[0].lower())
    ]


#: NWN TGA resource-type code (see ``core/formats/erf_reader.RES_TYPE_EXTENSIONS``).
_TGA_RES_TYPE = 3


def extract_hak_portraits(hak_path: Path, dest_dir: Path, *, erf_reader) -> int:
    """Extract complete portrait sets from a hak (VB ``ExtractHakPortraits``).

    Extracts the hak's TGA resources into ``dest_dir``, then keeps only those that
    form a *complete* five-size portrait set (``<base>t/s/m/l/h.tga``). When a set
    is missing only the huge ``h`` file it is created by copying the large ``l``
    file (VB's ``missingH`` fixup); every other extracted TGA — non-portrait images
    and incomplete sets — is deleted. Returns the number of complete portraits.
    """
    import shutil

    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted = erf_reader.extract_all(hak_path, dest_dir, res_type=_TGA_RES_TYPE)

    by_base: dict[str, dict[str, Path]] = {}
    discard: list[Path] = []
    for path in extracted:
        stem = path.stem
        if stem and stem[-1].lower() in PORTRAIT_SIZES:
            by_base.setdefault(stem[:-1], {})[stem[-1].lower()] = path
        else:
            discard.append(path)

    # Only the huge (h) file missing → create it from the large (l) file.
    for base, sizes in by_base.items():
        if "h" not in sizes and "l" in sizes and len(sizes) == 4:
            huge = dest_dir / f"{base}h.tga"
            shutil.copy2(sizes["l"], huge)
            sizes["h"] = huge

    complete = 0
    for sizes in by_base.values():
        if set(PORTRAIT_SIZES) <= set(sizes):
            complete += 1
        else:
            discard.extend(sizes.values())  # incomplete set is not a portrait

    for path in discard:
        path.unlink(missing_ok=True)
    return complete


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

    def summary(self, *, show_stats: bool = False) -> str:
        return character_summary(
            self.info,
            updated=self.updated,
            default_value=self.path.name,
            show_stats=show_stats,
        )

    def feats(self, reference=None) -> list[tuple[str, str]]:
        """This character's named feats + descriptions (VB ``GetFeats``)."""
        return character_feats(self.info, reference)

    def skills(self, reference=None) -> list[tuple[str, int, str]]:
        """This character's named skills, ranks + descriptions (VB ``GetSkills``)."""
        return character_skills(self.info, reference)

    def spells(self, reference=None) -> list[tuple[str, str, int | None]]:
        """This character's named spells + descriptions + spell level."""
        return character_spells(self.info, reference)


def character_feats(info: CharacterInfo, reference=None) -> list[tuple[str, str]]:
    """Named, de-duplicated, name-sorted feats for a character (VB ``GetFeats``)."""
    from vaultkeeper.game.character_reference import default_reference

    ref = reference if reference is not None else default_reference()
    return ref.feats(info.feat_ids)


def character_skills(info: CharacterInfo, reference=None) -> list[tuple[str, int, str]]:
    """Named skills with ranks + descriptions for a character (VB ``GetSkills``)."""
    from vaultkeeper.game.character_reference import default_reference

    ref = reference if reference is not None else default_reference()
    return ref.skills(info.skill_ranks)


def character_spells(info: CharacterInfo, reference=None) -> list[tuple[str, str, int | None]]:
    """Named, name-sorted spells (name, description, spell level) for a character."""
    from vaultkeeper.game.character_reference import default_reference

    ref = reference if reference is not None else default_reference()
    return ref.spells(info.spell_ids, info.spell_levels)


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
