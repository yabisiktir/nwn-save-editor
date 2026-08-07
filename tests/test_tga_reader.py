"""
Tests for TGA image file reader
"""
from pathlib import Path

import pytest

from nwnfile.formats.tga_reader import TGAImage, TGAReader


@pytest.mark.unit
class TestTgaReader:
    """Test TGA file reading functionality"""
    
    def test_reader_initialization(self):
        """Test TGAReader can be created"""
        reader = TGAReader()
        assert reader is not None
    
    def test_read_nonexistent_file(self):
        """Test reading a file that doesn't exist"""
        reader = TGAReader()
        result = reader.read_file(Path("/nonexistent/file.tga"))
        assert result is None
    
    def test_parse_minimal_tga(self, temp_dir):
        """Test parsing a minimal valid TGA file"""
        test_file = temp_dir / "minimal.tga"
        
        # TGA Header for 2x2 24-bit uncompressed
        header = bytearray(18)
        header[2] = 2  # Uncompressed true-color
        header[12] = 2 & 0xFF   # Width low
        header[13] = 0          # Width high
        header[14] = 2 & 0xFF   # Height low
        header[15] = 0          # Height high
        header[16] = 24         # Bits per pixel
        header[17] = 0          # Image descriptor
        
        # Pixel data (BGR format) - 4 pixels * 3 bytes = 12 bytes
        pixels = bytes([
            255, 0, 0,    # Blue (BGR)
            0, 255, 0,    # Green
            0, 0, 255,    # Red
            255, 255, 255 # White
        ])
        
        data = bytes(header) + pixels
        test_file.write_bytes(data)
        
        reader = TGAReader()
        result = reader.read_file(test_file)
        
        assert result is not None
        assert isinstance(result, TGAImage)
        assert result.width == 2
        assert result.height == 2
        assert result.has_alpha is False
    


@pytest.mark.unit
class TestTGAImage:
    """Test TGAImage data class"""
    
    def test_tga_image_creation(self):
        """Test TGAImage can be created"""
        # Create raw RGBA pixel data for 64x64 image
        pixel_data = bytes([255, 0, 0, 255] * (64 * 64))  # Red pixels with alpha
        
        image = TGAImage(
            width=64,
            height=64,
            pixel_data=pixel_data,
            has_alpha=True
        )
        
        assert image.width == 64
        assert image.height == 64
        assert image.has_alpha is True
        assert len(image.pixel_data) == 64 * 64 * 4  # RGBA = 4 bytes per pixel




@pytest.mark.integration
class TestTGAIntegration:
    """Integration tests for TGA reader"""
    
    def test_read_32bit_tga(self, temp_dir):
        """Test reading 32-bit TGA with alpha"""
        test_file = temp_dir / "test32.tga"
        
        # TGA Header for 1x1 32-bit
        header = bytearray(18)
        header[2] = 2  # Uncompressed true-color
        header[12] = 1  # Width
        header[14] = 1  # Height
        header[16] = 32 # Bits per pixel
        header[17] = 8  # 8 bits alpha
        
        # 32-bit pixel (BGRA)
        pixel = bytes([255, 128, 64, 200])  # BGRA
        
        data = bytes(header) + pixel
        test_file.write_bytes(data)
        
        reader = TGAReader()
        result = reader.read_file(test_file)
        
        assert result is not None
        assert result.has_alpha is True
        
        # Test RGBA conversion
        rgba_data = result.to_rgba()
        assert len(rgba_data) == 4  # 1 pixel * 4 bytes


# --------------------------------------------------------------------------- #
# Header-only size read
# --------------------------------------------------------------------------- #
def _tga_header(width: int, height: int) -> bytes:
    """An 18-byte TGA header for an uncompressed 24-bit image of this size."""
    header = bytearray(18)
    header[2] = 2  # uncompressed true-colour
    header[12] = width & 0xFF
    header[13] = width >> 8
    header[14] = height & 0xFF
    header[15] = height >> 8
    header[16] = 24
    return bytes(header)


def test_read_tga_size_reads_only_the_header(tmp_path):
    """Dimensions without decoding: validating a folder of portraits needs it."""
    from nwnfile.formats.tga_reader import read_tga_size

    path = tmp_path / "po_heroh.tga"
    path.write_bytes(_tga_header(256, 512) + bytes(256 * 512 * 3))
    assert read_tga_size(path) == (256, 512)


def test_read_tga_size_does_not_read_the_pixels(tmp_path):
    # A header that claims a big image, with no pixel data behind it. Decoding
    # would fail; reading the size must not, because the caller only wants the
    # dimensions and the file may be large.
    from nwnfile.formats.tga_reader import read_tga_size

    path = tmp_path / "truncated.tga"
    path.write_bytes(_tga_header(256, 512))
    assert read_tga_size(path) == (256, 512)


def test_read_tga_size_rejects_a_file_too_short_to_be_a_tga(tmp_path):
    from nwnfile.formats.tga_reader import read_tga_size

    path = tmp_path / "stub.tga"
    path.write_bytes(b"nope")
    with pytest.raises(ValueError):
        read_tga_size(path)
