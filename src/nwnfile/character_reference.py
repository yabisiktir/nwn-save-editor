"""Feat/skill reference data for character display (VB ``BicFileInfo`` GetNames/GetDescriptions).

A character's ``.bic`` stores its feats as a list of feat *ids* and its skills as a
list of ranks (see :mod:`vaultkeeper.core.formats.bic_reader`). To show them by name we
need the game's lookup tables, which the original tool ships as four text files in its
program folder and which are bundled here (``game/data/``):

* **Feat Names.txt** — one ``Name*DescRef`` line per feat; the *line index* is the
  feat id (matches the BIC ``FeatList`` WORD), and ``DescRef`` keys the descriptions.
* **Feat Descriptions.txt** — ``]DescRef`` blocks → description by ref.
* **Skill Names.txt** — one name per line (UTF-16); the line index is the skill id.
* **Skill Descriptions.txt** — ``]``-delimited blocks in skill-id order.

Faithful to ``BicFileInfo.GetNames`` / ``GetDescriptions`` / ``GetFeats`` / ``GetSkills``:
feats are looked up by feat-id → line, de-duplicated by name and name-sorted; skills
are listed in id order with unnamed extras shown as ``Unknown N``.

Divergence (noted): the VB List-based ``GetDescriptions`` inserts a leading empty entry,
so its skill descriptions are shifted by one (each skill shows the *previous* skill's
text, Animal Empathy shows blank). That is a bug, not a feature — this port indexes
skill descriptions correctly (block *i* is skill *i*'s description).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from vaultkeeper.core.win_sort import win_compare

_DATA_DIR = Path(__file__).resolve().parent / "data"

FEAT_NAMES_FILE = "Feat Names.txt"
FEAT_DESCRIPTIONS_FILE = "Feat Descriptions.txt"
SKILL_NAMES_FILE = "Skill Names.txt"
SKILL_DESCRIPTIONS_FILE = "Skill Descriptions.txt"
CLASS_DESCRIPTIONS_FILE = "Class Descriptions.txt"

_FEAT_DESC_UNAVAILABLE = "Feat description is not available."
_SKILL_DESC_UNAVAILABLE = "Skill description is not available."
_DESC_UNAVAILABLE = "Description is unavailable."


def _read_text(path: Path) -> str:
    """Read a data file, honouring a UTF-16/UTF-8 BOM, else Latin-1 (VB ANSI)."""
    data = path.read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    if data[:3] == b"\xef\xbb\xbf":
        return data.decode("utf-8-sig")
    return data.decode("latin-1")


def _lines(text: str) -> list[str]:
    """Split into lines dropping the trailing newline's empty entry (VB ``String.ToList``)."""
    return text.splitlines()


def load_feat_names(path: Path) -> list[tuple[str, int]]:
    """Parse ``Feat Names.txt`` into ``[(name, desc_ref)]`` indexed by feat id.

    Each line is ``Name*DescRef``; the list index is the feat id. Malformed lines
    (missing ``*`` / non-numeric ref) are skipped rather than aborting the load.
    """
    result: list[tuple[str, int]] = []
    for line in _lines(_read_text(path)):
        name, sep, ref = line.partition("*")
        if not sep:
            continue
        try:
            result.append((name, int(ref)))
        except ValueError:
            continue
    return result


def load_feat_descriptions(path: Path) -> dict[int, str]:
    """Parse ``Feat Descriptions.txt`` (``]DescRef`` blocks) into ``{ref: description}``."""
    descriptions: dict[int, str] = {}
    key: int | None = None
    buf: list[str] = []
    for line in _lines(_read_text(path)):
        if line.startswith("]"):
            if key is not None:
                descriptions[key] = "\n".join(buf).strip()
            try:
                key = int(line[1:])
            except ValueError:
                key = None
            buf = []
        else:
            buf.append(line)
    if key is not None:
        descriptions[key] = "\n".join(buf).strip()
    return descriptions


def load_class_descriptions(path: Path) -> dict[int, str]:
    """Parse ``Class Descriptions.txt`` (``]ClassRef`` blocks) into ``{ref: description}``.

    Same ``]``-delimited block format as ``Feat Descriptions.txt`` (VB
    ``ClassesSkillsAndFeats.LoadClassDescriptions``), keyed by the class name
    string-ref (see ``character.CLASS_REFS``).
    """
    return load_feat_descriptions(path)


def load_skill_names(path: Path) -> list[str]:
    """Parse ``Skill Names.txt`` (one name per line); the list index is the skill id."""
    return _lines(_read_text(path))


def load_skill_descriptions(path: Path) -> list[str]:
    """Parse ``Skill Descriptions.txt`` (``]``-delimited blocks) in skill-id order.

    Block *i* is skill *i*'s description (the VB off-by-one is corrected — see the
    module docstring).
    """
    descriptions: list[str] = []
    buf: list[str] = []
    started = False
    for line in _lines(_read_text(path)):
        if line.startswith("]"):
            if started:
                descriptions.append("\n".join(buf).strip())
            started = True
            buf = [line[1:]]
        else:
            buf.append(line)
    if started:
        descriptions.append("\n".join(buf).strip())
    return descriptions


