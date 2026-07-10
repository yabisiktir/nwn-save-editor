"""
Tests for BIC (Character) file reader
"""
from pathlib import Path

import pytest

from vaultkeeper.core.formats.bic_reader import (
    BicFileReader,
    CharacterClass,
    CharacterInfo,
    Gender,
    Race,
)


@pytest.mark.unit
class TestBicFileReader:
    """Test BIC file reading functionality"""
    
    def test_reader_initialization(self):
        """Test BicFileReader can be created"""
        reader = BicFileReader()
        assert reader is not None
    
    def test_read_nonexistent_file(self):
        """Test reading a file that doesn't exist"""
        reader = BicFileReader()
        result = reader.read_file(Path("/nonexistent/character.bic"))
        assert result is None
    
    def test_race_name_lookup(self):
        """Test race name conversion"""
        reader = BicFileReader()
        
        assert reader.get_race_name(0) == "Dwarf"
        assert reader.get_race_name(1) == "Elf"
        assert reader.get_race_name(6) == "Human"
        assert reader.get_race_name(999) == "Race 999"
    
    def test_class_name_lookup(self):
        """Test class name conversion"""
        reader = BicFileReader()
        
        assert reader.get_class_name(0) == "Barbarian"
        assert reader.get_class_name(4) == "Fighter"
        assert reader.get_class_name(9) == "Sorcerer"
        assert reader.get_class_name(999) == "Class 999"
    
    def test_gender_name_lookup(self):
        """Test gender name conversion"""
        reader = BicFileReader()
        
        assert reader.get_gender_name(0) == "Male"
        assert reader.get_gender_name(1) == "Female"
        assert reader.get_gender_name(2) == "Other"
        assert reader.get_gender_name(999) == "Other"
    
    def test_alignment_calculation(self):
        """Test alignment title calculation"""
        reader = BicFileReader()
        
        # Lawful Good
        assert reader.get_alignment_title(100, 100) == "Lawful Good"
        # Chaotic Evil
        assert reader.get_alignment_title(0, 0) == "Chaotic Evil"
        # True Neutral
        assert reader.get_alignment_title(50, 50) == "True Neutral"
        # Neutral Good
        assert reader.get_alignment_title(50, 100) == "Neutral Good"
    
    def test_level_from_xp(self):
        """Test level calculation from XP"""
        reader = BicFileReader()
        
        assert reader.get_level_from_xp(0) == 0
        assert reader.get_level_from_xp(500) == 0
        assert reader.get_level_from_xp(1000) == 1
        assert reader.get_level_from_xp(2000) == 1
        assert reader.get_level_from_xp(3000) == 2
        assert reader.get_level_from_xp(15000) == 5
        assert reader.get_level_from_xp(300000) == 24
    
    def test_xp_for_level(self):
        """Test XP required for level"""
        reader = BicFileReader()
        
        assert reader.get_xp_for_level(1) == 1000
        assert reader.get_xp_for_level(5) == 15000
        assert reader.get_xp_for_level(20) == 210000


@pytest.mark.unit
class TestCharacterInfo:
    """Test CharacterInfo data class"""
    
    def test_character_info_creation(self):
        """Test CharacterInfo can be created"""
        char = CharacterInfo(
            name="TestCharacter",
            gender=Gender.MALE,
            race=Race.HUMAN,
            classes=[(CharacterClass.FIGHTER, 5)],
            level=5,
            experience=15000,
            alignment_good_evil=50,
            alignment_lawful_chaotic=50,
            hit_points=50,
            portrait_resref="po_human_m_",
            is_valid=True
        )
        
        assert char.name == "TestCharacter"
        assert char.gender == Gender.MALE
        assert char.race == Race.HUMAN
        assert char.level == 5
        assert char.is_valid is True
    
    def test_character_info_invalid(self):
        """Test invalid CharacterInfo"""
        char = CharacterInfo(
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
            error_message="Parse error"
        )
        
        assert char.is_valid is False
        assert char.error_message == "Parse error"


