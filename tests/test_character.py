"""Tests for the character summary + discovery layer (game/character.py)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from vaultkeeper.core.formats.bic_reader import (
    CharacterClass,
    CharacterInfo,
    Gender,
    Race,
)
from vaultkeeper.game.character import (
    alignment_title,
    character_summary,
    class_name,
    level_summary,
    portrait_filename,
    race_name,
    resolve_portrait,
    scan_character_files,
)


def _info(**kw) -> CharacterInfo:
    base = dict(
        name="Morcan Fae",
        gender=Gender.MALE,
        race=Race.HUMAN,
        classes=[(CharacterClass.BARD, 8), (CharacterClass.RED_DRAGON_DISCIPLE, 10)],
        level=18,
        experience=171_000,
        alignment_good_evil=100,
        alignment_lawful_chaotic=100,
        hit_points=140,
        portrait_resref="po_hu_m_99_",
    )
    base.update(kw)
    return CharacterInfo(**base)


class TestNameTables:
    def test_race_and_class_use_vb_display_names(self):
        assert race_name(Race.HALF_ELF) == "Half-Elf"  # not "Half Elf"
        assert class_name(CharacterClass.CHAMPION_OF_TORM) == "Champion of Torm"
        assert class_name(CharacterClass.RED_DRAGON_DISCIPLE) == "Red Dragon Disciple"

    def test_alignment_title_corner_only(self):
        # Args are (lawful_chaotic, good_evil).
        assert alignment_title(100, 100) == "Crusader"
        assert alignment_title(0, 0) == "Destroyer"
        assert alignment_title(100, 50) == "Judge"  # lawful, neutral-good
        assert alignment_title(50, 100) == "Benefactor"  # neutral-law, good
        # Non-corner alignments have no title.
        assert alignment_title(85, 15) == ""


class TestSummary:
    def test_layout_and_fields(self):
        text = character_summary(_info(), updated=datetime(2024, 3, 1, 14, 30))
        # Header: name the Title (level)
        assert text.splitlines()[0] == "Morcan Fae the Crusader (18)"
        assert "Male Human, Lawful (100), Good (100)" in text
        assert "Bard (8)" in text
        assert "Red Dragon Disciple (10)" in text
        assert "Experience: 171,000" in text
        assert "Hit Points: 140" in text
        assert "Portrait: po_hu_m_99_" in text
        assert "Updated: 01 Mar 2024 14:30" in text

    def test_next_level_countdown(self):
        # level 8 threshold is LEVEL_XP[8] = 36000; xp 30000 -> 6000 to go.
        text = character_summary(_info(level=8, experience=30_000))
        assert "Next Level Countdown: 6,000" in text

    def test_countdown_none_when_reached(self):
        text = character_summary(_info(level=8, experience=40_000))
        assert "Next Level Countdown: None" in text

    def test_level_40_has_no_countdown(self):
        text = character_summary(_info(level=40, experience=2_000_000))
        assert "Next Level Countdown" not in text

    def test_alignment_words(self):
        text = character_summary(
            _info(alignment_lawful_chaotic=10, alignment_good_evil=20)
        )
        assert "Chaotic (10), Evil (20)" in text

    def test_neutral_words(self):
        text = character_summary(
            _info(alignment_lawful_chaotic=50, alignment_good_evil=50)
        )
        assert "Neutral (50), Neutral (50)" in text

    def test_invalid_info_returns_default_and_error(self):
        bad = CharacterInfo(
            name="",
            gender=Gender.MALE,
            race=Race.HUMAN,
            classes=[],
            level=1,
            experience=0,
            alignment_good_evil=50,
            alignment_lawful_chaotic=50,
            hit_points=10,
            is_valid=False,
            error_message="boom",
        )
        text = character_summary(bad, default_value="player.bic")
        assert text == "player.bic\n\nboom"

    def test_level_summary_line(self):
        assert level_summary(_info()) == "Level 18 (Bard 8, Red Dragon Disciple 10)"


class TestPortraitResolution:
    def test_filename_format(self):
        assert portrait_filename("po_hu_m_99_", "m") == "po_hu_m_99_m.tga"

    def test_resolves_requested_size_in_priority_order(self, tmp_path):
        # NWN resrefs carry their trailing separator; size is concatenated directly.
        low = tmp_path / "override"
        high = tmp_path / "portraits"
        low.mkdir()
        high.mkdir()
        (high / "hero_m.tga").write_bytes(b"TGA")
        (low / "hero_m.tga").write_bytes(b"TGA")
        # First folder in the list wins.
        assert resolve_portrait("hero_", [low, high], "m") == low / "hero_m.tga"

    def test_falls_back_to_other_size(self, tmp_path):
        (tmp_path / "hero_h.tga").write_bytes(b"TGA")  # only huge on disk
        assert resolve_portrait("hero_", [tmp_path], "m") == tmp_path / "hero_h.tga"

    def test_missing_returns_none(self, tmp_path):
        assert resolve_portrait("ghost", [tmp_path], "m") is None
        assert resolve_portrait("", [tmp_path], "m") is None


class TestDiscovery:
    def test_scan_empty_or_missing(self, tmp_path):
        assert scan_character_files(tmp_path / "nope") == []
        assert scan_character_files(tmp_path) == []

    def test_scan_ignores_non_bic(self, tmp_path):
        (tmp_path / "notes.txt").write_bytes(b"x")
        assert scan_character_files(tmp_path) == []


# Real character files on the developer's machine (localvault + quicksave).
_LOCALVAULT = Path.home() / "Documents" / "Neverwinter Nights" / "localvault"


@pytest.mark.integration
@pytest.mark.skipif(not _LOCALVAULT.is_dir(), reason="No local NWN vault on this box")
class TestRealCharacters:
    def test_scan_localvault_summaries(self):
        found = scan_character_files(_LOCALVAULT)
        assert found, "expected at least one .bic in the local vault"
        # Every discovered character produces a non-empty summary; at least one
        # parses to a real (valid) character with a name and a class.
        assert all(cf.summary() for cf in found)
        valid = [cf for cf in found if cf.info.is_valid]
        assert valid
        sample = valid[0]
        assert sample.display_name
        text = sample.summary()
        assert "Portrait:" in text and "Hit Points:" in text
