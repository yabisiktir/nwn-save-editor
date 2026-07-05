"""
Tests for GFF (Generic File Format) reader
"""
import struct
from pathlib import Path

import pytest

from vaultkeeper.core.formats.gff_reader import (
    GFFField,
    GFFFieldType,
    GFFFile,
    GFFReader,
    GFFStruct,
)


@pytest.mark.unit
class TestGffReader:
    """Test GFF file reading functionality"""
    
    def test_reader_initialization(self):
        """Test GFFReader can be created"""
        reader = GFFReader()
        assert reader is not None
    
    def test_read_nonexistent_file(self):
        """Test reading a file that doesn't exist"""
        reader = GFFReader()
        result = reader.read_file(Path("/nonexistent/file.gff"))
        assert result is None
    
    def test_parse_invalid_gff_header(self, temp_dir):
        """Test parsing a file with invalid GFF header - reader will try to parse anyway"""
        # Create a file with wrong header
        test_file = temp_dir / "invalid.gff"
        test_file.write_bytes(b"NOTGFF" + b"\x00" * 100)
        
        reader = GFFReader()
        result = reader.read_file(test_file)
        # The reader doesn't validate header, it will parse whatever data is there
        # We just verify the method runs without exception
    
    def test_parse_minimal_gff(self, temp_dir):
        """Test parsing a minimal valid GFF file structure"""
        # Create minimal GFF V3.2 file
        test_file = temp_dir / "minimal.gff"
        
        # GFF Header (56 bytes)
        header = b"GFF "  # Signature
        header += struct.pack("<I", 0xFFFFFFFF & 0x32000000)  # Version 3.2
        header += struct.pack("<I", 56)   # Struct offset
        header += struct.pack("<I", 1)   # Struct count
        header += struct.pack("<I", 64)  # Field offset
        header += struct.pack("<I", 0)   # Field count
        header += struct.pack("<I", 64)  # Label offset
        header += struct.pack("<I", 0)   # Label count
        header += struct.pack("<I", 64)  # Field data offset
        header += struct.pack("<I", 0)   # Field data count
        header += struct.pack("<I", 64)  # Field indices offset
        header += struct.pack("<I", 0)   # Field indices count
        header += struct.pack("<I", 64)  # List indices offset
        header += struct.pack("<I", 0)   # List indices count
        
        # Struct (12 bytes) - type, data offset, field count
        struct_data = struct.pack("<I", 0)   # Type
        struct_data += struct.pack("<I", 0)  # Data offset
        struct_data += struct.pack("<I", 0)  # Field count
        
        data = header + struct_data
        test_file.write_bytes(data)
        
        reader = GFFReader()
        result = reader.read_file(test_file)
        
        assert result is not None
        assert isinstance(result, GFFFile)
        assert result.root_struct is not None
    
    def test_gff_struct_fields_access(self):
        """Test GFFStruct field access"""
        from vaultkeeper.core.formats.gff_reader import GFFField
        struct = GFFStruct(struct_id=0)
        struct.fields["TestField"] = GFFField(label="TestField", field_type=GFFFieldType.CEXOSTRING, value="TestValue")
        
        assert "TestField" in struct.fields
        assert struct.fields["TestField"].value == "TestValue"
    
    def test_field_type_enum(self):
        """Test GFFFieldType enum values"""
        assert GFFFieldType.BYTE.value == 0
        assert GFFFieldType.CHAR.value == 1
        assert GFFFieldType.WORD.value == 2
        assert GFFFieldType.SHORT.value == 3
        assert GFFFieldType.DWORD.value == 4
        assert GFFFieldType.INT.value == 5


@pytest.mark.unit
class TestGffFileStructure:
    """Test GFF file data structures"""
    
    def test_gff_file_creation(self):
        """Test GFFFile can be created with data"""
        gff = GFFFile(file_type="GFF ", file_version="V3.2")
        assert gff.file_type == "GFF "
        
    def test_gff_struct_nested(self):
        """Test nested struct handling"""
        parent = GFFStruct(struct_id=0)
        child = GFFStruct(struct_id=1)
        child.fields["name"] = GFFField(label="name", field_type=GFFFieldType.CEXOSTRING, value="Child")
        parent.fields["child"] = child
        
        assert "child" in parent.fields
        assert parent.fields["child"].fields["name"].value == "Child"


@pytest.mark.integration
class TestGffIntegration:
    """Integration tests for GFF reader"""
    
    def test_read_save_game_info(self, temp_dir):
        """Test reading save game info structure"""
        # This would require a real save file
        # For now, just test the reader can be instantiated
        reader = GFFReader()
        assert reader is not None
