"""
GFF (Generic File Format) Reader for Neverwinter Nights
Ported from VB.NET GFF reading functionality

GFF is the binary format used for:
- .sav files (game saves)
- .bic files (characters)
- .ifo files (module info)
- .git files (area instances)
- And many other NWN file types
"""

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

from nwnfile.log import get_logger

logger = get_logger(__name__)


class GFFFieldType(IntEnum):
    """GFF field types as defined in NWN file format"""
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
    RESREF = 11
    CEXOLocString = 12
    VOID = 13
    STRUCT = 14
    LIST = 15
    ORIENTATION = 16
    VECTOR = 17


@dataclass
class GFFField:
    """A single field in a GFF structure"""
    label: str
    field_type: GFFFieldType
    value: Any


@dataclass
class GFFStruct:
    """A structure containing GFF fields"""
    struct_id: int
    fields: dict[str, GFFField] = field(default_factory=dict)
    
    def get_field(self, label: str) -> GFFField | None:
        """Get a field by label"""
        return self.fields.get(label)
    
    def get_value(self, label: str, default: Any = None) -> Any:
        """Get a field value by label with default"""
        field = self.fields.get(label)
        return field.value if field else default


@dataclass
class GFFFile:
    """Complete GFF file structure"""
    file_type: str  # 4-character file type
    file_version: str  # 4-character version
    structs: list[GFFStruct] = field(default_factory=list)
    root_struct: GFFStruct | None = None
    
    def get_root_value(self, label: str, default: Any = None) -> Any:
        """Get value from root structure"""
        if self.root_struct:
            return self.root_struct.get_value(label, default)
        return default