@dataclass
class CharacterReference:
    """Loaded feat/skill lookup tables (VB ``BicFileInfo`` name/description caches)."""

    feat_names: list[tuple[str, int]] = field(default_factory=list)
    feat_descriptions: dict[int, str] = field(default_factory=dict)
    skill_names: list[str] = field(default_factory=list)
    skill_descriptions: list[str] = field(default_factory=list)
    class_descriptions: dict[int, str] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        """True once the reference tables loaded (more than the error placeholder)."""
        return len(self.feat_names) > 1 and len(self.skill_names) > 1

    # -- Reference lists (VB ClassesSkillsAndFeats) ------------------------ #
    def all_classes(self) -> list[tuple[str, str]]:
        """Every selectable class + description, name-sorted (VB LvClasses).

        Ports ``ClassesSkillsAndFeats.SkillsAndFeats_Load``: excludes creature/NPC
        classes (refs 8154/8155), maps each class to its description via its
        string-ref (``character.CLASS_REFS``), and sorts by name (``WinCompare``).
        Returns ``[(name, description)]``.
        """
        from vaultkeeper.game.character import CLASS_NAMES, CLASS_REFS

        excluded = (8154, 8155)
        rows: list[tuple[str, str]] = []
        for class_id, name in CLASS_NAMES.items():
            ref = CLASS_REFS.get(class_id)
            if ref in excluded:
                continue
            desc = self.class_descriptions.get(ref, _DESC_UNAVAILABLE) if ref else _DESC_UNAVAILABLE
            rows.append((name, desc))
        rows.sort(key=lambda pair: _SortKey(pair[0]))
        return rows

    def all_skills(self) -> list[tuple[str, str]]:
        """Every skill + description, name-sorted (VB LvSkills). ``[(name, description)]``."""
        rows: list[tuple[str, str]] = []
        for skill_id, name in enumerate(self.skill_names):
            if skill_id < len(self.skill_descriptions):
                desc = self.skill_descriptions[skill_id]
            else:
                desc = _SKILL_DESC_UNAVAILABLE
            rows.append((name, desc))
        rows.sort(key=lambda pair: _SortKey(pair[0]))
        return rows

    def all_feats(self) -> list[tuple[str, str]]:
        """Every named feat + description (VB LvFeats / GetFeats).

        Excludes ``Unknown`` placeholder entries, de-duplicates by name (first wins)
        and sorts by name (``WinCompare``). Returns ``[(name, description)]``.
        """
        seen: set[str] = set()
        rows: list[tuple[str, str]] = []
        for name, ref in self.feat_names:
            if name == "Unknown" or name in seen:
                continue
            seen.add(name)
            rows.append((name, self.feat_descriptions.get(ref, _FEAT_DESC_UNAVAILABLE)))
        rows.sort(key=lambda pair: _SortKey(pair[0]))
        return rows

    def feats(self, feat_ids: list[int]) -> list[tuple[str, str]]:
        """Named feats for a character's feat ids (VB ``GetFeats``).

        Maps each id to its ``Feat Names`` line, de-duplicates by name (first wins)
        and sorts by name. Returns ``[(name, description)]``.
        """
        seen: set[str] = set()
        feats: list[tuple[str, str]] = []
        for feat_id in feat_ids:
            if 0 <= feat_id < len(self.feat_names):
                name, ref = self.feat_names[feat_id]
                if name in seen:
                    continue
                seen.add(name)
                desc = self.feat_descriptions.get(ref, _FEAT_DESC_UNAVAILABLE)
                feats.append((name, desc))
        feats.sort(key=lambda pair: _SortKey(pair[0]))
        return feats

    def skills(self, skill_ranks: list[int]) -> list[tuple[str, int, str]]:
        """Named skills + ranks for a character (VB ``GetSkills`` + name-sort).

        Skills without a name (ids beyond ``Skill Names``, e.g. EE-only skills) are
        shown as ``Unknown N``. Returns ``[(name, rank, description)]`` name-sorted.
        """
        unknown = 0
        rows: list[tuple[str, int, str]] = []
        for skill_id, rank in enumerate(skill_ranks):
            if skill_id < len(self.skill_names):
                name = self.skill_names[skill_id]
                if skill_id < len(self.skill_descriptions):
                    desc = self.skill_descriptions[skill_id]
                else:
                    desc = _SKILL_DESC_UNAVAILABLE
            else:
                unknown += 1
                name = f"Unknown {unknown}"
                desc = _SKILL_DESC_UNAVAILABLE
            rows.append((name, rank, desc))
        rows.sort(key=lambda row: _SortKey(row[0]))
        return rows


class _SortKey:
    """Adapter to sort strings with ``win_compare`` (StrCmpLogicalW natural order)."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value

    def __lt__(self, other: _SortKey) -> bool:
        return win_compare(self.value, other.value) < 0


_cached: CharacterReference | None = None


def default_reference() -> CharacterReference:
    """The bundled feat/skill reference tables (cached after first load)."""
    global _cached
    if _cached is None:
        _cached = load_reference(_DATA_DIR)
    return _cached


def load_reference(data_dir: Path) -> CharacterReference:
    """Load the four reference files from ``data_dir`` (missing files → empty tables)."""
    ref = CharacterReference()
    feat_names = data_dir / FEAT_NAMES_FILE
    feat_desc = data_dir / FEAT_DESCRIPTIONS_FILE
    skill_names = data_dir / SKILL_NAMES_FILE
    skill_desc = data_dir / SKILL_DESCRIPTIONS_FILE
    if feat_names.is_file():
        ref.feat_names = load_feat_names(feat_names)
    if feat_desc.is_file():
        ref.feat_descriptions = load_feat_descriptions(feat_desc)
    if skill_names.is_file():
        ref.skill_names = load_skill_names(skill_names)
    if skill_desc.is_file():
        ref.skill_descriptions = load_skill_descriptions(skill_desc)
    class_desc = data_dir / CLASS_DESCRIPTIONS_FILE
    if class_desc.is_file():
        ref.class_descriptions = load_class_descriptions(class_desc)
    return ref
