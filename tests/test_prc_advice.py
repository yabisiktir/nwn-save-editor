"""Classifying a PRC feat into what a save-edit can and can't grant."""

from __future__ import annotations

from nwnfile.prc_advice import PrcAdvisor


class _Reader:
    """A stand-in for HakStack.read_2da, backed by canned tables.

    Mirrors the real PRC schema seen in the source 2das: classes.2da names each
    class's FeatsTable (CLS_FEAT_x); cls_feat_x lists granted feats by FeatIndex;
    cls_spell_x lists spellbook abilities by FeatID.
    """

    def __init__(self) -> None:
        self.tables = {
            "feat": {
                2213: {"LABEL": "Skullclan_DivineStrike", "SPELLID": "****"},
                3949: {"LABEL": "Dragonfire_Strike", "SPELLID": "1890"},
                3951: {"LABEL": "Masters_Gift", "SPELLID": "****"},
                14373: {"LABEL": "Archivist_Darkfire", "SPELLID": "****"},
                100: {"LABEL": "Alertness", "SPELLID": "****"},
            },
            "classes": {
                190: {"Label": "Archivist", "FeatsTable": "CLS_FEAT_ARCHV"},
                227: {"Label": "SkullclanHunter", "FeatsTable": "CLS_FEAT_SKLCLN"},
            },
            "cls_feat_sklcln": {
                0: {"FeatLabel": "Skullclan_DivineStrike", "FeatIndex": "2213"},
            },
            "cls_feat_archv": {},
            "cls_spell_archv": {
                952: {"Label": "Archivist_Darkfire", "FeatID": "14373"},
            },
        }

    def read_2da(self, name: str):
        return self.tables.get(name.lower())


def _advisor() -> PrcAdvisor:
    return PrcAdvisor(_Reader())


def test_a_spellbook_ability_is_flagged_as_unobtainable_by_a_feat_add():
    advice = _advisor().advise(14373)  # Archivist Darkfire
    assert advice.bucket == "spellbook"
    assert advice.class_name == "Archivist"
    assert "can't grant" in advice.direction
    assert "Archivist" in advice.direction


def test_a_class_feature_needs_the_class():
    advice = _advisor().advise(2213)  # Skullclan Divine Strike
    assert advice.bucket == "class"
    assert advice.class_name == "SkullclanHunter"
    assert "class levels" in advice.direction


def test_a_standalone_active_feat_notes_the_reevaluation():
    advice = _advisor().advise(3949)  # Dragonfire Strike (has a SpellID)
    assert advice.bucket == "standalone"
    assert advice.active is True  # SpellID set -> shows in the radial
    assert "re-equip" in advice.direction


def test_a_standalone_passive_feat_is_standalone_and_inactive():
    advice = _advisor().advise(3951)  # Master's Gift (no SpellID)
    assert advice.bucket == "standalone"
    assert advice.active is False


def test_an_unknown_id_says_so():
    advice = _advisor().advise(999999)
    assert advice.bucket == "unknown"
    assert advice.label == ""


def test_the_membership_scan_runs_once():
    """Reads are cached: advising many feats must not re-scan every class table."""
    reader = _Reader()
    calls: list[str] = []
    original = reader.read_2da
    reader.read_2da = lambda name: (calls.append(name), original(name))[1]  # type: ignore[assignment]
    advisor = PrcAdvisor(reader)
    advisor.advise(2213)
    first = len(calls)
    advisor.advise(14373)
    advisor.advise(3949)
    assert len(calls) == first, "membership + feat table should be built only once"


class _ReaderWithSource(_Reader):
    """Adds .nss so the source refinement runs: Barbarian grants Dragonfire Strike
    (class-granted) but it is handled in prc_feats, so it is feat-driven, not gated.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tables["classes"][10] = {"Label": "Barbarian", "FeatsTable": "CLS_FEAT_BARB"}
        self.tables["cls_feat_barb"] = {
            0: {"FeatLabel": "Dragonfire_Strike", "FeatIndex": "3949"},
        }
        self.scripts = {
            "prc_feat_const": (
                "const int FEAT_DRAGONFIRE_STRIKE = 3949;\n"
                "const int FEAT_MASTERS_GIFT = 3951;\n"
            ),
            "prc_feats": "if(GetHasFeat(FEAT_DRAGONFIRE_STRIKE, oPC)) hook();",
            "prc_effect_inc": "if(GetHasFeat(FEAT_MASTERS_GIFT, oTarget)) apply();",
        }

    def read_script(self, name: str):
        return self.scripts.get(name)


def test_class_granted_but_feat_driven_is_not_gated_on_the_class():
    advice = PrcAdvisor(_ReaderWithSource()).advise(3949)  # granted by Barbarian
    assert advice.bucket == "standalone", "handled in prc_feats -> feat-driven"
    assert "re-equip" in advice.direction


def test_a_passive_feat_applies_immediately():
    advice = PrcAdvisor(_ReaderWithSource()).advise(3951)  # in prc_effect_inc
    assert advice.bucket == "standalone"
    assert "as soon as the save loads" in advice.direction


def test_a_class_feat_absent_from_the_handlers_stays_class_gated():
    advice = PrcAdvisor(_ReaderWithSource()).advise(2213)  # Skullclan, class-only
    assert advice.bucket == "class"
    assert advice.class_name == "SkullclanHunter"


def test_a_base_game_feat_reads_as_base_even_if_a_class_can_pick_it():
    """Alertness (id 100) is a base feat; a class listing it must not gate it."""
    reader = _Reader()
    # A class that offers Alertness as a bonus feat — the over-broad case.
    reader.tables["classes"][10] = {"Label": "Barbarian", "FeatsTable": "CLS_FEAT_BARB"}
    reader.tables["cls_feat_barb"] = {0: {"FeatLabel": "Alertness", "FeatIndex": "100"}}
    advice = PrcAdvisor(reader).advise(100)  # no read_base_2da -> id < 1116 fallback
    assert advice.bucket == "base"
    assert "engine handles it" in advice.headline


class _ReaderWithBase(_Reader):
    def read_base_2da(self, name: str):
        # The base feat.2da holds Alertness (100) but not the PRC feats.
        return {100: {"LABEL": "Alertness"}} if name.lower() == "feat" else None


def test_the_base_set_is_used_when_the_reader_offers_it():
    advisor = PrcAdvisor(_ReaderWithBase())
    assert advisor.advise(100).bucket == "base"
    # 14373 is not in the base set -> PRC analysis (spellbook).
    assert advisor.advise(14373).bucket == "spellbook"