class GFFReader:
    """Reader for GFF (Generic File Format) files"""
    
    def __init__(self):
        self._data: bytes = b""
        self._offset: int = 0
        
        # Header offsets
        self._structs_offset: int = 0
        self._fields_offset: int = 0
        self._labels_offset: int = 0
        self._field_data_offset: int = 0
        self._field_indices_offset: int = 0
        self._list_indices_offset: int = 0
        
        # Cached structures
        self._structs: list[GFFStruct] = []
        self._labels: list[str] = []
    
    def read_file(self, file_path: Path) -> GFFFile | None:
        """Read a GFF file from disk"""
        try:
            with open(file_path, 'rb') as f:
                self._data = f.read()
            self._offset = 0
            
            return self._parse_gff()
        except Exception as e:
            logger.error(f"Error reading GFF file {file_path}: {e}")
            return None
    
    def read_bytes(self, data: bytes) -> GFFFile | None:
        """Read GFF data from bytes"""
        self._data = data
        self._offset = 0
        return self._parse_gff()
    
    def _parse_gff(self) -> GFFFile | None:
        """Parse the GFF file structure"""
        if len(self._data) < 56:  # Minimum GFF header size
            logger.error("File too small to be a valid GFF file")
            return None
        
        # Read header
        file_type = self._read_string(4)
        file_version = self._read_string(4)
        
        # Read section offsets and counts
        struct_offset = self._read_dword()
        struct_count = self._read_dword()
        field_offset = self._read_dword()
        field_count = self._read_dword()
        label_offset = self._read_dword()
        label_count = self._read_dword()
        field_data_offset = self._read_dword()
        field_data_count = self._read_dword()
        field_indices_offset = self._read_dword()
        field_indices_count = self._read_dword()
        list_indices_offset = self._read_dword()
        list_indices_count = self._read_dword()
        
        self._structs_offset = struct_offset
        self._fields_offset = field_offset
        self._labels_offset = label_offset
        self._field_data_offset = field_data_offset
        self._field_indices_offset = field_indices_offset
        self._list_indices_offset = list_indices_offset
        
        # Parse labels
        self._labels = self._parse_labels(label_offset, label_count)
        
        # Parse structures
        self._structs = self._parse_structs(struct_offset, struct_count)
        
        # Create GFF file
        gff_file = GFFFile(
            file_type=file_type,
            file_version=file_version,
            structs=self._structs,
            root_struct=self._structs[0] if self._structs else None
        )
        
        return gff_file
    
    def _read_byte(self) -> int:
        """Read a single byte"""
        value = self._data[self._offset]
        self._offset += 1
        return value
    
    def _read_word(self) -> int:
        """Read a 2-byte word (little-endian)"""
        value = struct.unpack_from('<H', self._data, self._offset)[0]
        self._offset += 2
        return value
    
    def _read_short(self) -> int:
        """Read a 2-byte signed short (little-endian)"""
        value = struct.unpack_from('<h', self._data, self._offset)[0]
        self._offset += 2
        return value
    
    def _read_dword(self) -> int:
        """Read a 4-byte dword (little-endian)"""
        value = struct.unpack_from('<I', self._data, self._offset)[0]
        self._offset += 4
        return value
    
    def _read_int(self) -> int:
        """Read a 4-byte signed int (little-endian)"""
        value = struct.unpack_from('<i', self._data, self._offset)[0]
        self._offset += 4
        return value
    
    def _read_dword64(self) -> int:
        """Read an 8-byte dword64 (little-endian)"""
        value = struct.unpack_from('<Q', self._data, self._offset)[0]
        self._offset += 8
        return value
    
    def _read_int64(self) -> int:
        """Read an 8-byte signed int64 (little-endian)"""
        value = struct.unpack_from('<q', self._data, self._offset)[0]
        self._offset += 8
        return value
    
    def _read_float(self) -> float:
        """Read a 4-byte float (little-endian)"""
        value = struct.unpack_from('<f', self._data, self._offset)[0]
        self._offset += 4
        return value
    
    def _read_double(self) -> float:
        """Read an 8-byte double (little-endian)"""
        value = struct.unpack_from('<d', self._data, self._offset)[0]
        self._offset += 8
        return value
    
    def _read_string(self, length: int) -> str:
        """Read a fixed-length string"""
        value = self._data[self._offset:self._offset + length].decode('latin-1')
        self._offset += length
        return value
    
    def _read_cstring(self) -> str:
        """Read a null-terminated C-style string"""
        end = self._offset
        while end < len(self._data) and self._data[end] != 0:
            end += 1
        value = self._data[self._offset:end].decode('utf-8', errors='ignore')
        self._offset = end + 1  # Skip null terminator
        return value
    
    def _read_resref(self) -> str:
        """Read a RESREF (1 byte length + string)"""
        length = self._read_byte()
        return self._read_string(length)
    
    def _read_vector(self) -> tuple:
        """Read a 3D vector (3 floats)"""
        x = self._read_float()
        y = self._read_float()
        z = self._read_float()
        return (x, y, z)
    
    def _read_orientation(self) -> tuple:
        """Read a 4D orientation (4 floats)"""
        w = self._read_float()
        x = self._read_float()
        y = self._read_float()
        z = self._read_float()
        return (w, x, y, z)
    
    def _parse_labels(self, offset: int, count: int) -> list[str]:
        """Parse the label table"""
        labels = []
        self._offset = offset
        
        for _ in range(count):
            # Labels are 16 bytes, null-padded
            label_data = self._data[self._offset:self._offset + 16]
            label = label_data.split(b'\x00')[0].decode('utf-8', errors='ignore')
            labels.append(label)
            self._offset += 16
        
        return labels
    
    def _parse_structs(self, offset: int, count: int) -> list[GFFStruct]:
        """Parse the struct table"""
        structs = []
        
        for i in range(count):
            self._offset = offset + (i * 12)  # Each struct entry is 12 bytes
            
            struct_id = self._read_dword()
            field_index = self._read_dword()
            field_count = self._read_dword()
            
            # Parse fields for this struct
            fields = self._parse_struct_fields(field_index, field_count)
            
            gff_struct = GFFStruct(struct_id=struct_id, fields=fields)
            structs.append(gff_struct)
        
        return structs
    
    def _parse_struct_fields(self, field_index: int, field_count: int) -> dict[str, GFFField]:
        """Parse fields for a structure"""
        fields = {}
        
        if field_count == 1:
            # Single field - field_index is the field index directly
            field = self._parse_field(field_index)
            if field:
                fields[field.label] = field
        elif field_count > 1:
            # Multiple fields - field_index points to field indices array
            indices_offset = self._field_indices_offset + (field_index * 4)
            
            for i in range(field_count):
                index = struct.unpack_from('<I', self._data, indices_offset + (i * 4))[0]
                field = self._parse_field(index)
                if field:
                    fields[field.label] = field
        
        return fields
    
    def _parse_field(self, field_index: int) -> GFFField | None:
        """Parse a single field"""
        self._offset = self._fields_offset + (field_index * 12)  # Each field is 12 bytes
        
        field_type_val = self._read_dword()
        label_index = self._read_dword()
        data_or_offset = self._read_dword()
        
        field_type = GFFFieldType(field_type_val) if field_type_val <= 17 else GFFFieldType.BYTE
        label = self._labels[label_index] if label_index < len(self._labels) else f"UNKNOWN_{label_index}"
        
        # Read the actual value based on type
        value = self._read_field_value(field_type, data_or_offset)
        
        return GFFField(label=label, field_type=field_type, value=value)
    
    def _read_field_value(self, field_type: GFFFieldType, data_or_offset: int) -> Any:
        """Read field value based on type"""
        
        if field_type == GFFFieldType.BYTE:
            # Simple value stored in data_or_offset (low byte)
            return data_or_offset & 0xFF
        
        elif field_type == GFFFieldType.CHAR:
            # Signed char stored in data_or_offset
            value = data_or_offset & 0xFF
            if value > 127:
                value -= 256
            return value
        
        elif field_type == GFFFieldType.WORD:
            # 2-byte value stored in data_or_offset (low word)
            return data_or_offset & 0xFFFF
        
        elif field_type == GFFFieldType.SHORT:
            # Signed short stored in data_or_offset
            value = data_or_offset & 0xFFFF
            if value > 32767:
                value -= 65536
            return value
        
        elif field_type == GFFFieldType.DWORD:
            # 4-byte value stored in data_or_offset
            return data_or_offset
        
        elif field_type == GFFFieldType.INT:
            # Signed int stored in data_or_offset
            if data_or_offset > 2147483647:
                data_or_offset -= 4294967296
            return data_or_offset
        
        elif field_type == GFFFieldType.FLOAT:
            # Float stored in data_or_offset (raw bits)
            return struct.unpack('<f', struct.pack('<I', data_or_offset))[0]
        
        elif field_type in [GFFFieldType.DWORD64, GFFFieldType.INT64, GFFFieldType.DOUBLE,
                           GFFFieldType.CEXOSTRING, GFFFieldType.RESREF, GFFFieldType.CEXOLocString,
                           GFFFieldType.VOID]:
            # Complex types - data_or_offset is offset into field data
            return self._read_complex_field(field_type, data_or_offset)
        
        elif field_type == GFFFieldType.STRUCT:
            # Nested structure - data_or_offset is struct index
            return data_or_offset
        
        elif field_type == GFFFieldType.LIST:
            # List - data_or_offset is offset into list indices
            return self._read_list(data_or_offset)
        
        elif field_type == GFFFieldType.VECTOR:
            # Vector - stored in field data
            return self._read_complex_field(field_type, data_or_offset)
        
        elif field_type == GFFFieldType.ORIENTATION:
            # Orientation - stored in field data
            return self._read_complex_field(field_type, data_or_offset)
        
        return None
    
    def _read_complex_field(self, field_type: GFFFieldType, offset: int) -> Any:
        """Read complex field types from field data section"""
        self._offset = self._field_data_offset + offset
        
        if field_type == GFFFieldType.DWORD64:
            return self._read_dword64()
        
        elif field_type == GFFFieldType.INT64:
            return self._read_int64()
        
        elif field_type == GFFFieldType.DOUBLE:
            return self._read_double()
        
        elif field_type == GFFFieldType.CEXOSTRING:
            # CExoString: 4-byte length + string (not null-terminated)
            length = self._read_dword()
            return self._read_string(length)
        
        elif field_type == GFFFieldType.RESREF:
            # ResRef: 1-byte length + string
            return self._read_resref()
        
        elif field_type == GFFFieldType.CEXOLocString:
            # CExoLocString: complex localization string
            return self._read_loc_string()
        
        elif field_type == GFFFieldType.VOID:
            # Void: 4-byte length + raw bytes
            length = self._read_dword()
            return self._data[self._offset:self._offset + length]
        
        elif field_type == GFFFieldType.VECTOR:
            # Vector: 3 floats (12 bytes)
            return self._read_vector()
        
        elif field_type == GFFFieldType.ORIENTATION:
            # Orientation: 4 floats (16 bytes)
            return self._read_orientation()
        
        return None
    
    def _read_loc_string(self) -> dict[str, Any]:
        """Read a CExoLocString structure"""
        # Format: 4-byte total length, 4-byte string_ref, 4-byte string_count
        # Followed by string entries
        total_length = self._read_dword()
        string_ref = self._read_dword()
        string_count = self._read_dword()
        
        strings = {}
        for _ in range(string_count):
            lang_id = self._read_dword()
            str_len = self._read_dword()
            lang_str = self._read_string(str_len)
            strings[lang_id] = lang_str
        
        return {
            'string_ref': string_ref,
            'strings': strings
        }
    
    def _read_list(self, offset: int) -> list[int]:
        """Read a list of struct indices"""
        self._offset = self._list_indices_offset + offset
        
        # First 4 bytes is the count
        count = self._read_dword()
        
        # Read the indices
        indices = []
        for _ in range(count):
            indices.append(self._read_dword())
        
        return indices


# Convenience function for reading GFF files
def read_gff(file_path: Path) -> GFFFile | None:
    """Read a GFF file and return its contents"""
    reader = GFFReader()
    return reader.read_file(file_path)


def read_gff_bytes(data: bytes) -> GFFFile | None:
    """Read GFF data from bytes"""
    reader = GFFReader()
    return reader.read_bytes(data)
