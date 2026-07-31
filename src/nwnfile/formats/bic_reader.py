"""
BIC file format reader for Neverwinter Nights character files.

Self-contained GFF (V3.2) struct decoder — it does NOT depend on the generic
salvaged ``gff_reader``. The offset arithmetic mirrors
:mod:`vaultkeeper.game.module_reader` (which faithfully decodes a module.ifo GFF)
and is grounded against the C# ground-truth parser at
``BicFileReader/BicFileReader/GffReader.cs`` + ``Info.cs``.

The BIC lives at the start of the file, so every section offset in the header is
absolute (base = 0). Extracted: FirstName/LastName (CExoLocString), Gender/Race/
alignment (BYTE), ClassList (List of {Class INT, ClassLevel SHORT} structs),
Experience (DWORD), MaxHitPoints (SHORT), the Portrait resref (CResRef), Gold
(DWORD), Deity (CExoString) and the six ability scores Str/Dex/Con/Int/Wis/Cha
(BYTE) — field names verified against the C# ``BicFileReader/Info.cs``.
"""

import struct
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from pathlib import Path

from vaultkeeper.core.log import get_logger

logger = get_logger(__name__)


#: Ability-score BYTE fields (VB/C# ``Info.cs`` ``Str``/``Dex``/…), display order.
ABILITY_LABELS = ("Str", "Dex", "Con", "Int", "Wis", "Cha")

#: Equipment slot bit (``Equip_ItemList`` struct's programmer id = ``2**slot``) ->
#: display name (NWN ``INVENTORY_SLOT_*``). Creature slots (skin/creature weapons)
#: hold PRC-granted bonuses so they are surfaced too.
EQUIP_SLOT_NAMES: dict[int, str] = {
    1: "Head", 2: "Chest", 4: "Boots", 8: "Arms", 16: "Right Hand",
    32: "Left Hand", 64: "Cloak", 128: "Left Ring", 256: "Right Ring",
    512: "Neck", 1024: "Belt", 2048: "Arrows", 4096: "Bullets", 8192: "Bolts",
    16384: "Creature Weapon L", 32768: "Creature Weapon R",
    65536: "Creature Weapon B", 131072: "Skin",
}


class _GFFType(IntEnum):
    """GFF field type ids (see GffReader.cs)."""
    BYTE = 0
    CHAR = 1
    WORD = 2
    SHORT = 3
    DWORD = 4
    INT = 5
    DWORD64 = 6
    INT64 = 7
    FLOAT = 8
    DOUBLE = 9
    CEXOSTRING = 10
    CRESREF = 11
    CEXOLOCSTRING = 12
    VOID = 13
    STRUCT = 14
    LIST = 15


class Gender(Enum):
    """Character gender"""
    MALE = 0
    FEMALE = 1
    OTHER = 2


class Race(Enum):
    """Character race"""
    DWARF = 0
    ELF = 1
    GNOME = 2
    HALFLING = 3
    HALF_ELF = 4
    HALF_ORC = 5
    HUMAN = 6
    ABERRATION = 7
    ANIMAL = 8
    BEAST = 9
    CONSTRUCT = 10
    DRAGON = 11
    GOBLINOID = 12
    MONSTROUS = 13
    ORC = 14
    REPTILIAN = 15
    ELEMENTAL = 16
    FEY = 17
    GIANT = 18
    MAGICAL_BEAST = 19
    OUTSIDER = 20
    SHAPECHANGER = 23
    UNDEAD = 24
    VERMIN = 25
    OOZE = 29


