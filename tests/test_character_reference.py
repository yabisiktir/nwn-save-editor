"""Tests for the feat/skill reference tables (VB BicFileInfo GetNames/GetDescriptions)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from vaultkeeper.game.character_reference import (
    default_reference,
    load_feat_descriptions,
    load_feat_names,
    load_prc_feat_descriptions,
    load_prc_feat_names,
    load_prc_skill_names,
    load_reference,
    load_skill_descriptions,
    load_skill_names,
)


def _write_gz_json(path: Path, mapping: dict) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(mapping, fh)


def _write(dir_: Path) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    # Feat Names: line index = feat id, "Name*DescRef" (Latin-1, CRLF).
    (dir_ / "Feat Names.txt").write_bytes(
        "Alertness*290\r\nAmbidexterity*222\r\nBerserker Rage*111\r\n".encode("latin-1")
    )
    (dir_ / "Feat Descriptions.txt").write_bytes(
        "]290\r\nSpot and Listen bonus.\r\n]222\r\nOff-hand penalty removed.\r\n".encode(
            "latin-1"
        )
    )
    # Skill Names: one per line (UTF-16 with BOM), index = skill id.
    (dir_ / "Skill Names.txt").write_bytes(
        "Animal Empathy\r\nConcentration\r\nDiscipline\r\n".encode("utf-16")
    )
    (dir_ / "Skill Descriptions.txt").write_bytes(
        "]Charisma skill.\r\n]Keep casting.\r\n]Resist knockdown.\r\n".encode("latin-1")
    )
    return dir_


def test_load_feat_names_indexes_by_feat_id(tmp_path):
    names = load_feat_names(_write(tmp_path) / "Feat Names.txt")
    assert names[0] == ("Alertness", 290)
    assert names[2] == ("Berserker Rage", 111)


def test_load_feat_descriptions_keyed_by_ref(tmp_path):
    desc = load_feat_descriptions(_write(tmp_path) / "Feat Descriptions.txt")
    assert desc[290] == "Spot and Listen bonus."
    assert desc[222] == "Off-hand penalty removed."


def test_load_skill_names_utf16(tmp_path):
    names = load_skill_names(_write(tmp_path) / "Skill Names.txt")
    assert names == ["Animal Empathy", "Concentration", "Discipline"]


def test_load_skill_descriptions_indexed_by_skill_id(tmp_path):
    # No off-by-one: block i is skill i's own description.
    desc = load_skill_descriptions(_write(tmp_path) / "Skill Descriptions.txt")
    assert desc == ["Charisma skill.", "Keep casting.", "Resist knockdown."]


def test_reference_feats_dedups_and_sorts(tmp_path):
    ref = load_reference(_write(tmp_path))
    # feat ids 2, 0, 0 (duplicate), 99 (unresolved) -> named, deduped, sorted;
    # the unresolved id stays visible as "Unknown feat 99" (mirrors skills()).
    feats = ref.feats([2, 0, 0, 99])
    assert [name for name, _desc in feats] == [
        "Alertness",
        "Berserker Rage",
        "Unknown feat 99",
    ]
    # Description comes from the ref lookup; Berserker Rage (ref 111) has none.
    assert dict(feats)["Alertness"] == "Spot and Listen bonus."
    assert dict(feats)["Berserker Rage"] == "Feat description is not available."
    assert dict(feats)["Unknown feat 99"] == "Feat description is not available."


def test_load_prc_feat_names_parses_json_and_skips_non_int(tmp_path):
    path = tmp_path / "PRC Feats.json"
    path.write_text(
        '{"2213": "Divine Strike", "24730": "Aura of Despair", "bad": "skip"}',
        encoding="utf-8",
    )
    prc = load_prc_feat_names(path)
    assert prc == {2213: "Divine Strike", 24730: "Aura of Despair"}


def test_reference_resolves_prc_feats(tmp_path):
    # PRC feat ids run past the base table; they resolve via the PRC extension map.
    _write(tmp_path)
    (tmp_path / "PRC Feats.json").write_text(
        '{"2213": "Divine Strike", "7955": "Weapon Proficiency: Club"}',
        encoding="utf-8",
    )
    ref = load_reference(tmp_path)
    feats = ref.feats([7955, 2213])
    assert [name for name, _desc in feats] == [
        "Divine Strike",
        "Weapon Proficiency: Club",
    ]
    # PRC feats carry no bundled description.
    assert dict(feats)["Divine Strike"] == "Feat description is not available."


def test_load_prc_feat_descriptions_gzip_skips_non_int(tmp_path):
    path = tmp_path / "PRC Feat Descriptions.json.gz"
    _write_gz_json(path, {"2213": "Sneak the undead.", "bad": "skip"})
    assert load_prc_feat_descriptions(path) == {2213: "Sneak the undead."}


def test_reference_prc_feat_carries_description(tmp_path):
    # A PRC feat resolves to its bundled name AND its bundled description.
    _write(tmp_path)
    (tmp_path / "PRC Feats.json").write_text('{"2213": "Divine Strike"}', encoding="utf-8")
    _write_gz_json(tmp_path / "PRC Feat Descriptions.json.gz", {"2213": "Sneak the undead."})
    ref = load_reference(tmp_path)
    assert ref.feats([2213]) == [("Divine Strike", "Sneak the undead.")]


def test_reference_prc_feat_without_description_falls_back(tmp_path):
    # A PRC feat with a name but no bundled description shows the placeholder.
    _write(tmp_path)
    (tmp_path / "PRC Feats.json").write_text('{"2213": "Divine Strike"}', encoding="utf-8")
    ref = load_reference(tmp_path)  # no descriptions file
    assert ref.feats([2213]) == [("Divine Strike", "Feat description is not available.")]


def test_reference_base_name_wins_over_prc(tmp_path):
    # A PRC entry for a base-range id must NOT override the base line (base first).
    _write(tmp_path)  # base owns ids 0-2 (Alertness/Ambidexterity/Berserker Rage)
    (tmp_path / "PRC Feats.json").write_text('{"0": "PRC Override"}', encoding="utf-8")
    ref = load_reference(tmp_path)
    assert [name for name, _desc in ref.feats([0])] == ["Alertness"]


def test_reference_unknown_feat_stays_visible(tmp_path):
    # An id in neither base nor PRC surfaces as "Unknown feat <id>", not dropped.
    ref = load_reference(_write(tmp_path))  # no PRC file present
    assert ref.feats([500]) == [
        ("Unknown feat 500", "Feat description is not available.")
    ]


def test_reference_skills_lists_ranks_with_unknown_extras(tmp_path):
    ref = load_reference(_write(tmp_path))
    # Four ranks but only three named skills -> the 4th is "Unknown 1".
    skills = ref.skills([5, 0, 2, 7])
    by_name = {name: (rank, desc) for name, rank, desc in skills}
    assert by_name["Animal Empathy"] == (5, "Charisma skill.")
    assert by_name["Discipline"] == (2, "Resist knockdown.")
    assert by_name["Unknown 1"][0] == 7
    # Name-sorted output.
    assert [n for n, _r, _d in skills] == sorted(n for n, _r, _d in skills)


def test_reference_resolves_prc_skills(tmp_path):
    # Skill ids past the base table (3 here) resolve via the PRC extension map;
    # a genuinely unknown id still falls through to "Unknown N".
    _write(tmp_path)  # base skills are ids 0-2
    (tmp_path / "PRC Skills.json").write_text(
        '{"3": "Jump", "4": "Truespeak"}', encoding="utf-8"
    )
    ref = load_reference(tmp_path)
    by_name = {name: rank for name, rank, _desc in ref.skills([0, 0, 0, 9, 8, 0])}
    assert by_name["Jump"] == 9  # skill id 3 -> PRC name
    assert by_name["Truespeak"] == 8  # skill id 4 -> PRC name
    assert by_name["Unknown 1"] == 0  # skill id 5 -> still unknown


def test_reference_skill_base_name_wins_over_prc(tmp_path):
    # A PRC entry for a base-range skill id must NOT override the base line.
    _write(tmp_path)  # base owns ids 0-2 (Animal Empathy/Concentration/Discipline)
    (tmp_path / "PRC Skills.json").write_text('{"0": "PRC Override"}', encoding="utf-8")
    ref = load_reference(tmp_path)
    names = [name for name, _r, _d in ref.skills([1])]
    assert names == ["Animal Empathy"]  # base line 0, not the PRC entry


def test_load_prc_skill_names_parses_json_and_skips_non_int(tmp_path):
    path = tmp_path / "PRC Skills.json"
    path.write_text('{"28": "Jump", "bad": "skip"}', encoding="utf-8")
    assert load_prc_skill_names(path) == {28: "Jump"}


def test_load_prc_class_names_parses_json_and_skips_non_int(tmp_path):
    from vaultkeeper.game.character_reference import load_prc_class_names

    path = tmp_path / "PRC Classes.json"
    path.write_text('{"43": "Binder", "bad": "skip"}', encoding="utf-8")
    assert load_prc_class_names(path) == {43: "Binder"}


def test_bundled_prc_classes_loaded():
    ref = default_reference()
    # The bundled PRC class extension (prestige/base classes past base CLASS_NAMES).
    assert len(ref.prc_class_names) > 100
    assert ref.prc_class_names[43] == "Binder"


def test_bundled_reference_available():
    ref = default_reference()
    assert ref.available
    # The bundled tables are the full NWN set.
    assert len(ref.feat_names) > 1000
    assert ref.feat_names[0][0] == "Alertness"
    assert ref.skill_names[0] == "Animal Empathy"


def test_bundled_prc_feats_loaded():
    ref = default_reference()
    # The bundled PRC extension table (scraped from the PRC8 manual) is sizeable
    # and its ids all run past the base Feat Names.txt range.
    assert len(ref.prc_feat_names) > 10000
    assert min(ref.prc_feat_names) >= len(ref.feat_names)
    # A known PRC feat id from the PRC8 manual (id matches the .bic FeatList id).
    assert ref.prc_feat_names[2213] == "Divine Strike"


def test_bundled_prc_feat_descriptions_loaded():
    ref = default_reference()
    # The bundled (gzipped) PRC feat descriptions from the PRC8 manual pages.
    assert len(ref.prc_feat_descriptions) > 10000
    assert "Skullclan Hunter" in ref.prc_feat_descriptions[2213]


def test_bundled_prc_skills_loaded():
    ref = default_reference()
    # The bundled PRC skill extension — ids all past the base Skill Names.txt range.
    assert len(ref.prc_skill_names) >= 11
    assert min(ref.prc_skill_names) >= len(ref.skill_names)
    # A known PRC skill id (base-aligned: skill id == skills.2da row == .bic index).
    assert ref.prc_skill_names[28] == "Jump"


_LOCALVAULT = Path.home() / "Documents" / "Neverwinter Nights" / "localvault"
_REAL_L40 = _LOCALVAULT / "morcanfaenoble19.bic"


@pytest.mark.skipif(
    not _REAL_L40.is_file(), reason="owner's real level-40 .bic not present"
)
def test_real_level40_character_resolves_all_prc_feats_and_skills():
    """Golden: the owner's real PRC level-40 character shows its full feat/skill set.

    Before the PRC extensions, ~78 of its feat ids (in the thousands) fell off the
    end of the base table and vanished, and 11 PRC skills (ids 28-38) showed as
    "Unknown 1".."Unknown 11"; now every id resolves to a name.
    """
    from vaultkeeper.core.formats.bic_reader import BicFileReader

    info = BicFileReader().read_file(_REAL_L40)
    assert info is not None and info.level == 40
    ref = default_reference()

    feats = ref.feats(info.feat_ids)
    assert [name for name, _d in feats if name.startswith("Unknown feat ")] == []
    assert len(feats) > 100  # base + PRC, not just the ~60 base feats
    # Every feat (base and PRC) carries a real description, not the placeholder.
    assert [n for n, d in feats if d == "Feat description is not available."] == []

    skills = ref.skills(info.skill_ranks)
    assert [name for name, _r, _d in skills if name.startswith("Unknown")] == []
