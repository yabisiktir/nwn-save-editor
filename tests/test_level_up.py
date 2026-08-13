"""Computing what a class level grants (LevelUpCalculator)."""

from __future__ import annotations

from nwnfile.level_up import LevelUpCalculator


class _Reader:
    def __init__(self) -> None:
        self.tables = {
            "classes": {
                0: {  # a base martial class, full BAB, good Fort
                    "Label": "Barbarian", "HitDie": "12", "AttackBonusTable": "CLS_ATK_1",
                    "SavingThrowTable": "CLS_SAVTHR_BARB", "SkillPointBase": "4",
                    "FeatsTable": "CLS_FEAT_BARB", "SpellGainTable": "****",
                    "SpellKnownTable": "****",
                },
                190: {  # a PRC caster prestige class
                    "Label": "Archivist", "HitDie": "6", "AttackBonusTable": "CLS_ATK_3",
                    "SavingThrowTable": "CLS_SAVTHR_CLER", "SkillPointBase": "4",
                    "FeatsTable": "CLS_FEAT_SKLCLN", "SpellGainTable": "CLS_SPGN_ARCHV",
                    "SpellKnownTable": "****",
                },
            },
            "cls_atk_1": {i: {"BAB": str(i + 1)} for i in range(20)},  # full: +1/level
            "cls_atk_3": {i: {"BAB": str((i + 1) * 3 // 4)} for i in range(20)},  # 3/4
            # good save = 2 + level//2 ; poor save = level//3 (level = i+1)
            "cls_savthr_barb": {
                i: {"Level": str(i + 1), "FortSave": str(2 + (i + 1) // 2),
                    "RefSave": str((i + 1) // 3), "WillSave": str((i + 1) // 3)}
                for i in range(20)
            },
            "cls_savthr_cler": {
                i: {"Level": str(i + 1), "FortSave": str(2 + (i + 1) // 2),
                    "RefSave": str((i + 1) // 3), "WillSave": str(2 + (i + 1) // 2)}
                for i in range(20)
            },
            "feat": {2213: {"LABEL": "Skullclan_DivineStrike"}},
            "cls_feat_barb": {},
            "cls_feat_sklcln": {
                0: {"FeatLabel": "Skullclan_DivineStrike", "FeatIndex": "2213",
                    "GrantedOnLevel": "3"},
            },
        }

    def read_2da(self, name: str):
        return self.tables.get(name.lower())


class _ReaderWithBase(_Reader):
    def read_base_2da(self, name: str):
        # Base game has class 0 (Barbarian) but not the PRC prestige class 190.
        return {0: {"Label": "Barbarian"}} if name.lower() == "classes" else None


def _calc(reader=None):
    return LevelUpCalculator(reader or _Reader())


def test_full_bab_and_good_fort_gain_one_at_level_two():
    g = _calc().gains(0, 2, character_level=2)
    assert g.hit_die == 12
    assert g.bab_gain == 1  # full BAB: +1 per level
    assert g.fort_gain == 1  # good save steps 2 -> 3 at level 2
    assert g.ref_gain == 0


def test_skill_points_quadruple_at_first_level():
    g = _calc().gains(0, 1, character_level=1)
    assert g.skill_points(int_modifier=1) == (4 + 1) * 4  # (base+Int) x4 at level 1
    g2 = _calc().gains(0, 2, character_level=2)
    assert g2.skill_points(int_modifier=1) == 4 + 1  # then once per level


def test_skill_points_floor_at_one():
    g = _calc().gains(2 - 2, 5, character_level=5)  # class 0, low int
    assert g.skill_points(int_modifier=-10) == 1


def test_hit_points_max_at_first_level_then_by_rule():
    g1 = _calc().gains(0, 1, character_level=1)
    assert g1.hit_points(con_modifier=2) == 12 + 2  # first level always max
    g2 = _calc().gains(0, 2, character_level=2)
    assert g2.hit_points(con_modifier=0, rule="max") == 12
    assert g2.hit_points(con_modifier=0, rule="average") == 12 // 2 + 1


def test_a_general_feat_is_due_every_third_character_level():
    assert _calc().gains(0, 3, character_level=3).general_feat is True
    assert _calc().gains(0, 2, character_level=2).general_feat is False


def test_an_ability_point_is_due_every_fourth_character_level():
    assert _calc().gains(0, 4, character_level=4).ability_increase is True
    assert _calc().gains(0, 3, character_level=3).ability_increase is False


def test_class_granted_feats_appear_at_their_level():
    g = _calc().gains(190, 3, character_level=3)  # uses CLS_FEAT_SKLCLN in the fixture
    assert (2213, "Skullclan DivineStrike") in g.granted_feats
    assert _calc().gains(190, 2, character_level=2).granted_feats == ()


def test_caster_and_base_class_flags():
    barb = _calc(_ReaderWithBase()).gains(0, 2, character_level=2)
    arch = _calc(_ReaderWithBase()).gains(190, 2, character_level=2)
    assert barb.spellcaster is False and barb.is_base_class is True
    assert arch.spellcaster is True and arch.is_base_class is False  # PRC


def test_an_unknown_class_is_none():
    assert _calc().gains(9999, 1, character_level=1) is None