class CharacterClass(Enum):
    """Character class"""
    BARBARIAN = 0
    BARD = 1
    CLERIC = 2
    DRUID = 3
    FIGHTER = 4
    MONK = 5
    PALADIN = 6
    RANGER = 7
    ROGUE = 8
    SORCERER = 9
    WIZARD = 10
    ABERRATION = 11
    ANIMAL = 12
    CONSTRUCT = 13
    HUMANOID = 14
    MONSTROUS = 15
    ELEMENTAL = 16
    FEY = 17
    DRAGON = 18
    UNDEAD = 19
    COMMONER = 20
    BEAST = 21
    GIANT = 22
    MAGICAL_BEAST = 23
    OUTSIDER = 24
    SHAPECHANGER = 25
    VERMIN = 26
    SHADOWDANCER = 27
    HARPER_SCOUT = 28
    ARCANE_ARCHER = 29
    ASSASSIN = 30
    BLACKGUARD = 31
    CHAMPION_OF_TORM = 32
    WEAPON_MASTER = 33
    PALE_MASTER = 34
    SHIFTER = 35
    DWARVEN_DEFENDER = 36
    RED_DRAGON_DISCIPLE = 37
    OOZE = 38
    PURPLE_DRAGON_KNIGHT = 41


@dataclass
class ItemProperty:
    """One magical property from an item's ``PropertiesList`` struct.

    ``property_name`` is the itempropdef.2da row (the property type); ``subtype``
    keys the property's subtype table; ``cost_value`` is its magnitude (a +N for
    the linear-bonus properties). Named/formatted by :mod:`game.item_properties`.
    """
    property_name: int
    subtype: int
    cost_table: int
    cost_value: int
    param1: int
    param1_value: int


@dataclass
class InventoryItem:
    """One item from a ``.bic`` (``ItemList``/``Equip_ItemList`` struct).

    ``name`` is the item's ``LocalizedName`` (falling back to its resref/tag when
    blank — e.g. plain containers). ``contents`` holds a container's nested items.
    """
    name: str
    base_item: int
    tag: str
    resref: str
    stack_size: int
    identified: bool
    stolen: bool
    description: str
    #: ``ModelPart1`` — the item's icon/model variant (indexes the base item's icon).
    model_part: int = 0
    #: ``LocalizedName`` StrRef when the name is not stored inline (base items name
    #: themselves via ``dialog.tlk``); ``-1`` when a name is present inline.
    name_strref: int = -1
    properties: list[ItemProperty] = field(default_factory=list)
    contents: list["InventoryItem"] = field(default_factory=list)
    #: Where this item sits in an area's ``.git``, as ``((field, index), …)`` from
    #: the file root — empty for the player's own items, which are addressed from
    #: the character struct instead. Set by :mod:`vaultkeeper.game.save_area` so an
    #: area item can be edited in place rather than only copied.
    git_path: tuple = ()

    @property
    def is_container(self) -> bool:
        return bool(self.contents)

    @property
    def property_count(self) -> int:
        return len(self.properties)


@dataclass
class EquippedItem:
    """An :class:`InventoryItem` worn in an equipment slot."""
    slot: int  # the slot bit (2**INVENTORY_SLOT)
    slot_name: str
    item: InventoryItem


