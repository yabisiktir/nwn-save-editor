"""
TGA (Targa) Image Reader
Ported from VB.NET for NWN portrait support

NWN uses TGA format for portraits with the following conventions:
- Filename format: <resref><size>.tga
  - h = huge   (256x512)
  - l = large  (128x256)
  - m = medium  (64x128)
  - s = small   (32x64)
  - t = tiny    (16x32)

Portraits are twice as tall as they are wide; the sizes above are the ones the
game requires, from the original tool's ``Defs.PortraitInfo``. (They were listed
here as squares — 256x256 and so on — which no NWN portrait has ever been.)
"""

import struct
from dataclasses import dataclass
from pathlib import Path

from nwnfile.log import get_logger

logger = get_logger(__name__)


@dataclass
class TGAImage:
    """Decoded TGA image data.

    UI-agnostic: :meth:`to_rgba` yields raw 32-bit RGBA bytes that the UI layer
    turns into a ``QImage`` (that conversion lives in the UI, not here, so this
    module stays free of any Qt dependency and is testable headless).
    """
    width: int
    height: int
    pixel_data: bytes  # RGB or RGBA raw bytes
    has_alpha: bool

    def to_rgba(self) -> bytes:
        """Convert pixel data to 32-bit RGBA (adds opaque alpha for RGB input)."""
        if self.has_alpha:
            return self.pixel_data
        else:
            # Convert RGB to RGBA (add full alpha)
            rgba = bytearray()
            for i in range(0, len(self.pixel_data), 3):
                r = self.pixel_data[i]
                g = self.pixel_data[i + 1]
                b = self.pixel_data[i + 2]
                rgba.extend([r, g, b, 255])  # Add full alpha
            return bytes(rgba)


def read_tga_size(path: Path) -> tuple[int, int]:
    """``(width, height)`` from a TGA's header, without decoding the image.

    The header is 18 bytes and carries the dimensions at offsets 12-15, so this
    reads 18 bytes rather than the whole file. That matters when the caller is
    checking a folder of portraits: validating a thousand images by decoding each
    one is slow enough to need a progress dialog, which is why the original tool
    ran it on a background worker.

    Raises ``OSError`` if the file cannot be read, ``ValueError`` if it is too
    short to be a TGA.
    """
    with path.open("rb") as handle:
        header = handle.read(18)
    if len(header) < 18:
        raise ValueError(f"{path.name} is too short to be a TGA file")
    width, height = struct.unpack_from("<HH", header, 12)
    return width, height


