"""Tests for the character summary + discovery layer (game/character.py)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from nwnfile.character import (
    alignment_title,
    character_summary,
    class_name,
    level_summary,
    portrait_filename,
    race_name,
    resolve_portrait,
    scan_character_files,
    scan_portraits,
)
from nwnfile.formats.bic_reader import (
    CharacterClass,
    CharacterInfo,
    Gender,
    Race,
)


def _info(**kw) -> CharacterInfo:
    base = dict(
        name="Morcan Fae",
        gender=Gender.MALE,
        race_id=Race.HUMAN.value,
        classes=[
            (CharacterClass.BARD.value, 8),
            (CharacterClass.RED_DRAGON_DISCIPLE.value, 10),
        ],
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
        assert race_name(Race.HALF_ELF.value) == "Half-Elf"  # not "Half Elf"
        assert class_name(CharacterClass.CHAMPION_OF_TORM.value) == "Champion of Torm"
        assert class_name(CharacterClass.RED_DRAGON_DISCIPLE.value) == "Red Dragon Disciple"

    def test_class_name_resolves_base_then_prc_then_unknown(self):
        from nwnfile.character_reference import CharacterReference

        ref = CharacterReference(prc_class_names={43: "Binder"})
        assert class_name(1, ref) == "Bard"  # base CLASS_NAMES wins
        assert class_name(43, ref) == "Binder"  # PRC extension
        assert class_name(9999, ref) == "Class 9999"  # neither -> visible fallback

    def test_race_name_resolves_base_then_prc_then_unknown(self):
        from nwnfile.character_reference import CharacterReference

        ref = CharacterReference(prc_race_names={159: "Bralani Eladrin"})
        assert race_name(6, ref) == "Human"  # base RACE_NAMES wins
        assert race_name(159, ref) == "Bralani Eladrin"  # PRC extension
        assert race_name(9999, ref) == "Race 9999"  # neither -> visible fallback

    def test_prc_prestige_class_shows_in_summary(self):
        # A PRC prestige class id (43 = Binder) is parsed and named, not dropped as
        # VB did — it appears in the level/summary lines via the bundled PRC table.
        info = _info(classes=[(4, 20), (43, 20)], level=40)
        assert "Binder 20" in level_summary(info)
        assert "Binder (20)" in character_summary(info)

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

    def test_gold_deity_and_stats(self):
        info = _info(
            gold=139_380_743,
            deity="Corellon Larethian",
            abilities={"Str": 29, "Dex": 22, "Con": 14, "Int": 14, "Wis": 8, "Cha": 10},
        )
        # Gold + Deity always show; abilities only with show_stats.
        text = character_summary(info, show_stats=True)
        assert "Gold: 139,380,743" in text
        assert "Deity: Corellon Larethian" in text
        assert "Str: 29" in text and "Cha: 10" in text
        # Stats block omitted, and ordering matches VB (stats before Portrait).
        plain = character_summary(info)
        assert "Str:" not in plain
        assert plain.index("Gold:") < plain.index("Portrait:")

    def test_gold_none_and_no_deity(self):
        text = character_summary(_info(gold=0, deity=""))
        assert "Gold: None" in text
        assert "Deity:" not in text

    def test_character_sheet_fields_shown_with_stats(self):
        info = _info(
            subrace="Giant", age=200, armor_class=117, base_attack_bonus=27,
            save_fortitude=77, save_reflex=88, save_will=68,
            hit_points=1172, current_hit_points=352,
            biography="You remember very little of your home.",
        )
        text = character_summary(info, show_stats=True)
        assert "Human (Giant)," in text  # subrace shown next to race
        assert "Hit Points: 352 / 1,172" in text  # current / max
        assert "Age: 200" in text
        assert "Armor Class: 117" in text
        assert "Base Attack Bonus: +27" in text
        assert "Fortitude: 77, Reflex: 88, Will: 68" in text
        assert "Biography:" in text
        assert "You remember very little" in text

    def test_biography_and_combat_hidden_in_plain_summary(self):
        # The plain (filter) summary omits the biography + combat block so bio text
        # can't false-match the class filter.
        info = _info(biography="A brave fighter of the north.", armor_class=20)
        plain = character_summary(info)
        assert "Biography:" not in plain
        assert "Armor Class" not in plain

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
            race_id=Race.HUMAN.value,
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


class TestPortraitScan:
    def test_groups_sizes_by_resref(self, tmp_path):
        for size in ("t", "s", "m", "l", "h"):
            (tmp_path / f"po_hero_{size}.tga").write_bytes(b"TGA")
        (tmp_path / "po_villain_h.tga").write_bytes(b"TGA")
        (tmp_path / "notes.txt").write_bytes(b"x")  # ignored

        entries = scan_portraits([tmp_path])
        assert [e.resref for e in entries] == ["po_hero_", "po_villain_"]
        hero = entries[0]
        assert set(hero.sizes) == {"t", "s", "m", "l", "h"}
        assert hero.path("m") == tmp_path / "po_hero_m.tga"

    def test_path_falls_back_to_largest(self, tmp_path):
        (tmp_path / "po_hero_s.tga").write_bytes(b"TGA")
        entry = scan_portraits([tmp_path])[0]
        # No huge/medium on disk -> falls back to the largest available (small).
        assert entry.path("h") == tmp_path / "po_hero_s.tga"

    def test_first_folder_wins(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        (a / "po_hero_h.tga").write_bytes(b"A")
        (b / "po_hero_h.tga").write_bytes(b"B")
        entry = scan_portraits([a, b])[0]
        assert entry.path("h") == a / "po_hero_h.tga"

    def test_empty(self, tmp_path):
        assert scan_portraits([tmp_path / "nope"]) == []
