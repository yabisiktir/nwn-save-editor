"""The Save Game Editor's design tokens and shared widget vocabulary."""

from __future__ import annotations

import pytest

from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w


def test_tokens_are_hex_or_rgba():
    """Qt stylesheets can't parse ``oklch()`` — every colour must be converted."""
    for name in dir(t):
        if name.startswith("_"):
            continue
        value = getattr(t, name)
        if isinstance(value, str) and ("#" in value or "rgb" in value):
            assert "oklch" not in value, f"{name} still holds an OKLCH value"


def test_gold_tint_and_border_take_the_designs_alphas():
    assert t.gold_tint(0.15) == "rgba(58, 43, 13, 0.15)"
    assert t.gold_border(0.4) == "rgba(155, 123, 60, 0.4)"
    assert t.hairline(0.08) == "rgba(255, 255, 255, 0.08)"


def test_sheet_skins_cover_the_four_designed_skins():
    assert set(t.SHEET_SKINS) == {"leather", "crimson", "steel", "verdant"}
    assert [key for key, _ in t.SKIN_SWATCHES] == ["leather", "crimson", "steel", "verdant"]


def test_segmented_control_reports_and_sets_its_value(qtbot):
    control = w.SegmentedControl((("strict", "Strict"), ("free", "Free")))
    qtbot.addWidget(control)
    assert control.value() == "strict"  # first option is checked by default
    control.set_value("free")
    assert control.value() == "free"


def test_tab_strip_switches_and_marks_dirty_tabs(qtbot):
    strip = w.TabStrip((("abilities", "Abilities & Combat"), ("skills", "Skills")))
    qtbot.addWidget(strip)
    assert strip.value() == "abilities"
    strip.set_value("skills")
    assert strip.value() == "skills"

    strip.set_dirty("skills", True)
    assert strip._dots["skills"].text() == "Skills ●"
    strip.set_dirty("skills", True)  # idempotent — must not double up the marker
    assert strip._dots["skills"].text() == "Skills ●"
    strip.set_dirty("skills", False)
    assert strip._dots["skills"].text() == "Skills"


def test_nav_row_shows_its_dirty_dot_only_when_asked(qtbot):
    row = w.NavRow("character", "Character", "CH")
    qtbot.addWidget(row)
    row.show()
    assert not row._dot.isVisible()
    row.set_dirty(True)
    assert row._dot.isVisible()


def test_nav_row_recolours_its_label_when_checked(qtbot):
    row = w.NavRow("character", "Character", "CH")
    qtbot.addWidget(row)
    row.setChecked(True)
    assert t.GOLD in row._label.styleSheet()
    row.setChecked(False)
    assert t.TEXT_2 in row._label.styleSheet()


@pytest.mark.parametrize(
    "factory", [w.gold_button, w.ghost_button, w.small_ghost, w.pill_toggle]
)
def test_buttons_build_and_carry_a_disabled_rule(qtbot, factory):
    """The design dims disabled controls; Qt stylesheets have no ``opacity``."""
    button = factory("Save as New…")
    qtbot.addWidget(button)
    assert ":disabled" in button.styleSheet()
    assert "opacity" not in button.styleSheet()


def test_prc_badge_explains_why_an_edit_may_not_stick(qtbot):
    badge = w.prc_badge()
    qtbot.addWidget(badge)
    assert "PRC" in badge.text()
    assert "may not stick" in badge.toolTip()
