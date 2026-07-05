"""
ERF file format reader for Neverwinter Nights modules
Ported from VB.NET ErfFileReader.vb
"""

import struct
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from vaultkeeper.core.log import get_logger

logger = get_logger(__name__)


class ErfType(Enum):
    """ERF file type"""
    ERF = "ERF "
    MOD = "MOD "
    HAK = "HAK "
    ERF_V10 = "ERF V1.0"
    MOD_V10 = "MOD V1.0"
    HAK_V10 = "HAK V1.0"


@dataclass
class ErfResource:
    """Represents a resource within an ERF file"""
    filename: str
    resource_id: str
    offset: int
    size: int
    file_type: str


@dataclass
class ErfFileInfo:
    """Information extracted from an ERF file"""
    filename: str
    file_type: ErfType
    description: str
    save_name: str
    resources: list[ErfResource]
    localized_strings: dict[int, str]
    is_valid: bool = True
    error_message: str = ""


class ErfFileReader:
    """Reader for NWN ERF/HAK/MOD files"""
    
    # Module data dictionary for known modules
    MODULE_DATA: dict[str, tuple[str, str]] = {}
    
    BUFFER_SIZE = 8192
    RESOURCE_ELEMENT_SIZE = 8  # 4 bytes offset + 4 bytes size
    
    def __init__(self):
        self._load_module_data()
    
    def _load_module_data(self):
        """Load module data from file if available"""
        # TODO: Load from external data file
        # For now, this is a placeholder for the VB.NET ModuleData dictionary
        pass
    
    def read_file(self, file_path: Path) -> ErfFileInfo | None:
        """
        Read an ERF file and extract its information
        
        Args:
            file_path: Path to the ERF file
            
        Returns:
            ErfFileInfo with extracted data, or None if error
        """
        if not file_path.exists():
            logger.error(f"ERF file does not exist: {file_path}")
            return None
        
        try:
            with open(file_path, 'rb') as f:
                return self._parse_erf(f, file_path)
        except Exception as e:
            logger.error(f"Error reading ERF file {file_path}: {e}")
            return ErfFileInfo(
                filename=str(file_path),
                file_type=ErfType.ERF,
                description="",
                save_name="",
                resources=[],
                localized_strings={},
                is_valid=False,
                error_message=str(e)
            )
    
    def _parse_erf(self, file, file_path: Path) -> ErfFileInfo:
        """Parse ERF file structure"""
        try:
            # Read header
            file_type = self._read_string(file, 4)
            version = self._read_string(file, 4)
            
            # Determine ERF type
            erf_type = self._determine_erf_type(file_type, version)
            
            # Read localization info
            loc_string_count = self._read_int32(file)
            loc_string_size = self._read_int32(file)
            entry_count = self._read_int32(file)
            
            loc_string_offset = self._read_int32(file)
            keys_offset = self._read_int32(file)
            resource_offset = self._read_int32(file)
            
            # Read localized strings if present
            localized_strings = {}
            if loc_string_count > 0 and loc_string_size > 0:
                current_pos = file.tell()
                file.seek(loc_string_offset)
                localized_strings = self._read_localized_strings(file, loc_string_count)
                file.seek(current_pos)
            
            # Read resource entries
            resources = []
            if entry_count > 0:
                current_pos = file.tell()
                file.seek(keys_offset)
                
                for _ in range(entry_count):
                    resource = self._read_resource_entry(file, resource_offset)
                    if resource:
                        resources.append(resource)
                        resource_offset += self.RESOURCE_ELEMENT_SIZE
                
                file.seek(current_pos)
            
            # Extract description from localized strings
            description = localized_strings.get(0, "")
            if not description:
                description = self.MODULE_DATA.get(file_path.name, ("", ""))[1]
            
            # Get save name from module data
            save_name = self.MODULE_DATA.get(file_path.name, ("", ""))[0]
            
            return ErfFileInfo(
                filename=str(file_path),
                file_type=erf_type,
                description=description,
                save_name=save_name,
                resources=resources,
                localized_strings=localized_strings,
                is_valid=True
            )
            
        except Exception as e:
            logger.error(f"Error parsing ERF file: {e}")
            raise
    
    def _determine_erf_type(self, file_type: str, version: str) -> ErfType:
        """Determine ERF type from header"""
        type_map = {
            "ERF ": ErfType.ERF,
            "MOD ": ErfType.MOD,
            "HAK ": ErfType.HAK,
        }
        
        if file_type in type_map:
            return type_map[file_type]
        
        # Try version-based detection
        if "V1.0" in version:
            if file_type == "ERF":
                return ErfType.ERF_V10
            elif file_type == "MOD":
                return ErfType.MOD_V10
            elif file_type == "HAK":
                return ErfType.HAK_V10
        
        return ErfType.ERF  # Default
    
    def _read_localized_strings(self, file, count: int) -> dict[int, str]:
        """Read localized strings from ERF file"""
        strings = {}
        for i in range(count):
            string_id = self._read_int32(file)
            string_length = self._read_int32(file)
            if string_length > 0:
                string_data = file.read(string_length)
                try:
                    strings[string_id] = string_data.decode('utf-16-le')
                except UnicodeDecodeError:
                    strings[string_id] = string_data.decode('utf-8', errors='ignore')
        return strings
    
    def _read_resource_entry(self, file, base_offset: int) -> ErfResource | None:
        """Read a single resource entry"""
        try:
            # Read resource name (16 chars, null-padded)
            name_bytes = file.read(16)
            filename = name_bytes.rstrip(b'\x00').decode('ascii', errors='ignore')
            
            # Read resource ID (4 chars)
            id_bytes = file.read(4)
            resource_id = id_bytes.decode('ascii', errors='ignore')
            
            # Read resource type (2 chars)
            type_bytes = file.read(2)
            file_type = type_bytes.decode('ascii', errors='ignore')
            
            # Skip reserved field (2 bytes)
            file.read(2)
            
            # Read offset and size from resource table
            current_pos = file.tell()
            offset = base_offset
            size = 0
            
            return ErfResource(
                filename=filename,
                resource_id=resource_id,
                offset=offset,
                size=size,
                file_type=file_type
            )
            
        except Exception as e:
            logger.error(f"Error reading resource entry: {e}")
            return None
    
    def _read_string(self, file, length: int) -> str:
        """Read a string of fixed length"""
        data = file.read(length)
        return data.decode('ascii', errors='ignore')
    
    def _read_int32(self, file) -> int:
        """Read a 32-bit integer"""
        data = file.read(4)
        return struct.unpack('<I', data)[0]
    
    def extract_resource(self, erf_path: Path, resource: ErfResource, output_path: Path) -> bool:
        """
        Extract a single resource from an ERF file
        
        Args:
            erf_path: Path to the ERF file
            resource: Resource information
            output_path: Where to save the extracted file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with open(erf_path, 'rb') as f:
                f.seek(resource.offset)
                data = f.read(resource.size)
                
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as out:
                    out.write(data)
                
                return True
        except Exception as e:
            logger.error(f"Error extracting resource {resource.filename}: {e}")
            return False
    
    def find_resource(self, erf_path: Path, filename: str) -> ErfResource | None:
        """
        Find a resource in an ERF file by filename.
        
        Args:
            erf_path: Path to the ERF file
            filename: Name of the resource to find
            
        Returns:
            ErfResource if found, None otherwise
        """
        file_info = self.read_file(erf_path)
        if not file_info or not file_info.is_valid:
            return None
        
        # Normalize filename for comparison
        target_name = filename.lower()
        
        for resource in file_info.resources:
            if resource.filename.lower() == target_name:
                return resource
            # Also try matching without extension
            if resource.filename.lower().rsplit('.', 1)[0] == target_name.rsplit('.', 1)[0]:
                return resource
        
        return None
    
    def extract_all_resources(self, erf_path: Path, output_dir: Path) -> list[Path]:
        """
        Extract all resources from an ERF file
        
        Args:
            erf_path: Path to the ERF file
            output_dir: Directory to save extracted files
            
        Returns:
            List of extracted file paths
        """
        file_info = self.read_file(erf_path)
        if not file_info or not file_info.is_valid:
            return []
        
        extracted = []
        for resource in file_info.resources:
            output_path = output_dir / resource.filename
            if self.extract_resource(erf_path, resource, output_path):
                extracted.append(output_path)
        
        return extracted
    
    def extract_file_by_name(self, erf_path: Path, filename: str, output_path: Path) -> bool:
        """
        Extract a specific file from an ERF archive by name.
        
        Args:
            erf_path: Path to the ERF file
            filename: Name of the file to extract
            output_path: Where to save the extracted file
            
        Returns:
            True if successful, False otherwise
        """
        resource = self.find_resource(erf_path, filename)
        if resource:
            return self.extract_resource(erf_path, resource, output_path)
        return False