@dataclass
class CharacterInfo:
    """Character information extracted from BIC file"""
    name: str
    gender: Gender
    #: Race id (racialtypes.2da row); raw so PRC custom races past the base set are
    #: kept (named at display time via ``character.race_name``).
    race_id: int
    #: (class_id, level) per ClassList entry, raw class ids preserved (community/PRC
    #: classes past the base set are kept, not dropped; named at display time).
    classes: list[tuple[int, int]]
    level: int
    experience: int
    alignment_good_evil: int  # 0-100
    alignment_lawful_chaotic: int  # 0-100
    hit_points: int  # MaxHitPoints (SHORT)
    portrait_resref: str = ""  # Portrait resource reference
    gold: int = 0  # Gold pieces (DWORD)
    deity: str = ""  # Deity (CExoString)
    subrace: str = ""  # Subrace (CExoString)
    age: int = 0  # Age (INT)
    biography: str = ""  # Description (CExoLocString) — the PC's biography text
    armor_class: int = 0  # ArmorClass (SHORT)
    base_attack_bonus: int = 0  # BaseAttackBonus (BYTE)
    save_fortitude: int = 0  # FortSaveThrow (CHAR)
    save_reflex: int = 0  # RefSaveThrow (CHAR)
    save_will: int = 0  # WillSaveThrow (CHAR)
    current_hit_points: int = 0  # CurrentHitPoints (SHORT)
    abilities: dict[str, int] = field(default_factory=dict)  # Str/Dex/Con/Int/Wis/Cha
    #: FeatList feat ids (each struct's ``Feat`` WORD), order-preserving + distinct
    #: (C# ``Info.FeatInfo``). These index Feat Names.txt (line index = feat id).
    feat_ids: list[int] = field(default_factory=list)
    #: SkillList ranks (each struct's ``Rank`` BYTE), indexed by skill id
    #: (C# ``Info.SkillRanks``); index 0 = the first skill in Skill Names.txt.
    skill_ranks: list[int] = field(default_factory=list)
    #: Distinct spell ids the character knows/has memorised, gathered from every
    #: class's ``KnownList0..9`` / ``MemorizedList0..9`` (each entry's ``Spell``
    #: WORD). Order-preserving + distinct; index the bundled Spell Names.json.
    spell_ids: list[int] = field(default_factory=list)
    #: spell id -> lowest spell level it is known/memorised at (the ``KnownList<N>``
    #: / ``MemorizedList<N>`` index N).
    spell_levels: dict[int, int] = field(default_factory=dict)
    #: Items worn in equipment slots (``Equip_ItemList``).
    equipped_items: list[EquippedItem] = field(default_factory=list)
    #: Items carried in the backpack (``ItemList``); containers hold nested items.
    inventory_items: list[InventoryItem] = field(default_factory=list)
    is_valid: bool = True
    error_message: str = ""


