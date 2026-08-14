"""Feat/skill reference data for character display (VB ``BicFileInfo`` GetNames/GetDescriptions).

A character's ``.bic`` stores its feats as a list of feat *ids* and its skills as a
list of ranks (see :mod:`nwnfile.formats.bic_reader`). To show them by name we
need the game's lookup tables, which the original tool ships as four text files in its
program folder and which are bundled here (``game/data/``):

* **Feat Names.txt** — one ``Name*DescRef`` line per feat; the *line index* is the
  feat id (matches the BIC ``FeatList`` WORD), and ``DescRef`` keys the descriptions.
* **Feat Descriptions.txt** — ``]DescRef`` blocks → description by ref.
* **PRC Feats.json** — ``{"<feat id>": "name"}`` for community PRC (Player Resource
  Consortium) feats, whose ids run past the base table (see the merge note below).
* **PRC Feat Descriptions.json.gz** — ``{"<feat id>": "text"}`` (gzipped) — the PRC
  feat descriptions from the PRC8 manual, keyed by feat id.
* **Skill Names.txt** — one name per line (UTF-16); the line index is the skill id.
* **Skill Descriptions.txt** — ``]``-delimited blocks in skill-id order.
* **PRC Skills.json** / **PRC Skill Descriptions.json** — ``{"<skill id>": ...}`` for
  community PRC skills, whose ids run past the base ``Skill Names.txt`` table (same
  three-tier merge as feats).
* **PRC Classes.json** / **PRC Class Descriptions.json.gz** — ``{"<class id>": ...}``
  for community PRC classes, whose ids run past the base ``character.CLASS_NAMES``
  set (resolved by ``class_name``; descriptions feed the reference viewer).
* **PRC Races.json** — ``{"<race id>": "name"}`` for community PRC races, whose ids
  run past base ``character.RACE_NAMES`` (resolved by ``race_name``).
* **Spell Names.json** / **Spell Descriptions.json.gz** — ``{"<spell id>": ...}`` for
  every spell (base NWN + PRC; there is no base spell file, so this is the sole
  source). A ``.bic``'s spells come from each class's ``KnownList``/``MemorizedList``.

The base ``Feat Names.txt`` only covers base NWN (ids 0-1115). A PRC character's
``.bic`` stores feat ids in the thousands, which would fall off the end of that
table and vanish. :meth:`CharacterReference.feats` therefore resolves each feat id
in three tiers — the base line index first (base behaviour unchanged), then the
bundled PRC extension map, then ``Unknown feat <id>`` for ids in neither source so
genuine gaps stay visible (mirroring :meth:`CharacterReference.skills`). The PRC
table is scraped from the PRC8 online manual by ``docs/prc_feats/build_prc_feats.py``.

Faithful to ``BicFileInfo.GetNames`` / ``GetDescriptions`` / ``GetFeats`` / ``GetSkills``:
feats are looked up by feat-id → line, de-duplicated by name and name-sorted; skills
are listed in id order with unnamed extras shown as ``Unknown N``.

Divergence (noted): the VB List-based ``GetDescriptions`` inserts a leading empty entry,
so its skill descriptions are shifted by one (each skill shows the *previous* skill's
text, Animal Empathy shows blank). That is a bug, not a feature — this port indexes
skill descriptions correctly (block *i* is skill *i*'s description).
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path

from nwnfile.win_sort import win_compare

_DATA_DIR = Path(__file__).resolve().parent / "data"

FEAT_NAMES_FILE = "Feat Names.txt"
FEAT_DESCRIPTIONS_FILE = "Feat Descriptions.txt"
PRC_FEAT_NAMES_FILE = "PRC Feats.json"
PRC_FEAT_DESCRIPTIONS_FILE = "PRC Feat Descriptions.json.gz"
SKILL_NAMES_FILE = "Skill Names.txt"
SKILL_DESCRIPTIONS_FILE = "Skill Descriptions.txt"
PRC_SKILL_NAMES_FILE = "PRC Skills.json"
PRC_SKILL_DESCRIPTIONS_FILE = "PRC Skill Descriptions.json"
CLASS_DESCRIPTIONS_FILE = "Class Descriptions.txt"
PRC_CLASS_NAMES_FILE = "PRC Classes.json"
PRC_CLASS_DESCRIPTIONS_FILE = "PRC Class Descriptions.json.gz"
PRC_RACE_NAMES_FILE = "PRC Races.json"
SPELL_NAMES_FILE = "Spell Names.json"
SPELL_DESCRIPTIONS_FILE = "Spell Descriptions.json.gz"

_FEAT_DESC_UNAVAILABLE = "Feat description is not available."
_SKILL_DESC_UNAVAILABLE = "Skill description is not available."
_SPELL_DESC_UNAVAILABLE = "Spell description is not available."
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


def _coerce_int_keys(raw: dict) -> dict[int, str]:
    """``{"<id>": value}`` -> ``{id: value}``, skipping non-integer keys."""
    result: dict[int, str] = {}
    for key, value in raw.items():
        try:
            result[int(key)] = value
        except (TypeError, ValueError):
            continue
    return result


def _load_id_name_json(path: Path) -> dict[int, str]:
    """Parse a ``{"<id>": "name"}`` JSON map into ``{id: name}`` (non-int keys skipped)."""
    return _coerce_int_keys(json.loads(path.read_text(encoding="utf-8")))


def _load_id_name_json_gz(path: Path) -> dict[int, str]:
    """Parse a gzipped ``{"<id>": "text"}`` JSON map into ``{id: text}``."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return _coerce_int_keys(json.load(fh))


