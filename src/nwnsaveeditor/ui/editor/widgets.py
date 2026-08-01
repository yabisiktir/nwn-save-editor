"""The Save Game Editor's shared widget vocabulary.

Every screen is built from these, so the design stays consistent and each screen
file stays about *its* content rather than about styling. The handoff asks for
high fidelity but says to "prefer the native control that carries the same meaning
over a pixel-exact reproduction" — so these are ordinary Qt widgets wearing the
design's colours, not custom-painted lookalikes.

Qt stylesheets have no ``opacity``, so the design's "disabled = opacity .45" is
expressed as explicitly dimmed colours in a ``:disabled`` rule.

Every stylesheet here is built inside a function. A module-level f-string would
bake whichever theme happened to be active at import time, and the editor's theme
toggle swaps :mod:`~nwnsaveeditor.ui.editor.tokens` live.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nwnsaveeditor.ui.editor import tokens as t


def paints_own_background(widget: QWidget) -> QWidget:
    """Let a plain ``QWidget`` render a *selector-scoped* stylesheet.

    Unscoped inline QSS ("background:x;border:y") applies to a widget directly, but
    a rule behind a selector (``Foo{...}`` / ``#foo{...}``) is ignored for
    background and border on a bare QWidget unless this attribute is set. QFrame
    subclasses paint either way, which is why ``Panel`` does not need it.
    """
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    return widget


def _literal(text: str) -> str:
    """Escape ``&`` so Qt draws it instead of eating it as a mnemonic.

    Several labels in the design contain a literal ampersand ("Abilities & Combat",
    "Inventory & Equipment", "Quests & World State"), which a button would
    otherwise turn into an access key and render as an underline.
    """
    return text.replace("&", "&&")


# -- Text ----------------------------------------------------------------- #
def cap_label(text: str) -> QLabel:
    """A small uppercase section caption (``SECTIONS``, ``PENDING CHANGES``)."""
    label = QLabel(text.upper())
    label.setStyleSheet(
        f"font-family:{t.UI_FAMILY};font-size:11px;font-weight:600;"
        f"letter-spacing:0.04em;color:{t.TEXT_2};background:transparent;"
    )
    return label


def heading(text: str, size: int = 16) -> QLabel:
    """A Cinzel-style display heading (screen and section titles)."""
    label = QLabel(text)
    label.setStyleSheet(
        f"font-family:{t.DISPLAY_FAMILY};font-size:{size}px;font-weight:600;"
        f"color:{t.TEXT_HEADING};background:transparent;"
    )
    return label


def body(text: str, color: str | None = None, size: float = 12.5) -> QLabel:
    """Ordinary UI copy. Wraps, because most body text in the design does."""
    label = QLabel(text)
    label.setWordWrap(True)
    # A wrapping QLabel still reports a single-line sizeHint, so in a vertical
    # layout it is given one line's height and paints over its neighbour. Layouts
    # only consult heightForWidth when the size policy opts in.
    policy = label.sizePolicy()
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    label.setStyleSheet(
        f"font-family:{t.UI_FAMILY};font-size:{size}px;"
        f"color:{color or t.TEXT};background:transparent;"
    )
    return label


def mono(text: str, color: str | None = None, size: float = 11.5) -> QLabel:
    """Ids, codes, paths and filenames — the design sets these in a mono face."""
    label = QLabel(text)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setStyleSheet(
        f"font-family:{t.MONO_FAMILY};font-size:{size}px;"
        f"color:{color or t.TEXT_2};background:transparent;"
    )
    return label


# -- Buttons -------------------------------------------------------------- #
def _btn_base() -> str:
    """Metrics shared by every full-size button."""
    return (
        f"font-family:{t.UI_FAMILY};font-size:12.5px;font-weight:600;"
        f"border-radius:{t.RADIUS_BUTTON}px;padding:6px 14px;"
    )


def gold_button(text: str) -> QPushButton:
    """The primary action (Save as New…, Overwrite save, Write new file)."""
    button = QPushButton(_literal(text))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(
        f"QPushButton{{{_btn_base()}border:none;background:{t.GOLD};color:{t.GOLD_ON};}}"
        f"QPushButton:hover{{background:{t.GOLD_HOVER};}}"
        f"QPushButton:disabled{{background:{t.GOLD_OFF};color:{t.GOLD_OFF_ON};}}"
    )
    return button


def ghost_button(text: str) -> QPushButton:
    """A secondary action — outlined, transparent fill."""
    button = QPushButton(_literal(text))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(
        f"QPushButton{{{_btn_base()}font-weight:500;border:1px solid {t.hairline(0.16)};"
        f"background:transparent;color:{t.TEXT};}}"
        f"QPushButton:hover{{background:{t.hairline(0.06)};}}"
        f"QPushButton:disabled{{color:{t.TEXT_3};border-color:{t.hairline(0.08)};}}"
    )
    return button


def small_ghost(text: str) -> QPushButton:
    """The compact row-level action (``Edit…``, ``×``, ``Add a feat…``)."""
    button = QPushButton(_literal(text))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(
        f"QPushButton{{font-family:{t.UI_FAMILY};font-size:11px;font-weight:600;"
        f"border-radius:{t.RADIUS_CHIP}px;padding:3px 9px;"
        f"border:1px solid {t.hairline(0.16)};background:transparent;color:{t.TEXT_2};}}"
        f"QPushButton:hover{{color:{t.TEXT};background:{t.hairline(0.06)};}}"
        f"QPushButton:disabled{{color:{t.TEXT_3};border-color:{t.hairline(0.08)};}}"
    )
    return button


def pill_toggle(text: str) -> QPushButton:
    """The checkable ``Edit`` pill — turns gold when on."""
    button = QPushButton(_literal(text))
    button.setCheckable(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(
        f"QPushButton{{{_btn_base()}border:1px solid {t.hairline(0.16)};"
        f"background:transparent;color:{t.TEXT};}}"
        f"QPushButton:hover{{background:{t.hairline(0.06)};}}"
        f"QPushButton:checked{{border-color:{t.gold_border(0.5)};"
        f"background:{t.gold_tint(0.2)};color:{t.GOLD};}}"
        f"QPushButton:disabled{{color:{t.TEXT_3};border-color:{t.hairline(0.08)};}}"
    )
    return button


class SegmentedControl(QWidget):
    """A two-or-more-way exclusive choice (the design's ``Strict`` / ``Free``)."""

    def __init__(self, options: tuple[tuple[str, str], ...], parent: QWidget | None = None) -> None:
        """``options`` is a tuple of ``(key, label)`` in display order."""
        super().__init__(parent)
        paints_own_background(self)
        self.setStyleSheet(
            f"SegmentedControl{{border:1px solid {t.hairline(0.16)};"
            f"border-radius:{t.RADIUS_BUTTON}px;background:transparent;}}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._keys: dict[QAbstractButton, str] = {}
        for key, label in options:
            button = QPushButton(_literal(label))
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                f"QPushButton{{font-family:{t.UI_FAMILY};font-size:11.5px;font-weight:600;"
                f"border:none;border-radius:{t.RADIUS_CHIP}px;padding:6px 14px;"
                f"background:transparent;color:{t.TEXT_2};}}"
                f"QPushButton:checked{{background:{t.gold_tint(0.25)};color:{t.GOLD};}}"
            )
            self._group.addButton(button)
            self._keys[button] = key
            layout.addWidget(button)
        first = self._group.buttons()[0]
        first.setChecked(True)

    @property
    def changed(self):
        """Signal emitting the newly checked button (connect and call :meth:`value`)."""
        return self._group.buttonClicked

    def value(self) -> str:
        """The checked option's key."""
        return self._keys[self._group.checkedButton()]

    def set_value(self, key: str) -> None:
        for button, option in self._keys.items():
            if option == key:
                button.setChecked(True)
                return


# -- Surfaces ------------------------------------------------------------- #
class Panel(QFrame):
    """An inset panel — the design's ``oklch(0.185 0.014 55)`` block."""

    def __init__(
        self, parent: QWidget | None = None, *, radius: int = t.RADIUS_PANEL, padding: int = 14
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"Panel{{background:{t.INSET};border:1px solid {t.hairline(0.06)};"
            f"border-radius:{radius}px;}}"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(10)

    def body_layout(self) -> QVBoxLayout:
        """The panel's content layout — add rows to this."""
        return self._layout


class WarningPanel(QFrame):
    """The red-tinted warning block (Free mode, no-backup overwrite).

    A named subclass rather than a plain ``QFrame`` so the stylesheet can be scoped
    to it: ``QLabel`` derives from ``QFrame``, so a ``QFrame{...}`` rule set on the
    frame would also paint the danger border around the child text.
    """


def warning_panel(text: str) -> WarningPanel:
    """Build a :class:`WarningPanel` carrying ``text``."""
    frame = WarningPanel()
    frame.setStyleSheet(
        f"WarningPanel{{background:{t.DANGER_BG};border:1px solid {t.DANGER_BORDER};"
        f"border-radius:9px;}}"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.addWidget(body(text, t.DANGER, 12))
    return frame


def hline() -> QFrame:
    """A 1px hairline separator."""
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background:{t.hairline(0.08)};border:none;")
    return line


def vline() -> QFrame:
    """A 1px vertical divider (used in the toolbar)."""
    line = QFrame()
    line.setFixedWidth(1)
    line.setStyleSheet(f"background:{t.hairline(0.08)};border:none;")
    return line


def scrollbar_qss() -> str:
    """Scrollbar styling for the editor's scroll areas.

    Qt's default chrome is a bright native bar that reads as a bug against the
    editor's own surfaces, in either theme.
    """
    return (
        f"QScrollBar:vertical{{background:transparent;width:9px;margin:0;}}"
        f"QScrollBar::handle:vertical{{background:{t.hairline(0.14)};border-radius:4px;"
        f"min-height:28px;}}"
        f"QScrollBar::handle:vertical:hover{{background:{t.hairline(0.24)};}}"
        f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        f"QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{{background:transparent;}}"
        f"QScrollBar:horizontal{{background:transparent;height:9px;margin:0;}}"
        f"QScrollBar::handle:horizontal{{background:{t.hairline(0.14)};border-radius:4px;"
        f"min-width:28px;}}"
        f"QScrollBar::handle:horizontal:hover{{background:{t.hairline(0.24)};}}"
        f"QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{{width:0;}}"
        f"QScrollBar::add-page:horizontal,"
        f"QScrollBar::sub-page:horizontal{{background:transparent;}}"
    )


def scroll_area_qss(background: str = "transparent") -> str:
    """A frameless scroll area with the editor's scrollbars — every screen's pairing."""
    return f"QScrollArea{{background:{background};border:none;}}" + scrollbar_qss()


# -- Small indicators ----------------------------------------------------- #
def icon_chip(code: str, *, size: int = t.NAV_CHIP) -> QLabel:
    """The 2-letter gold code chip used as a nav/section icon."""
    chip = QLabel(code)
    chip.setFixedSize(size, size)
    chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
    chip.setStyleSheet(
        f"background:{t.ICON_CHIP};color:{t.GOLD};border-radius:{t.RADIUS_CHIP}px;"
        f"font-family:{t.UI_FAMILY};font-size:9.5px;font-weight:700;"
    )
    return chip


def status_dot(color: str | None = None) -> QLabel:
    """The 6px dot marking a section with unsaved changes."""
    dot = QLabel()
    dot.setFixedSize(t.STATUS_DOT, t.STATUS_DOT)
    dot.setStyleSheet(
        f"background:{color or t.GOLD};border-radius:{t.STATUS_DOT // 2}px;"
    )
    return dot


def prc_badge() -> QLabel:
    """The ``(PRC)`` badge — content PRC regenerates, so an edit may not stick."""
    badge = QLabel("PRC")
    badge.setStyleSheet(
        f"color:{t.PRC_AMBER};border:1px solid {t.PRC_BORDER};"
        f"border-radius:{t.RADIUS_BADGE}px;padding:1px 4px;"
        f"font-family:{t.UI_FAMILY};font-size:8.5px;font-weight:700;"
    )
    badge.setToolTip(
        "PRC manages this from its own data and regenerates it on rest, level-up "
        "or area load — an edit here may not stick in-game."
    )
    return badge


class NavRow(QPushButton):
    """A sidebar navigation row: icon chip, label, and a dirty dot."""

    def __init__(self, key: str, label: str, code: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        # A button laid out with child widgets has no useful text sizeHint of its
        # own, so without this the rows collapse and overlap.
        self.setMinimumHeight(t.NAV_CHIP + 16)
        self.setStyleSheet(
            f"NavRow{{text-align:left;padding:0;border-radius:{t.RADIUS_ROW}px;"
            f"border:1px solid transparent;background:transparent;}}"
            f"NavRow:hover{{background:{t.hairline(0.05)};}}"
            f"NavRow:checked{{border-color:{t.gold_border(0.4)};background:{t.gold_tint(0.18)};}}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        layout.addWidget(icon_chip(code))
        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"font-family:{t.UI_FAMILY};font-size:12.5px;font-weight:500;"
            f"color:{t.TEXT_2};background:transparent;"
        )
        layout.addWidget(self._label, 1)
        self._dot = status_dot()
        self._dot.setVisible(False)
        layout.addWidget(self._dot)

    def set_dirty(self, dirty: bool) -> None:
        """Show or hide the gold dot marking staged changes in this section."""
        self._dot.setVisible(dirty)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt override
        super().setChecked(checked)
        # The label is a child widget, so ``NavRow:checked`` can't recolour it.
        self._label.setStyleSheet(
            f"font-family:{t.UI_FAMILY};font-size:12.5px;"
            f"font-weight:{'600' if checked else '500'};"
            f"color:{t.GOLD if checked else t.TEXT_2};background:transparent;"
        )


class TabStrip(QWidget):
    """The per-screen tab strip — 2px gold underline on the active tab."""

    def __init__(self, tabs: tuple[tuple[str, str], ...], parent: QWidget | None = None) -> None:
        """``tabs`` is a tuple of ``(key, label)`` in display order."""
        super().__init__(parent)
        paints_own_background(self)
        self.setStyleSheet(f"TabStrip{{border-bottom:1px solid {t.hairline(0.1)};}}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._keys: dict[QAbstractButton, str] = {}
        self._dots: dict[str, QPushButton] = {}
        for key, label in tabs:
            button = QPushButton(_literal(label))
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                f"QPushButton{{font-family:{t.UI_FAMILY};font-size:12.5px;font-weight:500;"
                f"border:none;border-bottom:2px solid transparent;background:transparent;"
                f"color:{t.TEXT_2};padding:11px 16px;}}"
                f"QPushButton:hover{{color:{t.TEXT};}}"
                f"QPushButton:checked{{border-bottom-color:{t.GOLD};color:{t.GOLD};"
                f"font-weight:600;}}"
            )
            self._group.addButton(button)
            self._keys[button] = key
            self._dots[key] = button
            layout.addWidget(button)
        layout.addStretch(1)
        self._group.buttons()[0].setChecked(True)

    @property
    def changed(self):
        """Signal emitting the clicked tab button (connect and call :meth:`value`)."""
        return self._group.buttonClicked

    def value(self) -> str:
        return self._keys[self._group.checkedButton()]

    def set_value(self, key: str) -> None:
        for button, option in self._keys.items():
            if option == key:
                button.setChecked(True)
                return

    def set_dirty(self, key: str, dirty: bool) -> None:
        """Append the design's ``●`` marker to a tab holding staged changes."""
        button = self._dots.get(key)
        if button is None:
            return
        label = button.text().removesuffix(" ●")
        button.setText(f"{label} ●" if dirty else label)

def apply_tree_palette(tree) -> None:
    """Recolour a tree's selection roles for the active theme.

    A stylesheet paints ``::item`` and ``::branch``, but the style still fills the
    branch column with the palette's Highlight when a row is selected — which
    shows as a stripe of native blue beside our gold row.
    """
    from PySide6.QtGui import QColor, QPalette

    palette = tree.palette()
    palette.setColor(QPalette.ColorRole.Highlight, QColor(t.TREE_HIGHLIGHT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(t.GOLD))
    palette.setColor(QPalette.ColorRole.Base, QColor(t.INSET))
    tree.setPalette(palette)


def prompt_text(parent, title: str, label: str, current: str) -> tuple[str, bool]:
    """Ask for a line of text in a dialog wearing the editor's theme.

    Built rather than taken from ``QInputDialog.getText``: the convenience
    function shows the dialog before a caller can style it, so inside a
    light-themed editor it rendered with the app's dark input field.
    """
    from PySide6.QtWidgets import QDialog, QInputDialog

    dialog = style_dialog(QInputDialog(parent))
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setTextValue(current)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return "", False
    return dialog.textValue(), True


def dialog_qss() -> str:
    """Styling for the plain Qt dialogs the editor reuses.

    The store editor, id picker and property editors were written for the app's
    own palette, so inside this self-themed window their inputs and tables
    rendered dark-on-dark (and, in light mode, would render light-on-light).
    """
    return f"""
QDialog {{ background:{t.APP_BG}; }}
QLabel, QCheckBox, QRadioButton, QGroupBox {{ color:{t.TEXT}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background:{t.INPUT_BG}; color:{t.TEXT};
    border:1px solid {t.hairline(0.22)}; border-radius:5px; padding:4px 6px;
    selection-background-color:{t.gold_tint(0.5)}; selection-color:{t.GOLD};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color:{t.gold_border(0.6)}; }}
QComboBox QAbstractItemView {{
    background:{t.INPUT_BG}; color:{t.TEXT};
    selection-background-color:{t.gold_tint(0.5)}; selection-color:{t.GOLD};
    border:1px solid {t.hairline(0.22)};
}}
QAbstractItemView, QTableView, QTreeView, QListView {{
    background:{t.INSET}; color:{t.TEXT}; alternate-background-color:{t.ALT_ROW};
    selection-background-color:{t.gold_tint(0.5)}; selection-color:{t.GOLD};
    border:1px solid {t.hairline(0.12)}; border-radius:6px;
}}
QHeaderView::section {{
    background:{t.SURFACE}; color:{t.TEXT_2}; border:none;
    border-bottom:1px solid {t.hairline(0.12)}; padding:5px 8px; font-weight:600;
}}
QPushButton {{
    background:transparent; color:{t.TEXT};
    border:1px solid {t.hairline(0.22)}; border-radius:6px; padding:5px 14px;
}}
QPushButton:hover {{ background:{t.hairline(0.08)}; }}
QPushButton:default {{ background:{t.GOLD}; color:{t.GOLD_ON}; border:none; }}
QPushButton:disabled {{ color:{t.TEXT_3}; border-color:{t.hairline(0.1)}; }}
"""


def style_dialog(dialog):
    """Give a reused app dialog the editor's current styling, then return it."""
    dialog.setStyleSheet(dialog_qss() + scrollbar_qss())
    return dialog


#: Widgets taken out of the UI but not yet destroyed. See :func:`retire`.
_RETIRED: list = []


def retire(widget) -> None:
    """Remove a widget from the UI without destroying it mid-event.

    Two Qt facts collide here. ``QLayout.takeAt()`` does not unparent, so a removed
    widget keeps painting at its old geometry — but ``setParent(None)`` hands
    ownership back to Python, and the object is destroyed as soon as the last
    reference goes, which is *immediately*, not at ``deleteLater()`` time.

    A screen rebuild is almost always triggered by one of the widgets it is about
    to tear down (a spin box's ``valueChanged``, an item cell's
    ``mousePressEvent``), so destroying synchronously deletes the widget Qt is
    still delivering an event to and the application crashes. Holding a reference
    until the next turn of the event loop makes ``deleteLater()`` mean what it says.
    """
    widget.hide()
    widget.setParent(None)
    _RETIRED.append(widget)
    if len(_RETIRED) == 1:
        QTimer.singleShot(0, _drop_retired)


def _drop_retired() -> None:
    for widget in _RETIRED:
        widget.deleteLater()
    _RETIRED.clear()


def set_scroll_widget(area, content) -> None:
    """Swap a scroll area's contents, keeping the scroll position.

    Two things ``QScrollArea.setWidget`` gets wrong for a rebuild. It destroys the
    old widget, with the mid-event hazard :func:`retire` exists for. And it resets
    the scrollbars to the top — so editing a field two thirds down the Details tab
    threw the view back to the start, every keystroke.

    The position is restored after the event loop has laid the new widget out:
    setting it immediately does nothing, because the scrollbar's range is still 0
    until the content is measured.
    """
    vertical = area.verticalScrollBar().value()
    horizontal = area.horizontalScrollBar().value()

    previous = area.takeWidget()
    if previous is not None:
        retire(previous)
    area.setWidget(content)

    if vertical or horizontal:
        def _restore() -> None:
            area.verticalScrollBar().setValue(vertical)
            area.horizontalScrollBar().setValue(horizontal)

        QTimer.singleShot(0, _restore)