@pytest.mark.integration
class TestBicIntegration:
    """Integration tests for BIC reader"""
    
    def test_parse_with_gff_integration(self, temp_dir):
        """Test BIC parsing with actual GFF structure"""
        import struct

        from vaultkeeper.core.formats.gff_reader import GFFReader
        
        # Create a minimal GFF structure that looks like a BIC file
        test_file = temp_dir / "test.bic"
        
        # GFF Header
        header = b"GFF "
        header += struct.pack("<I", 0xFFFFFFFF & 0x32000000)  # Version 3.2
        header += struct.pack("<I", 56)   # Struct offset
        header += struct.pack("<I", 1)   # Struct count
        header += struct.pack("<I", 68)  # Field offset
        header += struct.pack("<I", 1)   # Field count
        header += struct.pack("<I", 80)  # Label offset
        header += struct.pack("<I", 1)   # Label count
        header += struct.pack("<I", 96)  # Field data offset
        header += struct.pack("<I", 16)  # Field data count
        header += struct.pack("<I", 112) # Field indices offset
        header += struct.pack("<I", 0)   # Field indices count
        header += struct.pack("<I", 112) # List indices offset
        header += struct.pack("<I", 0)   # List indices count
        
        # Struct (12 bytes)
        struct_data = struct.pack("<I", 0)   # Type
        struct_data += struct.pack("<I", 0)  # Data offset
        struct_data += struct.pack("<I", 1)  # Field count
        
        # Field (12 bytes) - type, label index, data/offset
        field = struct.pack("<I", 10)  # Type: CExoString (10)
        field += struct.pack("<I", 0)  # Label index
        field += struct.pack("<I", 0)  # Data offset (relative)
        
        # Label (16 bytes)
        label = b"FirstName\x00\x00\x00\x00\x00"[:16]
        
        # Field data - CExoString (4 byte length + string)
        name = b"Hero"
        field_data = struct.pack("<I", len(name)) + name
        
        data = header + struct_data + field + label + field_data
        test_file.write_bytes(data)
        
        # Test that GFF reader can read this
        reader = GFFReader()
        gff_file = reader.read_file(test_file)
        assert gff_file is not None


REAL_BIC = (
    Path.home()
    / "Documents"
    / "Neverwinter Nights"
    / "saves"
    / "000000 - quicksave"
    / "player.bic"
)


@pytest.mark.integration
@pytest.mark.skipif(not REAL_BIC.is_file(), reason="No real NWN player.bic on this machine")
class TestRealBic:
    """Parse a real NWN character file end-to-end (the format the salvaged
    generic GFF reader could not decode)."""

    def test_parses_real_player_bic(self):
        info = BicFileReader().read_file(REAL_BIC)

        assert info is not None
        # A real parse — not the level=1/hp=10 placeholder returned on failure.
        assert info.is_valid
        assert info.error_message == ""

        # FirstName/LastName (CExoLocString) resolved to a non-placeholder name.
        assert info.name
        assert info.name != REAL_BIC.stem  # not the "player" file-stem fallback

        # ClassList decoded into concrete classes whose levels sum to the total.
        assert info.classes
        for char_class, class_level in info.classes:
            assert isinstance(char_class, CharacterClass)
            assert class_level > 0
        assert info.level == sum(level for _cls, level in info.classes)

        # Scalar fields fall in sane ranges.
        assert info.experience > 0
        assert info.hit_points > 0
        assert 0 <= info.alignment_good_evil <= 100
        assert 0 <= info.alignment_lawful_chaotic <= 100

        # Portrait resref (CResRef) is present for the Portrait Manager UI.
        assert isinstance(info.portrait_resref, str)
        assert info.portrait_resref  # this character has a portrait set

        # FeatList / SkillList decode into feat ids and per-skill ranks.
        assert info.feat_ids and all(isinstance(f, int) for f in info.feat_ids)
        assert len(info.feat_ids) == len(set(info.feat_ids))  # distinct (C# .Distinct())
        assert info.skill_ranks and all(r >= 0 for r in info.skill_ranks)

    def test_real_player_bic_extended_fields(self):
        """Gold (DWORD), Deity (CExoString) and the six ability scores decode."""
        from vaultkeeper.core.formats.bic_reader import ABILITY_LABELS
        from vaultkeeper.game.character import character_summary

        info = BicFileReader().read_file(REAL_BIC)
        assert info.is_valid
        assert isinstance(info.gold, int) and info.gold >= 0
        assert isinstance(info.deity, str)
        # A real character carries all six ability scores in a sane 1..60 range.
        assert set(info.abilities) == set(ABILITY_LABELS)
        for score in info.abilities.values():
            assert 1 <= score <= 60

        # The stats block only appears when requested; gold/deity always show.
        with_stats = character_summary(info, show_stats=True)
        without = character_summary(info, show_stats=False)
        assert "Gold:" in without
        assert "Str:" in with_stats and "Str:" not in without
        if info.deity:
            assert f"Deity: {info.deity}" in without