def load_prc_feat_names(path: Path) -> dict[int, str]:
    """Parse ``PRC Feats.json`` (``{"<feat id>": "name"}``) into ``{id: name}``.

    The bundled PRC (Player Resource Consortium) extension table — feat ids past
    the base ``Feat Names.txt`` range, scraped from the PRC8 manual (see
    ``docs/prc_feats/build_prc_feats.py``).
    """
    return _load_id_name_json(path)


def load_prc_feat_descriptions(path: Path) -> dict[int, str]:
    """Parse ``PRC Feat Descriptions.json.gz`` (``{"<feat id>": "text"}``) → ``{id: text}``.

    Gzip-compressed JSON (the uncompressed text is ~8.6 MB), keyed by feat id —
    the PRC feat descriptions pulled from the PRC8 manual pages (see
    ``docs/prc_feats/build_prc_feat_descriptions.py``).
    """
    return _load_id_name_json_gz(path)


def load_spell_names(path: Path) -> dict[int, str]:
    """Parse ``Spell Names.json`` (``{"<spell id>": "name"}``) into ``{id: name}``.

    The bundled spell name table — base NWN *and* PRC spells (there is no base
    spell file to preserve; the manual is the sole source). See
    ``docs/prc_feats/build_spells.py``.
    """
    return _load_id_name_json(path)


def load_spell_descriptions(path: Path) -> dict[int, str]:
    """Parse ``Spell Descriptions.json.gz`` (gzipped ``{"<spell id>": "text"}``)."""
    return _load_id_name_json_gz(path)


def load_prc_skill_names(path: Path) -> dict[int, str]:
    """Parse ``PRC Skills.json`` (``{"<skill id>": "name"}``) into ``{id: name}``.

    The bundled PRC skill extension table — skill ids past the base ``Skill
    Names.txt`` range, from the PRC8 manual (see
    ``docs/prc_feats/build_prc_skills.py``).
    """
    return _load_id_name_json(path)


def load_prc_skill_descriptions(path: Path) -> dict[int, str]:
    """Parse ``PRC Skill Descriptions.json`` (``{"<skill id>": "text"}``) into ``{id: text}``.

    PRC skill descriptions from the manual skill pages, keyed by skill id.
    """
    return _load_id_name_json(path)


def load_prc_class_names(path: Path) -> dict[int, str]:
    """Parse ``PRC Classes.json`` (``{"<class id>": "name"}``) into ``{id: name}``.

    The bundled PRC class extension table — class ids past the base
    ``character.CLASS_NAMES`` set, from the PRC8 manual (see
    ``docs/prc_feats/build_prc_classes.py``).
    """
    return _load_id_name_json(path)


