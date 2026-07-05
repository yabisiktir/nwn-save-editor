"""
BIC file format reader for Neverwinter Nights character files
Ported from VB.NET BicFileInfo.vb
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from vaultkeeper.core.log import get_logger

logger = get_logger(__name__)


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
class CharacterInfo:
    """Character information extracted from BIC file"""
    name: str
    gender: Gender
    race: Race
    classes: list[tuple[CharacterClass, int]]  # (class, level)
    level: int
    experience: int
    alignment_good_evil: int  # 0-100
    alignment_lawful_chaotic: int  # 0-100
    hit_points: int
    portrait_resref: str = ""  # Portrait resource reference
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
            with open(file_path, 'rb') as f:
                return self._parse_bic(f, file_path)
        except Exception as e:
            logger.error(f"Error reading BIC file {file_path}: {e}")
            return CharacterInfo(
                name="",
                gender=Gender.MALE,
                race=Race.HUMAN,
                classes=[],
                level=0,
                experience=0,
                alignment_good_evil=50,
                alignment_lawful_chaotic=50,
                hit_points=0,
                portrait_resref="",
                is_valid=False,
                error_message=str(e)
            )
    
    def _parse_bic(self, file, file_path: Path) -> CharacterInfo:
        """Parse BIC file structure using GFF parser"""
        try:
            # Use the full GFF parser
            from vaultkeeper.core.formats.gff_reader import GFFReader

            reader = GFFReader()
            gff_file = reader.read_file(file_path)
            
            if not gff_file or not gff_file.root_struct:
                raise ValueError("Failed to parse GFF file")
            
            # Extract character data from GFF structure
            root = gff_file.root_struct
            
            # Get character name (CExoString field "FirstName")
            name = "Unknown"
            if "FirstName" in root.fields:
                name_field = root.fields["FirstName"]
                if isinstance(name_field, str):
                    name = name_field
                elif hasattr(name_field, 'string'):
                    name = name_field.string
            
            # Fallback to file stem if no name
            if not name or name == "Unknown":
                name = file_path.stem
            
            # Get gender
            gender = Gender.MALE
            if "Gender" in root.fields:
                gender_val = root.fields["Gender"]
                if isinstance(gender_val, int) and gender_val in [0, 1, 2]:
                    gender = Gender(gender_val)
            
            # Get race
            race = Race.HUMAN
            if "Race" in root.fields:
                race_val = root.fields["Race"]
                if isinstance(race_val, int):
                    try:
                        race = Race(race_val)
                    except ValueError:
                        race = Race.HUMAN
            
            # Get classes and levels
            classes = []
            level = 0
            
            # Try to get class info from ClassList
            if "ClassList" in root.fields:
                class_list = root.fields["ClassList"]
                if isinstance(class_list, list):
                    for class_info in class_list:
                        if isinstance(class_info, dict):
                            class_id = class_info.get("Class", 0)
                            class_level = class_info.get("Level", 1)
                            try:
                                char_class = CharacterClass(class_id)
                                classes.append((char_class, class_level))
                                level += class_level
                            except ValueError:
                                pass
            
            # If no classes found, try individual class fields
            if not classes:
                for i in range(1, 4):  # Check up to 3 classes
                    class_key = f"Class{i}"
                    level_key = f"Class{i}Level"
                    
                    if class_key in root.fields and level_key in root.fields:
                        class_id = root.fields[class_key]
                        class_level = root.fields[level_key]
                        
                        if isinstance(class_id, int) and isinstance(class_level, int):
                            try:
                                char_class = CharacterClass(class_id)
                                classes.append((char_class, class_level))
                                level += class_level
                            except ValueError:
                                pass
            
            # Get experience
            experience = 0
            if "Experience" in root.fields:
                exp_val = root.fields["Experience"]
                if isinstance(exp_val, int):
                    experience = exp_val
            
            # Calculate level from XP if not determined from classes
            if level == 0 and experience > 0:
                level = self.get_level_from_xp(experience)
            
            if level == 0:
                level = 1  # Minimum level
            
            # Get alignment
            alignment_good_evil = 50
            alignment_lawful_chaotic = 50
            
            if "GoodEvil" in root.fields:
                ge_val = root.fields["GoodEvil"]
                if isinstance(ge_val, int):
                    alignment_good_evil = ge_val
            
            if "LawfulChaotic" in root.fields:
                lc_val = root.fields["LawfulChaotic"]
                if isinstance(lc_val, int):
                    alignment_lawful_chaotic = lc_val
            
            # Get hit points
            hit_points = 10
            if "HitPoints" in root.fields:
                hp_val = root.fields["HitPoints"]
                if isinstance(hp_val, int):
                    hit_points = hp_val
            elif "MaxHitPoints" in root.fields:
                hp_val = root.fields["MaxHitPoints"]
                if isinstance(hp_val, int):
                    hit_points = hp_val
            
            # Get portrait resref
            portrait_resref = ""
            if "Portrait" in root.fields:
                port_val = root.fields["Portrait"]
                if isinstance(port_val, str):
                    portrait_resref = port_val
                elif hasattr(port_val, 'resref'):
                    portrait_resref = port_val.resref
            
            return CharacterInfo(
                name=name,
                gender=gender,
                race=race,
                classes=classes,
                level=level,
                experience=experience,
                alignment_good_evil=alignment_good_evil,
                alignment_lawful_chaotic=alignment_lawful_chaotic,
                hit_points=hit_points,
                portrait_resref=portrait_resref,
                is_valid=True
            )
            
        except Exception as e:
            logger.error(f"Error parsing BIC file: {e}")
            # Return placeholder but mark as invalid
            return CharacterInfo(
                name=file_path.stem,
                gender=Gender.MALE,
                race=Race.HUMAN,
                classes=[],
                level=1,
                experience=0,
                alignment_good_evil=50,
                alignment_lawful_chaotic=50,
                hit_points=10,
                portrait_resref="",
                is_valid=False,
                error_message=str(e)
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
