"""Tests for the feat/skill reference tables (VB BicFileInfo GetNames/GetDescriptions)."""

from __future__ import annotations

from pathlib import Path

from vaultkeeper.game.character_reference import (
    default_reference,
    load_feat_descriptions,
    load_feat_names,
    load_reference,
    load_skill_descriptions,
    load_skill_names,
)


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
    # feat ids 2, 0, 0 (duplicate), 99 (out of range) -> named, deduped, sorted.
    feats = ref.feats([2, 0, 0, 99])
    assert [name for name, _desc in feats] == ["Alertness", "Berserker Rage"]
    # Description comes from the ref lookup; Berserker Rage (ref 111) has none.
    assert dict(feats)["Alertness"] == "Spot and Listen bonus."
    assert dict(feats)["Berserker Rage"] == "Feat description is not available."


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


def test_bundled_reference_available():
    ref = default_reference()
    assert ref.available
    # The bundled tables are the full NWN set.
    assert len(ref.feat_names) > 1000
    assert ref.feat_names[0][0] == "Alertness"
    assert ref.skill_names[0] == "Animal Empathy"