def load_prc_class_descriptions(path: Path) -> dict[int, str]:
    """Parse ``PRC Class Descriptions.json.gz`` (gzipped ``{"<class id>": "text"}``).

    PRC class descriptions from the manual class pages, keyed by class id (used by
    :meth:`CharacterReference.all_classes` for the reference viewer).
    """
    return _load_id_name_json_gz(path)


def load_prc_race_names(path: Path) -> dict[int, str]:
    """Parse ``PRC Races.json`` (``{"<race id>": "name"}``) into ``{id: name}``.

    The bundled PRC race extension — racialtypes.2da ids past the base
    ``character.RACE_NAMES`` set, from the PRC8 manual (see
    ``docs/prc_feats/build_prc_races.py``).
    """
    return _load_id_name_json(path)


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
    prc_feat_names: dict[int, str] = field(default_factory=dict)
    prc_feat_descriptions: dict[int, str] = field(default_factory=dict)
    skill_names: list[str] = field(default_factory=list)
    skill_descriptions: list[str] = field(default_factory=list)
    prc_skill_names: dict[int, str] = field(default_factory=dict)
    prc_skill_descriptions: dict[int, str] = field(default_factory=dict)
    class_descriptions: dict[int, str] = field(default_factory=dict)
    prc_class_names: dict[int, str] = field(default_factory=dict)
    prc_class_descriptions: dict[int, str] = field(default_factory=dict)
    prc_race_names: dict[int, str] = field(default_factory=dict)
    spell_names: dict[int, str] = field(default_factory=dict)
    spell_descriptions: dict[int, str] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        """True once the reference tables loaded (more than the error placeholder)."""
        return len(self.feat_names) > 1 and len(self.skill_names) > 1

    # -- Reference lists (VB ClassesSkillsAndFeats) ------------------------ #
    def all_classes(self) -> list[tuple[str, str]]:
        """Every selectable class + description, name-sorted (VB LvClasses).

        Ports ``ClassesSkillsAndFeats.SkillsAndFeats_Load``: excludes creature/NPC
        classes (refs 8154/8155), maps each base class to its description via its
        string-ref (``character.CLASS_REFS``), then appends the bundled PRC classes
        (description from the PRC manual). De-duplicated by name (base wins) and
        sorted by name (``WinCompare``). Returns ``[(name, description)]``.
        """
        from nwnfile.character import CLASS_NAMES, CLASS_REFS

        excluded = (8154, 8155)
        rows: list[tuple[str, str]] = []
        seen: set[str] = set()
        for class_id, name in CLASS_NAMES.items():
            ref = CLASS_REFS.get(class_id)
            if ref in excluded:
                continue
            desc = self.class_descriptions.get(ref, _DESC_UNAVAILABLE) if ref else _DESC_UNAVAILABLE
            seen.add(name)
            rows.append((name, desc))
        for class_id, name in self.prc_class_names.items():
            if name in seen:
                continue
            seen.add(name)
            desc = self.prc_class_descriptions.get(class_id, _DESC_UNAVAILABLE)
            rows.append((name, desc))
        rows.sort(key=lambda pair: _SortKey(pair[0]))
        return rows

    def all_skills(self) -> list[tuple[str, str]]:
        """Every skill + description, name-sorted (VB LvSkills + PRC extension).

        Lists base NWN skills then the bundled PRC skills (de-duplicated by name,
        base wins). Returns ``[(name, description)]``.
        """
        rows: list[tuple[str, str]] = []
        seen: set[str] = set()
        for skill_id, name in enumerate(self.skill_names):
            if skill_id < len(self.skill_descriptions):
                desc = self.skill_descriptions[skill_id]
            else:
                desc = _SKILL_DESC_UNAVAILABLE
            seen.add(name)
            rows.append((name, desc))
        for skill_id, name in self.prc_skill_names.items():
            if name in seen:
                continue
            seen.add(name)
            desc = self.prc_skill_descriptions.get(skill_id, _SKILL_DESC_UNAVAILABLE)
            rows.append((name, desc))
        rows.sort(key=lambda pair: _SortKey(pair[0]))
        return rows

    def all_feats(self) -> list[tuple[str, str]]:
        """Every named feat + description (VB LvFeats / GetFeats + PRC extension).

        Lists base NWN feats then the bundled PRC feats, excludes ``Unknown``
        placeholders, de-duplicates by name (first/base wins) and sorts by name
        (``WinCompare``). Returns ``[(name, description)]``.
        """
        seen: set[str] = set()
        rows: list[tuple[str, str]] = []
        for name, ref in self.feat_names:
            if name == "Unknown" or name in seen:
                continue
            seen.add(name)
            rows.append((name, self.feat_descriptions.get(ref, _FEAT_DESC_UNAVAILABLE)))
        for feat_id, name in self.prc_feat_names.items():
            if name in seen:
                continue
            seen.add(name)
            rows.append((name, self.prc_feat_descriptions.get(feat_id, _FEAT_DESC_UNAVAILABLE)))
        rows.sort(key=lambda pair: _SortKey(pair[0]))
        return rows

    def feat_name(self, feat_id: int) -> str:
        """The name of a feat by id (base table, then PRC map, then ``Unknown``)."""
        return self._feat_name(feat_id)[0]

    def is_base_feat(self, feat_id: int) -> bool:
        """True for a base-game feat (whose id is in ``Feat Names.txt``).

        Base feats edited into ``FeatList`` persist; PRC feats (higher ids) are
        regenerated by PRC's scripts, so editing them may not stick.
        """
        return 0 <= feat_id < len(self.feat_names)

    def all_feat_ids(self) -> list[tuple[int, str]]:
        """Every known feat as ``(id, name)`` — base ids then PRC ids, for a picker."""
        pairs = [(i, name) for i, (name, _ref) in enumerate(self.feat_names)]
        pairs += sorted(self.prc_feat_names.items())
        return pairs

    def feats(self, feat_ids: list[int]) -> list[tuple[str, str]]:
        """Named feats for a character's feat ids (VB ``GetFeats``).

        Resolves each id in three tiers — the base ``Feat Names`` line (base NWN),
        then the bundled PRC extension map (community feats whose ids run past the
        base table), then ``Unknown feat <id>`` for ids in neither source — so PRC
        feats show by name and genuine gaps stay visible rather than being silently
        dropped (mirrors :meth:`skills`). De-duplicated by name (first wins) and
        name-sorted. Returns ``[(name, description)]``.
        """
        seen: set[str] = set()
        feats: list[tuple[str, str]] = []
        for feat_id in feat_ids:
            name, desc = self._feat_name(feat_id)
            if name in seen:
                continue
            seen.add(name)
            feats.append((name, desc))
        feats.sort(key=lambda pair: _SortKey(pair[0]))
        return feats

    def _feat_name(self, feat_id: int) -> tuple[str, str]:
        """Resolve a feat id to ``(name, description)`` — base, then PRC, then unknown."""
        if 0 <= feat_id < len(self.feat_names):
            name, ref = self.feat_names[feat_id]
            return name, self.feat_descriptions.get(ref, _FEAT_DESC_UNAVAILABLE)
        prc_name = self.prc_feat_names.get(feat_id)
        if prc_name is not None:
            desc = self.prc_feat_descriptions.get(feat_id, _FEAT_DESC_UNAVAILABLE)
            return prc_name, desc
        return f"Unknown feat {feat_id}", _FEAT_DESC_UNAVAILABLE

    def feat_description(self, feat_id: int) -> str:
        """A feat's description (base, then PRC), or a placeholder when unknown."""
        return self._feat_name(feat_id)[1]

    def spell_description(self, spell_id: int) -> str:
        """A spell's description, or empty when there is no bundled text for it."""
        rows = self.spells([spell_id])
        return rows[0][1] if rows else ""

    def skill_name(self, skill_id: int) -> str:
        """The name of a skill by its id (base table, then PRC map, then ``Skill N``)."""
        if 0 <= skill_id < len(self.skill_names):
            return self.skill_names[skill_id]
        return self.prc_skill_names.get(skill_id, f"Skill {skill_id}")

    def skills(self, skill_ranks: list[int]) -> list[tuple[str, int, str]]:
        """Named skills + ranks for a character (VB ``GetSkills`` + name-sort).

        Resolves each skill id by position — the base ``Skill Names`` line first,
        then the bundled PRC extension map (community skills whose ids run past the
        base table), then ``Unknown N`` for ids in neither source. Returns
        ``[(name, rank, description)]`` name-sorted.
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
            elif skill_id in self.prc_skill_names:
                name = self.prc_skill_names[skill_id]
                desc = self.prc_skill_descriptions.get(skill_id, _SKILL_DESC_UNAVAILABLE)
            else:
                unknown += 1
                name = f"Unknown {unknown}"
                desc = _SKILL_DESC_UNAVAILABLE
            rows.append((name, rank, desc))
        rows.sort(key=lambda row: _SortKey(row[0]))
        return rows

    def spell_name(self, spell_id: int) -> str:
        """The name of a spell by id (bundled base+PRC table), or ``Unknown spell N``."""
        return self.spell_names.get(spell_id, f"Unknown spell {spell_id}")

    def all_spell_ids(self) -> list[tuple[int, str]]:
        """Every known spell as ``(id, name)`` — for a picker."""
        return sorted(self.spell_names.items())

    def spells(
        self, spell_ids: list[int], spell_levels: dict[int, int] | None = None
    ) -> list[tuple[str, str, int | None]]:
        """Named spells for a character's spell ids (from the bundled spell tables).

        Maps each id (a spells.2da row = the ``.bic`` ``Spell`` WORD) to its name,
        description and spell level (from ``spell_levels``, ``None`` when unknown),
        de-duplicates by name (first wins) and sorts by name. Ids with no bundled
        name show as ``Unknown spell <id>``. Returns ``[(name, description, level)]``.
        """
        seen: set[str] = set()
        spells: list[tuple[str, str, int | None]] = []
        for spell_id in spell_ids:
            name = self.spell_names.get(spell_id, f"Unknown spell {spell_id}")
            if name in seen:
                continue
            seen.add(name)
            desc = self.spell_descriptions.get(spell_id, _SPELL_DESC_UNAVAILABLE)
            level = spell_levels.get(spell_id) if spell_levels else None
            spells.append((name, desc, level))
        spells.sort(key=lambda row: _SortKey(row[0]))
        return spells


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
    prc_feats = data_dir / PRC_FEAT_NAMES_FILE
    if prc_feats.is_file():
        ref.prc_feat_names = load_prc_feat_names(prc_feats)
    prc_feat_desc = data_dir / PRC_FEAT_DESCRIPTIONS_FILE
    if prc_feat_desc.is_file():
        ref.prc_feat_descriptions = load_prc_feat_descriptions(prc_feat_desc)
    if skill_names.is_file():
        ref.skill_names = load_skill_names(skill_names)
    if skill_desc.is_file():
        ref.skill_descriptions = load_skill_descriptions(skill_desc)
    prc_skills = data_dir / PRC_SKILL_NAMES_FILE
    if prc_skills.is_file():
        ref.prc_skill_names = load_prc_skill_names(prc_skills)
    prc_skill_desc = data_dir / PRC_SKILL_DESCRIPTIONS_FILE
    if prc_skill_desc.is_file():
        ref.prc_skill_descriptions = load_prc_skill_descriptions(prc_skill_desc)
    class_desc = data_dir / CLASS_DESCRIPTIONS_FILE
    if class_desc.is_file():
        ref.class_descriptions = load_class_descriptions(class_desc)
    prc_classes = data_dir / PRC_CLASS_NAMES_FILE
    if prc_classes.is_file():
        ref.prc_class_names = load_prc_class_names(prc_classes)
    prc_class_desc = data_dir / PRC_CLASS_DESCRIPTIONS_FILE
    if prc_class_desc.is_file():
        ref.prc_class_descriptions = load_prc_class_descriptions(prc_class_desc)
    prc_races = data_dir / PRC_RACE_NAMES_FILE
    if prc_races.is_file():
        ref.prc_race_names = load_prc_race_names(prc_races)
    spell_names = data_dir / SPELL_NAMES_FILE
    if spell_names.is_file():
        ref.spell_names = load_spell_names(spell_names)
    spell_desc = data_dir / SPELL_DESCRIPTIONS_FILE
    if spell_desc.is_file():
        ref.spell_descriptions = load_spell_descriptions(spell_desc)
    return ref