class BicFileReader:
    """Reader for NWN BIC character files"""
    
    # Experience points required for each level
    LEVEL_XP = [
        0, 1000, 3000, 6000, 10000, 15000, 21000, 28000, 36000, 45000,
        55000, 66000, 78000, 91000, 105000, 120000, 136000, 153000,
        171000, 190000, 210000, 231000, 253000, 276000, 300000, 325000,
        351000, 378000, 406000, 435000, 465000, 496000, 528000, 561000,
        595000, 630000, 666000, 703000, 741000, 780000, 820000, 861000,
        903000, 946000, 990000, 1035000, 1081000, 1128000, 1176000,
        1225000, 1275000, 1326000, 1378000, 1431000, 1485000, 1540000,
        1596000, 1653000, 1711000, 1770000
    ]
    
    def __init__(self):
        pass
    
    def read_file(self, file_path: Path) -> CharacterInfo | None:
        """
        Read a BIC file and extract character information
        
        Args:
            file_path: Path to the BIC file
            
        Returns:
            CharacterInfo with extracted data, or None if error
        """
        if not file_path.exists():
            logger.error(f"BIC file does not exist: {file_path}")
            return None

        try:
            data = file_path.read_bytes()
            return self._parse_bic(data, file_path)
        except Exception as e:
            logger.error(f"Error reading BIC file {file_path}: {e}")
            return self._placeholder(file_path, error=str(e))

    @staticmethod
    def _placeholder(file_path: Path, error: str) -> CharacterInfo:
        """An invalid CharacterInfo used when a file cannot be parsed."""
        return CharacterInfo(
            name=file_path.stem,
            gender=Gender.MALE,
            race_id=Race.HUMAN.value,
            classes=[],
            level=1,
            experience=0,
            alignment_good_evil=50,
            alignment_lawful_chaotic=50,
            hit_points=10,
            portrait_resref="",
            is_valid=False,
            error_message=error,
        )

    def _parse_bic(self, data: bytes, file_path: Path) -> CharacterInfo:
        """Decode the character's top-level GFF struct straight from bytes."""
        try:
            gff = _GFF(data)
        except Exception as e:
            logger.error(f"Error parsing BIC file {file_path}: {e}")
            return self._placeholder(file_path, error=str(e))

        first_name = ""
        last_name = ""
        gender = Gender.MALE
        race_id = Race.HUMAN.value
        alignment_good_evil = 50
        alignment_lawful_chaotic = 50
        experience = 0
        hit_points = 10
        portrait_resref = ""
        gold = 0
        deity = ""
        subrace = ""
        age = 0
        biography = ""
        armor_class = 0
        base_attack_bonus = 0
        save_fortitude = 0
        save_reflex = 0
        save_will = 0
        current_hit_points = 0
        abilities: dict[str, int] = {}
        classes: list[tuple[int, int]] = []
        level = 0
        spell_ids: list[int] = []
        spell_levels: dict[int, int] = {}
        feat_ids: list[int] = []
        skill_ranks: list[int] = []
        equipped_items: list[EquippedItem] = []
        inventory_items: list[InventoryItem] = []

        # Walk the fields of the top-level (root) struct — struct 0.
        for label, ftype, raw in gff.iter_struct_fields(0):
            if label == "FirstName" and ftype == _GFFType.CEXOLOCSTRING:
                first_name = gff.read_value(ftype, raw) or ""
            elif label == "LastName" and ftype == _GFFType.CEXOLOCSTRING:
                last_name = gff.read_value(ftype, raw) or ""
            elif label == "Gender":
                val = gff.read_value(ftype, raw)
                if isinstance(val, int) and val in (0, 1, 2):
                    gender = Gender(val)
            elif label == "Race":
                val = gff.read_value(ftype, raw)
                if isinstance(val, int):
                    race_id = val
            elif label == "GoodEvil":
                val = gff.read_value(ftype, raw)
                if isinstance(val, int):
                    alignment_good_evil = val
            elif label == "LawfulChaotic":
                val = gff.read_value(ftype, raw)
                if isinstance(val, int):
                    alignment_lawful_chaotic = val
            elif label == "Experience" and ftype == _GFFType.DWORD:
                experience = gff.read_value(ftype, raw)
            elif label == "MaxHitPoints":
                val = gff.read_value(ftype, raw)
                if isinstance(val, int):
                    hit_points = val
            elif label == "Portrait" and ftype == _GFFType.CRESREF:
                portrait_resref = gff.read_value(ftype, raw) or ""
            elif label == "Gold" and ftype == _GFFType.DWORD:
                gold = gff.read_value(ftype, raw)
            elif label == "Deity" and ftype == _GFFType.CEXOSTRING:
                deity = gff.read_value(ftype, raw) or ""
            elif label == "Subrace" and ftype == _GFFType.CEXOSTRING:
                subrace = gff.read_value(ftype, raw) or ""
            elif label == "Description" and ftype == _GFFType.CEXOLOCSTRING:
                biography = gff.read_value(ftype, raw) or ""
            elif label == "Age" and ftype == _GFFType.INT:
                age = gff.read_value(ftype, raw)
            elif label == "ArmorClass":
                val = gff.read_value(ftype, raw)
                if isinstance(val, int):
                    armor_class = val
            elif label == "BaseAttackBonus" and ftype == _GFFType.BYTE:
                base_attack_bonus = gff.read_value(ftype, raw)
            elif label == "FortSaveThrow":
                val = gff.read_value(ftype, raw)
                if isinstance(val, int):
                    save_fortitude = val
            elif label == "RefSaveThrow":
                val = gff.read_value(ftype, raw)
                if isinstance(val, int):
                    save_reflex = val
            elif label == "WillSaveThrow":
                val = gff.read_value(ftype, raw)
                if isinstance(val, int):
                    save_will = val
            elif label == "CurrentHitPoints":
                val = gff.read_value(ftype, raw)
                if isinstance(val, int):
                    current_hit_points = val
            elif label in ABILITY_LABELS and ftype == _GFFType.BYTE:
                abilities[label] = gff.read_value(ftype, raw)
            elif label == "ClassList" and ftype == _GFFType.LIST:
                classes, level, spell_ids, spell_levels = self._read_class_list(
                    gff, gff.read_value(ftype, raw)
                )
            elif label == "FeatList" and ftype == _GFFType.LIST:
                feat_ids = self._read_feat_list(gff, gff.read_value(ftype, raw))
            elif label == "SkillList" and ftype == _GFFType.LIST:
                skill_ranks = self._read_skill_list(gff, gff.read_value(ftype, raw))
            elif label == "Equip_ItemList" and ftype == _GFFType.LIST:
                equipped_items = self._read_equipped(gff, gff.read_value(ftype, raw))
            elif label == "ItemList" and ftype == _GFFType.LIST:
                inventory_items = [
                    self._read_item(gff, sid) for sid in gff.read_value(ftype, raw)
                ]

        # Assemble the display name from first + last (fall back to file stem).
        name = " ".join(part for part in (first_name.strip(), last_name.strip()) if part)
        if not name:
            name = file_path.stem

        # Derive level from XP when the ClassList produced nothing usable.
        if level == 0 and experience > 0:
            level = self.get_level_from_xp(experience)
        if level == 0:
            level = 1  # Minimum level

        return CharacterInfo(
            name=name,
            gender=gender,
            race_id=race_id,
            classes=classes,
            level=level,
            experience=experience,
            alignment_good_evil=alignment_good_evil,
            alignment_lawful_chaotic=alignment_lawful_chaotic,
            hit_points=hit_points,
            portrait_resref=portrait_resref,
            gold=gold,
            deity=deity,
            subrace=subrace,
            age=age,
            biography=biography,
            armor_class=armor_class,
            base_attack_bonus=base_attack_bonus,
            save_fortitude=save_fortitude,
            save_reflex=save_reflex,
            save_will=save_will,
            current_hit_points=current_hit_points,
            abilities=abilities,
            feat_ids=feat_ids,
            skill_ranks=skill_ranks,
            spell_ids=spell_ids,
            spell_levels=spell_levels,
            equipped_items=equipped_items,
            inventory_items=inventory_items,
            is_valid=True,
        )

    #: Per-class spellbook list fields (spontaneous KnownList + prepared MemorizedList).
    _SPELL_LISTS = frozenset(
        [f"KnownList{i}" for i in range(10)] + [f"MemorizedList{i}" for i in range(10)]
    )

    @classmethod
    def _read_class_list(
        cls, gff: "_GFF", struct_ids: list[int]
    ) -> tuple[list[tuple[int, int]], int, list[int], dict[int, int]]:
        """Decode ClassList — each struct has a ``Class`` (INT) + ``ClassLevel`` (SHORT).

        Keeps every class id as a raw int so community/PRC classes past the base
        set are preserved (not dropped); name resolution happens at display time.
        Also gathers the distinct spell ids from each class's spellbook lists, plus
        each spell's lowest spell level (the ``KnownList<N>``/``MemorizedList<N>`` N).
        """
        classes: list[tuple[int, int]] = []
        level = 0
        spell_ids: list[int] = []
        spell_levels: dict[int, int] = {}
        seen_spells: set[int] = set()
        for struct_id in struct_ids:
            class_id: int | None = None
            class_level = 0
            for label, ftype, raw in gff.iter_struct_fields(struct_id):
                if label == "Class":
                    class_id = gff.read_value(ftype, raw)
                elif label == "ClassLevel":
                    class_level = gff.read_value(ftype, raw)
                elif label in cls._SPELL_LISTS and ftype == _GFFType.LIST:
                    spell_level = int(label[len("KnownList"):]) if label.startswith(
                        "KnownList"
                    ) else int(label[len("MemorizedList"):])
                    cls._collect_spells(
                        gff, gff.read_value(ftype, raw), spell_ids, seen_spells,
                        spell_level, spell_levels,
                    )
            if class_id is None:
                continue
            level += class_level
            classes.append((class_id, class_level))
        return classes, level, spell_ids, spell_levels

    @staticmethod
    def _collect_spells(
        gff: "_GFF", entry_ids: list[int], out: list[int], seen: set[int],
        spell_level: int, levels: dict[int, int],
    ) -> None:
        """Append each spellbook entry's ``Spell`` id (distinct) + record its level."""
        for entry_id in entry_ids:
            for label, ftype, raw in gff.iter_struct_fields(entry_id):
                if label == "Spell":
                    spell = gff.read_value(ftype, raw)
                    if isinstance(spell, int):
                        if spell not in seen:
                            seen.add(spell)
                            out.append(spell)
                        if spell_level < levels.get(spell, 99):
                            levels[spell] = spell_level

    @staticmethod
    def _read_feat_list(gff: "_GFF", struct_ids: list[int]) -> list[int]:
        """Decode FeatList — each struct holds a ``Feat`` (WORD) id (C# ``FeatInfo``).

        Collects the feat ids in order and de-duplicates them (C# ``.Distinct()``).
        """
        feat_ids: list[int] = []
        seen: set[int] = set()
        for struct_id in struct_ids:
            for label, ftype, raw in gff.iter_struct_fields(struct_id):
                if label == "Feat":
                    feat = gff.read_value(ftype, raw)
                    if isinstance(feat, int) and feat not in seen:
                        seen.add(feat)
                        feat_ids.append(feat)
        return feat_ids

    @staticmethod
    def _read_skill_list(gff: "_GFF", struct_ids: list[int]) -> list[int]:
        """Decode SkillList — each struct holds a ``Rank`` (BYTE); index = skill id."""
        ranks: list[int] = []
        for struct_id in struct_ids:
            rank = 0
            for label, ftype, raw in gff.iter_struct_fields(struct_id):
                if label == "Rank":
                    value = gff.read_value(ftype, raw)
                    if isinstance(value, int):
                        rank = value
            ranks.append(rank)
        return ranks

    @classmethod
    def _read_equipped(cls, gff: "_GFF", struct_ids: list[int]) -> list[EquippedItem]:
        """Decode ``Equip_ItemList`` — each struct's programmer id is its slot bit."""
        equipped: list[EquippedItem] = []
        for struct_id in struct_ids:
            slot = gff.struct_type(struct_id)
            item = cls._read_item(gff, struct_id)
            equipped.append(EquippedItem(slot, EQUIP_SLOT_NAMES.get(slot, f"Slot {slot}"), item))
        return equipped

    @classmethod
    def _read_item(cls, gff: "_GFF", struct_id: int) -> InventoryItem:
        """Decode one item struct, recursing into a container's nested ``ItemList``."""
        fields = {label: (ftype, raw) for label, ftype, raw in gff.iter_struct_fields(struct_id)}

        def value(name, default=None):
            if name in fields:
                return gff.read_value(*fields[name])
            return default

        name = (value("LocalizedName") or "").strip()
        resref = (value("TemplateResRef") or "").strip()
        tag = (value("Tag") or "").strip()
        name_strref = -1
        if not name:
            if "LocalizedName" in fields:
                name_strref = gff.read_locstring_strref(fields["LocalizedName"][1])
            name = f"(unnamed: {resref or tag})" if (resref or tag) else "(unnamed item)"

        description = (value("DescIdentified") or value("Description") or "").strip()
        properties: list[ItemProperty] = []
        if "PropertiesList" in fields:
            properties = [cls._read_property(gff, pid) for pid in (value("PropertiesList") or [])]
        contents: list[InventoryItem] = []
        if "ItemList" in fields:
            contents = [cls._read_item(gff, sid) for sid in (value("ItemList") or [])]

        return InventoryItem(
            name=name,
            base_item=value("BaseItem", -1) if isinstance(value("BaseItem"), int) else -1,
            tag=tag,
            resref=resref,
            stack_size=value("StackSize", 1) or 1,
            identified=bool(value("Identified", 0)),
            stolen=bool(value("Stolen", 0)),
            description=description,
            model_part=value("ModelPart1", 0) if isinstance(value("ModelPart1"), int) else 0,
            name_strref=name_strref,
            properties=properties,
            contents=contents,
        )

    @staticmethod
    def _read_property(gff: "_GFF", struct_id: int) -> ItemProperty:
        """Decode one ``PropertiesList`` entry into an :class:`ItemProperty`."""
        fields = {label: (ftype, raw) for label, ftype, raw in gff.iter_struct_fields(struct_id)}

        def value(name, default=0):
            if name in fields:
                val = gff.read_value(*fields[name])
                return val if isinstance(val, int) else default
            return default

        return ItemProperty(
            property_name=value("PropertyName"),
            subtype=value("Subtype"),
            cost_table=value("CostTable"),
            cost_value=value("CostValue"),
            param1=value("Param1", 255),
            param1_value=value("Param1Value"),
        )

    def get_race_name(self, race_id: int) -> str:
        """Get race name from ID"""
        try:
            return Race(race_id).name.replace('_', ' ').title()
        except ValueError:
            return f"Race {race_id}"
    
    def get_class_name(self, class_id: int) -> str:
        """Get class name from ID"""
        try:
            return CharacterClass(class_id).name.replace('_', ' ').title()
        except ValueError:
            return f"Class {class_id}"
    
    def get_gender_name(self, gender_id: int) -> str:
        """Get gender name from ID"""
        try:
            return Gender(gender_id).name.title()
        except ValueError:
            return "Other"
    
    def get_alignment_title(self, lawful_chaotic: int, good_evil: int) -> str:
        """Get alignment title based on axes"""
        # Map to 9-point alignment system
        lc = "Lawful" if lawful_chaotic > 66 else ("Chaotic" if lawful_chaotic < 33 else "Neutral")
        ge = "Good" if good_evil > 66 else ("Evil" if good_evil < 33 else "Neutral")
        
        if lc == "Neutral" and ge == "Neutral":
            return "True Neutral"
        else:
            return f"{lc} {ge}"
    
    def get_level_from_xp(self, xp: int) -> int:
        """Get character level from experience points"""
        for i, level_xp in enumerate(self.LEVEL_XP):
            if xp < level_xp:
                return max(0, i - 1)
        return len(self.LEVEL_XP)
    
    def get_xp_for_level(self, level: int) -> int:
        """Get experience points required for a level"""
        if level < len(self.LEVEL_XP):
            return self.LEVEL_XP[level]
        return self.LEVEL_XP[-1]


