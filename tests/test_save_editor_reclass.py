"""The Character screen's re-class glue (CharacterScreen._apply_reclass).

The byte-level move is covered by SaveEditor.reclass_level in test_class_level;
here we exercise the screen's orchestration of the *choices* — removing the old
level's feat/ability/skill points (faithful) or keeping them (Free "break it") and
applying the new ones — against a real edit session, no game stack needed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nwnfile.formats.gff import Gff, GffField, GffList, GffStruct, GffType, write_gff
from nwnsaveeditor.save_game import SaveGame
from nwnsaveeditor.ui.editor.window import SaveEditorWindow
from tests.test_class_level import FIGHTER, ROGUE, _fighter_top_gains, _rogue_gains
from tests.test_erf_writer import _make_erf

OLD_FEAT, KEEP_FEAT, NEW_FEAT = 42, 7, 99


class _FakeWizard:
    """Stands in for LevelUpWizard — just returns the choices _apply_reclass reads."""

    def __init__(self, *, skills=None, feat=None, ability=None, spells=None) -> None:
        self._skills, self._feat = skills or {}, feat
        self._ability, self._spells = ability, spells or {}

    def skill_allocations(self):
        return dict(self._skills)

    def chosen_feat(self):
        return self._feat

    def chosen_ability(self):
        return self._ability

    def chosen_spells(self):
        return dict(self._spells)


def _character() -> GffStruct:
    """Fighter 3 that has a feat and a skill the *second* level granted, plus a
    recorded history that says so — so a faithful re-class has something to undo."""
    classes = [GffStruct(struct_type=2, fields={
        "Class": GffField(GffType.INT, FIGHTER),
        "ClassLevel": GffField(GffType.SHORT, 3),
    })]
    skills = [GffStruct(struct_type=0, fields={"Rank": GffField(GffType.SHORT, r)})
              for r in (4, 2, 0)]
    feats = [GffStruct(struct_type=1, fields={"Feat": GffField(GffType.WORD, f)})
             for f in (OLD_FEAT, KEEP_FEAT)]
    history = []
    for deltas, feat, ability in (
        ([4, 0, 0], None, None), ([0, 1, 0], OLD_FEAT, 0), ([0, 1, 0], None, None),
    ):
        fields = {
            "LvlStatClass": GffField(GffType.BYTE, FIGHTER),
            "LvlStatHitDie": GffField(GffType.BYTE, 10),
            "EpicLevel": GffField(GffType.BYTE, 0),
            "SkillPoints": GffField(GffType.WORD, 0),
            "SkillList": GffField(GffType.LIST, GffList([
                GffStruct(struct_type=0, fields={"Rank": GffField(GffType.BYTE, d)})
                for d in deltas
            ])),
            "FeatList": GffField(GffType.LIST, GffList(
                [GffStruct(struct_type=0, fields={"Feat": GffField(GffType.WORD, feat)})]
                if feat is not None else []
            )),
        }
        if ability is not None:
            fields["LvlStatAbility"] = GffField(GffType.BYTE, ability)  # 0 = Str
        history.append(GffStruct(struct_type=0, fields=fields))
    return GffStruct(struct_type=0xFFFFFFFF, fields={
        "FeatList": GffField(GffType.LIST, GffList(feats)),
        "ClassList": GffField(GffType.LIST, GffList(classes)),
        "SkillList": GffField(GffType.LIST, GffList(skills)),
        "LvlStatList": GffField(GffType.LIST, GffList(history)),
        "MaxHitPoints": GffField(GffType.INT, 30),
        "CurrentHitPoints": GffField(GffType.INT, 30),
        "BaseAttackBonus": GffField(GffType.INT, 3),
        "FortSaveThrow": GffField(GffType.INT, 3),
        "RefSaveThrow": GffField(GffType.INT, 1),
        "WillSaveThrow": GffField(GffType.INT, 1),
        "Experience": GffField(GffType.INT, 3000),
        "Str": GffField(GffType.BYTE, 16),
        "Dex": GffField(GffType.BYTE, 14),
        "Con": GffField(GffType.BYTE, 12),
    })


@pytest.fixture
def window(qtbot, tmp_path):
    ifo = Gff("IFO ", "V3.2", GffStruct(struct_type=0xFFFFFFFF, fields={
        "Mod_PlayerList": GffField(GffType.LIST, GffList([_character()])),
    }))
    bic = Gff("BIC ", "V3.2", _character())
    folder = tmp_path / "000000 - reclass"
    folder.mkdir()
    (folder / "x.sav").write_bytes(_make_erf([("module", 2014, write_gff(ifo))]))
    (folder / "player.bic").write_bytes(write_gff(bic))
    save = SaveGame(folder=folder)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    editor = SaveEditorWindow([save], _Ctrl())
    qtbot.addWidget(editor)
    editor._editing = True
    return editor


def _feats(session):
    return {fid for fid, _n, _b in session.player_feats()}


def _score(session, field):
    return next(f.value for f in session.player_fields() if f.field == field)


def _skill_rank(session, index):
    return next(s.rank for s in session.player_skills() if s.index == index)


def test_faithful_reclass_swaps_the_feat_moves_the_ability_and_lowers_the_skill(window):
    screen = window._screens["character"]
    session = window.session()
    old = session.level_entry(1)  # Fighter level that granted OLD_FEAT + a Str point
    wizard = _FakeWizard(feat=NEW_FEAT, ability="Dex")
    screen._apply_reclass(
        session, 1, old, ROGUE, _rogue_gains(), _fighter_top_gains(),
        keep_previous=False, wizard=wizard,
    )
    assert _feats(session) == {KEEP_FEAT, NEW_FEAT}  # old feat removed, new added
    assert _score(session, "Str") == 15  # the Str point the level gave is taken back
    assert _score(session, "Dex") == 15  # and the new level's point goes to Dex
    assert _skill_rank(session, 1) == 1  # the 1 rank that level spent is refunded
    assert dict(session.player_classes()) == {FIGHTER: 2, ROGUE: 1}


def _ghost_button(screen, text_fragment):
    from PySide6.QtWidgets import QPushButton

    return next(
        (b for b in screen.findChildren(QPushButton) if text_fragment in b.text()), None
    )


def test_the_reclass_button_appears_only_with_editing_and_the_toggle_on(window, monkeypatch):
    screen = window._screens["character"]
    monkeypatch.setattr(window, "class_level_editing_enabled", lambda: True)
    window._editing = False
    screen.refresh()
    screen._show_tab()
    assert _ghost_button(screen, "Change a level's class") is None  # gated on edit mode

    window._editing = True
    screen.refresh()
    screen._show_tab()
    assert _ghost_button(screen, "Change a level's class") is not None


def test_reclass_without_class_tables_reports_and_does_not_raise(window, monkeypatch):
    from nwnsaveeditor.ui.editor import widgets as w

    screen = window._screens["character"]
    shown = []
    monkeypatch.setattr(w, "message", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(window, "hak_stack", lambda: None)  # no game root -> no tables
    screen._reclass_level()  # must not raise
    assert shown and "class tables" in shown[0][3].lower()  # (parent, icon, title, text, …)


def test_keep_previous_reclass_keeps_the_feat_ability_and_skill(window):
    screen = window._screens["character"]
    session = window.session()
    old = session.level_entry(1)
    wizard = _FakeWizard(feat=NEW_FEAT, ability="Dex")
    screen._apply_reclass(
        session, 1, old, ROGUE, _rogue_gains(), _fighter_top_gains(),
        keep_previous=True, wizard=wizard,
    )
    assert _feats(session) == {OLD_FEAT, KEEP_FEAT, NEW_FEAT}  # nothing removed
    assert _score(session, "Str") == 16  # the old Str point stays
    assert _score(session, "Dex") == 15  # new point still applied
    assert _skill_rank(session, 1) == 2  # old rank not refunded
    assert dict(session.player_classes()) == {FIGHTER: 2, ROGUE: 1}  # counts still move
