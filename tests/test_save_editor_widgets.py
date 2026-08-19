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


def test_a_tab_is_wide_enough_for_its_bold_active_label(qtbot):
    """The active tab is drawn at weight 600; the button must fit that, not 500.

    It did not, and the label was clipped at both ends — "Abilities & Combat"
    came out as "bilities & Comba". macOS hid it because its UI font is narrow
    enough that the bold text still fitted; Windows, with Segoe UI, showed it.

    Asserted against the bold metrics rather than against a screenshot, so it
    holds on every platform. The measured case: the label is 105px at weight 500
    and 121px at 600, and the padding is 32px, so the hint of 137 was 16px short
    of the 153 the active tab needs — 8px clipped at each end.

    The padding matters in this sum. Leaving it out makes the assertion pass
    against the too-narrow hint, which is how the first version of this test
    went green on Windows against the very bug it was written for.
    """
    from PySide6.QtGui import QFont, QFontMetrics

    strip = w.TabStrip((("abilities", "Abilities & Combat"), ("skills", "Skills")))
    qtbot.addWidget(strip)
    strip.show()
    qtbot.waitExposed(strip)

    for key in ("abilities", "skills"):
        button = strip._dots[key]
        bold = QFont(button.font())
        bold.setWeight(QFont.Weight.DemiBold)
        text = QFontMetrics(bold).horizontalAdvance(button.text().replace("&&", "&"))
        needed = text + 2 * 16  # padding:11px 16px, both sides
        assert button.width() >= needed, (
            f"{key} clips its own label when active: "
            f"{button.width()}px wide, needs {needed}px"
        )


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


# -- Stepper: the −/+ number control that replaced the tiny spin-box arrows --- #
def test_stepper_exposes_a_ranged_spin_box(qtbot):
    step = w.stepper(minimum=0, maximum=43, value=5, tooltip="caps at 43")
    qtbot.addWidget(step)
    from PySide6.QtWidgets import QSpinBox

    assert isinstance(step.spin, QSpinBox)
    assert (step.spin.minimum(), step.spin.maximum()) == (0, 43)
    assert step.value() == 5
    assert step.spin.toolTip() == "caps at 43"


def test_stepper_has_labelled_plus_minus_buttons_not_bare_arrows(qtbot):
    step = w.stepper(minimum=0, maximum=10, value=1)
    qtbot.addWidget(step)
    from PySide6.QtWidgets import QAbstractSpinBox, QPushButton

    glyphs = {b.text() for b in step.findChildren(QPushButton)}
    assert glyphs == {"+", "−"}, "the control must show clear −/+ labels"
    # the field itself carries no native arrows (they were the unclear 'dots')
    assert step.spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons


def test_stepper_buttons_nudge_the_value_but_do_not_commit_per_click(qtbot):
    """A click runs the value live; nothing is staged mid-gesture. Staging (which
    rebuilds the screen and would destroy the control) waits until the pointer
    leaves — so running + then − never rebuilds the field out from under it."""
    from PySide6.QtWidgets import QPushButton

    committed = []
    step = w.stepper(minimum=0, maximum=10, value=4, on_commit=committed.append)
    qtbot.addWidget(step)
    plus = next(b for b in step.findChildren(QPushButton) if b.text() == "+")
    minus = next(b for b in step.findChildren(QPushButton) if b.text() == "−")

    plus.click()
    plus.click()
    minus.click()  # + then − in one gesture
    assert step.value() == 5, "clicks change the value live"
    assert committed == [], "but nothing is staged while the pointer stays on it"

    step.spin.editingFinished.emit()  # typed value: Enter / focus-out commits
    assert committed == [5], "the whole settled value stages once, on finish"


def test_stepper_commits_when_the_pointer_leaves(qtbot, monkeypatch):
    """The −/+ path stages on leave, not per click (see the docstring above)."""
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import QPushButton

    committed = []
    step = w.stepper(minimum=0, maximum=10, value=4, on_commit=committed.append)
    qtbot.addWidget(step)
    plus = next(b for b in step.findChildren(QPushButton) if b.text() == "+")
    plus.click()
    assert committed == []

    # Pretend the cursor is well outside the control, then deliver the leave.
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: QPoint(-9999, -9999)))
    step.leaveEvent(QEvent(QEvent.Type.Leave))
    assert committed == [5], "leaving the control stages the settled value once"


def test_stepper_leave_onto_a_child_does_not_commit(qtbot, monkeypatch):
    """Qt sends the parent a leaveEvent when the cursor moves onto its own child;
    that must not be mistaken for the user finishing."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import QPushButton

    committed = []
    step = w.stepper(minimum=0, maximum=10, value=4, on_commit=committed.append)
    qtbot.addWidget(step)
    step.resize(120, 30)
    next(b for b in step.findChildren(QPushButton) if b.text() == "+").click()

    # Cursor still inside the control's own rectangle (i.e. over a child).
    inside = step.mapToGlobal(step.rect().center())
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: inside))
    step.leaveEvent(QEvent(QEvent.Type.Leave))
    assert committed == [], "moving onto a child is not leaving the control"


def test_stepper_buttons_respect_the_range(qtbot):
    step = w.stepper(minimum=0, maximum=2, value=2)
    qtbot.addWidget(step)
    from PySide6.QtWidgets import QPushButton

    plus = next(b for b in step.findChildren(QPushButton) if b.text() == "+")
    plus.click()
    assert step.value() == 2, "cannot step past the maximum"


# -- ElidingLabel: keeps a long save name from pinning the window width -------- #
def test_eliding_label_shows_full_text_when_it_fits(qtbot):
    label = w.eliding_body("Short name")
    qtbot.addWidget(label)
    label.setFixedWidth(400)
    label.show()
    qtbot.waitExposed(label)
    assert label.text() == "Short name"
    assert label.toolTip() == "Short name", "the full text is always the tooltip"


def test_eliding_label_truncates_and_does_not_force_its_width(qtbot):
    long = "000002 - quicksave (edited)  —  A Cave beneath the Cloudpeaks"
    label = w.eliding_body(long)
    qtbot.addWidget(label)
    assert label.minimumWidth() == 0, "must not pin a minimum from its text"

    label.setFixedWidth(120)
    label.show()
    qtbot.waitExposed(label)  # a real resize so resizeEvent runs the elision
    shown = label.text()
    assert shown != long and shown.endswith("…"), "narrow: elided with an ellipsis"
    assert label.toolTip() == long, "the untruncated name stays on hover"

    label.setText("A different, also quite long, save name here")
    assert label.toolTip() == "A different, also quite long, save name here"