class _GFF:
    """Minimal GFF (V3.2) reader over an in-memory buffer.

    Offsets are absolute (the BIC's GFF starts at byte 0). Mirrors the section
    handling of ``GffReader.cs`` / ``module_reader.py``: the header stores six
    ``(offset, count)`` pairs; a struct's ``DataOrDataOffset`` is a *field id*
    when it has one field, otherwise a *byte offset* into the field-indices
    array (hence ``offset // 4`` to reach the first id — the ``* 4`` scaling the
    salvaged ``gff_reader`` applied on top of an already-byte offset is what read
    past EOF).
    """

    _HEADER = struct.Struct("<12I")

    def __init__(self, data: bytes):
        self._data = data
        if len(data) < 56:
            raise ValueError("File too small to be a valid GFF file")

        version = data[4:8].decode("ascii", "replace")
        if version != "V3.2":
            raise ValueError(f"Unsupported GFF version {version!r} (expected 'V3.2')")

        (
            self._struct_offset, self._struct_count,
            self._field_offset, self._field_count,
            self._label_offset, self._label_count,
            self._field_data_offset, _field_data_len,
            self._field_indices_offset, self._field_indices_len,
            self._list_indices_offset, _list_indices_len,
        ) = self._HEADER.unpack_from(data, 8)

    def struct_type(self, struct_id: int) -> int:
        """The struct's programmer-defined type id (the first header word).

        For ``Equip_ItemList`` elements this is the equipment slot bit (``2**slot``).
        """
        if not 0 <= struct_id < self._struct_count:
            return -1
        return struct.unpack_from("<I", self._data, self._struct_offset + struct_id * 12)[0]

    def read_locstring_strref(self, raw: bytes) -> int:
        """The StrRef of a ``CExoLocString`` field (``-1`` when none is set)."""
        offset = struct.unpack("<I", raw)[0]
        return struct.unpack_from("<i", self._data, self._field_data_offset + offset + 4)[0]

    def iter_struct_fields(self, struct_id: int):
        """Yield ``(label, field_type, raw4)`` for every field of a struct."""
        if not 0 <= struct_id < self._struct_count:
            return
        base = self._struct_offset + struct_id * 12
        _type_id, id_or_offset, field_count = struct.unpack_from("<3I", self._data, base)

        if field_count == 1:
            field_ids = [id_or_offset]
        elif field_count > 1:
            # id_or_offset is a byte offset into the field-indices array.
            start = self._field_indices_offset + id_or_offset
            field_ids = struct.unpack_from(f"<{field_count}I", self._data, start)
        else:
            field_ids = []

        for field_id in field_ids:
            yield self._read_field_header(field_id)

    def _read_field_header(self, field_id: int) -> tuple[str, int, bytes]:
        """Return ``(label, field_type, raw4)`` for a field entry (12 bytes)."""
        base = self._field_offset + field_id * 12
        field_type, label_id = struct.unpack_from("<2I", self._data, base)
        raw = self._data[base + 8:base + 12]
        label = self._read_label(label_id)
        return label, field_type, raw

    def _read_label(self, label_id: int) -> str:
        if not 0 <= label_id < self._label_count:
            return ""
        start = self._label_offset + label_id * 16
        return self._data[start:start + 16].split(b"\x00", 1)[0].decode("ascii", "replace")

    def read_value(self, field_type: int, raw: bytes):
        """Decode a field value. ``raw`` is the 4-byte DataOrDataOffset word."""
        if field_type == _GFFType.BYTE:
            return raw[0]
        if field_type == _GFFType.CHAR:
            return struct.unpack("<b", raw[:1])[0]
        if field_type == _GFFType.WORD:
            return struct.unpack("<H", raw[:2])[0]
        if field_type == _GFFType.SHORT:
            return struct.unpack("<h", raw[:2])[0]
        if field_type == _GFFType.DWORD:
            return struct.unpack("<I", raw)[0]
        if field_type == _GFFType.INT:
            return struct.unpack("<i", raw)[0]
        if field_type == _GFFType.FLOAT:
            return struct.unpack("<f", raw)[0]

        # Complex types: raw is a byte offset into the field-data block.
        offset = struct.unpack("<I", raw)[0]
        if field_type == _GFFType.DWORD64:
            return struct.unpack_from("<Q", self._data, self._field_data_offset + offset)[0]
        if field_type == _GFFType.INT64:
            return struct.unpack_from("<q", self._data, self._field_data_offset + offset)[0]
        if field_type == _GFFType.DOUBLE:
            return struct.unpack_from("<d", self._data, self._field_data_offset + offset)[0]
        if field_type == _GFFType.CEXOSTRING:
            return self._read_cexostring(offset)
        if field_type == _GFFType.CRESREF:
            return self._read_cresref(offset)
        if field_type == _GFFType.CEXOLOCSTRING:
            return self._read_cexolocstring(offset)
        if field_type == _GFFType.STRUCT:
            return offset  # struct id
        if field_type == _GFFType.LIST:
            return self._read_list(offset)
        return None

    def _read_cexostring(self, offset: int) -> str:
        pos = self._field_data_offset + offset
        length = struct.unpack_from("<I", self._data, pos)[0]
        return self._data[pos + 4:pos + 4 + length].decode("utf-8", "replace")

    def _read_cresref(self, offset: int) -> str:
        pos = self._field_data_offset + offset
        length = self._data[pos]
        return self._data[pos + 1:pos + 1 + length].decode("ascii", "replace")

    def _read_cexolocstring(self, offset: int) -> str:
        """Return the first substring's text (names carry one gendered locale)."""
        pos = self._field_data_offset + offset
        # total length (4, ignored), strref (4, ignored), substring count (4).
        count = struct.unpack_from("<I", self._data, pos + 8)[0]
        pos += 12
        for _ in range(count):
            _string_id, length = struct.unpack_from("<2I", self._data, pos)
            pos += 8
            text = self._data[pos:pos + length].decode("utf-8", "replace")
            pos += length
            return text
        return ""

    def _read_list(self, offset: int) -> list[int]:
        pos = self._list_indices_offset + offset
        count = struct.unpack_from("<I", self._data, pos)[0]
        if count == 0:
            return []
        return list(struct.unpack_from(f"<{count}I", self._data, pos + 4))