class TGAReader:
    """Reader for TGA (Targa) image files"""
    
    # TGA Image Types
    TYPE_NO_IMAGE = 0
    TYPE_COLOR_MAPPED = 1
    TYPE_TRUE_COLOR = 2
    TYPE_GRAYSCALE = 3
    TYPE_RLE_COLOR_MAPPED = 9
    TYPE_RLE_TRUE_COLOR = 10
    TYPE_RLE_GRAYSCALE = 11
    
    def __init__(self):
        self._data: bytes = b""
        self._offset: int = 0
    
    def read_file(self, file_path: Path) -> TGAImage | None:
        """Read a TGA file and return TGAImage"""
        try:
            with open(file_path, 'rb') as f:
                self._data = f.read()
            self._offset = 0
            
            return self._parse_tga()
        except Exception as e:
            logger.error(f"Error reading TGA file {file_path}: {e}")
            return None
    
    def read_bytes(self, data: bytes) -> TGAImage | None:
        """Read TGA data from bytes"""
        self._data = data
        self._offset = 0
        return self._parse_tga()
    
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
    
    def _parse_tga(self) -> TGAImage | None:
        """Parse TGA file structure"""
        if len(self._data) < 18:  # Minimum TGA header size
            logger.error("File too small to be a valid TGA file")
            return None
        
        # Read header
        id_length = self._read_byte()          # 0: ID length
        color_map_type = self._read_byte()     # 1: Color map type
        image_type = self._read_byte()         # 2: Image type
        
        # Color map specification (5 bytes)
        color_map_origin = self._read_word()   # 3-4: First entry index
        color_map_length = self._read_word()   # 5-6: Color map length
        color_map_entry_size = self._read_byte()  # 7: Color map entry size
        
        # Image specification (10 bytes)
        x_origin = self._read_word()           # 8-9: X origin
        y_origin = self._read_word()           # 10-11: Y origin
        width = self._read_word()              # 12-13: Width
        height = self._read_word()             # 14-15: Height
        pixel_depth = self._read_byte()        # 16: Pixel depth (bits per pixel)
        image_descriptor = self._read_byte()   # 17: Image descriptor
        
        # Skip ID field if present
        if id_length > 0:
            self._offset += id_length
        
        # Skip color map if present
        if color_map_type == 1:
            color_map_size = color_map_length * (color_map_entry_size // 8)
            self._offset += color_map_size
        
        # Read pixel data based on image type
        if image_type == self.TYPE_TRUE_COLOR:
            pixel_data = self._read_uncompressed_rgb(width, height, pixel_depth)
        elif image_type == self.TYPE_RLE_TRUE_COLOR:
            pixel_data = self._read_rle_rgb(width, height, pixel_depth)
        elif image_type == self.TYPE_GRAYSCALE:
            pixel_data = self._read_uncompressed_grayscale(width, height, pixel_depth)
        elif image_type == self.TYPE_RLE_GRAYSCALE:
            pixel_data = self._read_rle_grayscale(width, height, pixel_depth)
        else:
            logger.warning(f"Unsupported TGA image type: {image_type}")
            return None
        
        if pixel_data is None:
            return None
        
        # Check if image is flipped (bit 5 of image descriptor)
        is_flipped = not (image_descriptor & 0x20)
        if is_flipped:
            pixel_data = self._flip_vertical(pixel_data, width, height, pixel_depth // 8)
        
        has_alpha = pixel_depth == 32
        
        return TGAImage(
            width=width,
            height=height,
            pixel_data=pixel_data,
            has_alpha=has_alpha
        )
    
    def _read_uncompressed_rgb(self, width: int, height: int, pixel_depth: int) -> bytes | None:
        """Read uncompressed RGB/RGBA data"""
        bytes_per_pixel = pixel_depth // 8
        expected_size = width * height * bytes_per_pixel
        
        if len(self._data) - self._offset < expected_size:
            logger.error("TGA file truncated")
            return None
        
        pixel_data = self._data[self._offset:self._offset + expected_size]
        
        # TGA stores as BGR(A), convert to RGB(A)
        rgba_data = bytearray()
        for i in range(0, len(pixel_data), bytes_per_pixel):
            b = pixel_data[i]
            g = pixel_data[i + 1]
            r = pixel_data[i + 2]
            if bytes_per_pixel == 4:
                a = pixel_data[i + 3]
                rgba_data.extend([r, g, b, a])
            else:
                rgba_data.extend([r, g, b])
        
        return bytes(rgba_data)
    
    def _read_rle_rgb(self, width: int, height: int, pixel_depth: int) -> bytes | None:
        """Read RLE-compressed RGB/RGBA data"""
        bytes_per_pixel = pixel_depth // 8
        rgba_data = bytearray()
        
        pixels_read = 0
        total_pixels = width * height
        
        while pixels_read < total_pixels and self._offset < len(self._data):
            header = self._read_byte()
            
            if header & 0x80:  # Run-length packet
                count = (header & 0x7F) + 1
                
                # Read the pixel to repeat
                pixel = self._data[self._offset:self._offset + bytes_per_pixel]
                self._offset += bytes_per_pixel
                
                b, g, r = pixel[0], pixel[1], pixel[2]
                a = pixel[3] if bytes_per_pixel == 4 else 255
                
                for _ in range(count):
                    rgba_data.extend([r, g, b, a])
                    pixels_read += 1
                    if pixels_read >= total_pixels:
                        break
            else:  # Raw packet
                count = (header & 0x7F) + 1
                
                for _ in range(count):
                    if self._offset + bytes_per_pixel > len(self._data):
                        break
                    
                    pixel = self._data[self._offset:self._offset + bytes_per_pixel]
                    self._offset += bytes_per_pixel
                    
                    b, g, r = pixel[0], pixel[1], pixel[2]
                    a = pixel[3] if bytes_per_pixel == 4 else 255
                    
                    rgba_data.extend([r, g, b, a])
                    pixels_read += 1
                    if pixels_read >= total_pixels:
                        break
        
        return bytes(rgba_data)
    
    def _read_uncompressed_grayscale(self, width: int, height: int, pixel_depth: int) -> bytes:
        """Read uncompressed grayscale data"""
        bytes_per_pixel = pixel_depth // 8
        expected_size = width * height * bytes_per_pixel
        
        pixel_data = self._data[self._offset:self._offset + expected_size]
        self._offset += expected_size
        
        # Convert grayscale to RGB
        rgba_data = bytearray()
        for i in range(0, len(pixel_data), bytes_per_pixel):
            gray = pixel_data[i]
            if bytes_per_pixel == 2:
                a = pixel_data[i + 1]
            else:
                a = 255
            rgba_data.extend([gray, gray, gray, a])
        
        return bytes(rgba_data)
    
    def _read_rle_grayscale(self, width: int, height: int, pixel_depth: int) -> bytes:
        """Read RLE-compressed grayscale data"""
        bytes_per_pixel = pixel_depth // 8
        rgba_data = bytearray()
        
        pixels_read = 0
        total_pixels = width * height
        
        while pixels_read < total_pixels and self._offset < len(self._data):
            header = self._read_byte()
            
            if header & 0x80:  # Run-length packet
                count = (header & 0x7F) + 1
                gray = self._read_byte()
                a = self._read_byte() if bytes_per_pixel == 2 else 255
                
                for _ in range(count):
                    rgba_data.extend([gray, gray, gray, a])
                    pixels_read += 1
                    if pixels_read >= total_pixels:
                        break
            else:  # Raw packet
                count = (header & 0x7F) + 1
                
                for _ in range(count):
                    gray = self._read_byte()
                    a = self._read_byte() if bytes_per_pixel == 2 else 255
                    rgba_data.extend([gray, gray, gray, a])
                    pixels_read += 1
                    if pixels_read >= total_pixels:
                        break
        
        return bytes(rgba_data)
    
    def _flip_vertical(self, pixel_data: bytes, width: int, height: int, bytes_per_pixel: int) -> bytes:
        """Flip image vertically (TGA default is bottom-up)"""
        row_size = width * bytes_per_pixel
        flipped = bytearray()
        
        for y in range(height - 1, -1, -1):
            row_start = y * row_size
            flipped.extend(pixel_data[row_start:row_start + row_size])
        
        return bytes(flipped)


class PortraitManager:
    """Manager for NWN character portraits"""
    
    PORTRAIT_SIZES = {
        't': (32, 32),    # tiny
        's': (64, 64),    # small
        'm': (96, 96),    # medium
        'l': (128, 128),  # large
        'h': (256, 256),  # huge
    }
    
    def __init__(self):
        self._reader = TGAReader()
        self._portrait_cache: dict = {}
    
    def find_portrait(self, resref: str, size: str = 'm', portraits_path: Path | None = None) -> Path | None:
        """Find portrait file by resref and size.

        ``portraits_path`` must be supplied by the caller (the UI/domain layer
        resolves the game's portraits directory); this module does not reach into
        global path state.
        """
        if not portraits_path or not portraits_path.exists():
            return None
        
        # NWN portrait naming: <resref><size>.tga
        portrait_file = portraits_path / f"{resref}{size}.tga"
        
        if portrait_file.exists():
            return portrait_file
        
        # Try lowercase
        portrait_file = portraits_path / f"{resref.lower()}{size}.tga"
        if portrait_file.exists():
            return portrait_file
        
        return None
    
    def load_portrait(self, resref: str, size: str = 'm', portraits_path: Path | None = None) -> TGAImage | None:
        """Load a portrait by resref"""
        # Check cache
        cache_key = f"{resref}_{size}"
        if cache_key in self._portrait_cache:
            return self._portrait_cache[cache_key]
        
        portrait_file = self.find_portrait(resref, size, portraits_path)
        if not portrait_file:
            return None
        
        tga_image = self._reader.read_file(portrait_file)
        if tga_image:
            self._portrait_cache[cache_key] = tga_image
        
        return tga_image
    
    # NOTE: QPixmap conversion for display lives in the UI layer (Phase 7 Portrait
    # Manager), which consumes TGAImage.to_rgba(). Keeping it out of nwnfile
    # preserves this module's Qt-free, headless-testable property.

    def scan_available_portraits(self, portraits_path: Path | None = None) -> list[tuple[str, str]]:
        """Scan a directory for all available portraits (resref, size-code)."""
        if not portraits_path or not portraits_path.exists():
            return []
        
        portraits = []
        for tga_file in portraits_path.glob("*.tga"):
            name = tga_file.stem
            # Extract resref and size from filename
            if len(name) >= 2:
                size_code = name[-1].lower()
                resref = name[:-1]
                if size_code in self.PORTRAIT_SIZES:
                    portraits.append((resref, size_code))
        
        return portraits


def read_tga(file_path: Path) -> TGAImage | None:
    """Convenience function to read a TGA file"""
    reader = TGAReader()
    return reader.read_file(file_path)
