"""Edit a localized string (CExoLocString) — an item's name, a description, a name.

A localized string is a StrRef (a line of ``dialog.tlk``, or none) plus the text
stored in the save for each language. The game shows the StrRef's line when there
is one, so replacing a name means writing the text *and* letting go of the StrRef;
the dialog does that for you when you start typing, and you can undo it with the
checkbox. Text you do not touch is handed back exactly as it was read.

:meth:`value` returns the edited :class:`~nwnfile.formats.gff.LocString`; writing it
is the caller's job (:meth:`SaveEditor.set_raw_field`).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from nwnfile.formats.gff import LocString, string_id_label
from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w

#: the string id a new text is filed under when the value holds none: English.
_DEFAULT_STRING_ID = 0
#: a StrRef spin box shows this at -1.
_NO_STRREF = -1
#: a QSpinBox is a signed 32-bit number. Every StrRef a game ships fits (custom
#: talk tables start at 0x01000000); one that does not is shown but left alone.
_MAX_STRREF = 2 ** 31 - 1
_MAX_VISIBLE_LINES = 8


def _displayable(text: str) -> str:
    """``text`` as a Qt widget can show it.

    The file format keeps undecodable bytes as lone surrogates so they survive a
    round trip; a widget cannot hold those, so they show as U+FFFD. Only the
    *display* is changed — see :meth:`LocStringEditDialog.value`.
    """
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


class _TextRow:
    """One substring: its string id, the text as read, and the box editing it."""

    def __init__(self, string_id: int, text: str) -> None:
        self.string_id = string_id
        self.original = text
        self.shown = _displayable(text)
        self.lossy = self.shown != text  # undecodable bytes became U+FFFD in the box
        self.box = QPlainTextEdit()
        self.box.setPlainText(self.shown)
        # What the box holds is not always what it was given ("\r\n" becomes
        # "\n"), so "edited" is measured against this.
        self._baseline = self.box.toPlainText()
        lines = min(max(self.shown.count("\n") + 1, 2), _MAX_VISIBLE_LINES)
        self.box.setFixedHeight(self.box.fontMetrics().lineSpacing() * lines + 16)

    def edited(self) -> bool:
        return self.box.toPlainText() != self._baseline

    def text(self) -> str:
        return self.box.toPlainText() if self.edited() else self.original


class LocStringEditDialog(QDialog):
    """Edit a localized string's StrRef and its per-language texts."""

    def __init__(
        self,
        description: str,
        value: LocString,
        *,
        tlk_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Text")
        self.setStyleSheet(w.dialog_qss())  # wear the editor's theme, not the app palette
        self._original = value
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{description}</b>"))

        form = QFormLayout()
        layout.addLayout(form)
        self._strref = QSpinBox()
        self._strref.setRange(_NO_STRREF, _MAX_STRREF)
        self._strref.setSpecialValueText("None")  # shown at -1
        self._strref.setValue(min(value.strref, _MAX_STRREF))
        self._strref_locked = value.strref > _MAX_STRREF  # editing it would clamp it
        self._strref.setEnabled(not self._strref_locked)
        form.addRow("StrRef:", self._strref)
        if value.strref >= 0:
            shown = f"“{tlk_text}”" if tlk_text else "not found in dialog.tlk"
            form.addRow("dialog.tlk says:", QLabel(shown))

        self._clear = QCheckBox("Use my text instead (clears the StrRef)")
        self._clear.setVisible(value.strref >= 0)
        self._clear.toggled.connect(self._on_clear_toggled)
        self._clear.clicked.connect(self._on_clear_clicked)
        self._auto_cleared = False  # the box was ticked by typing, not by the user
        layout.addWidget(self._clear)

        self._rows = [_TextRow(sid, text) for sid, text in value.substrings]
        if not self._rows:  # a StrRef-only value: typing here adds the first text
            self._rows.append(_TextRow(_DEFAULT_STRING_ID, ""))
        for row in self._rows:
            row.box.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._row_area())

        self._note = QLabel()
        self._note.setWordWrap(True)
        layout.addWidget(self._note)
        self._refresh_note()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(560, min(230 + sum(r.box.maximumHeight() + 34 for r in self._rows), 680))

    def _row_area(self) -> QScrollArea:
        content = QWidget()
        w.own_style(content, f"background:{t.APP_BG};")
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        for row in self._rows:
            column.addWidget(QLabel(string_id_label(row.string_id)))
            column.addWidget(row.box)
            if row.lossy:
                warning = QLabel("Contains bytes that are not valid text; "
                                 "editing this replaces them.")
                warning.setWordWrap(True)
                column.addWidget(warning)
        column.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        # A bare scroll viewport falls back to the OS palette, which on a dark-mode
        # Mac drew the light theme dark-on-dark: make it transparent and have the
        # content paint the theme background itself (as the settings screen does).
        area.setStyleSheet(w.scroll_area_qss())
        w.own_style(area.viewport(), "background:transparent;")
        area.setWidget(content)
        return area

    # -- behaviour ---------------------------------------------------------- #
    def _on_text_changed(self) -> None:
        # Typing over a name that came from dialog.tlk would otherwise be invisible
        # in-game, so the first edit lets go of the StrRef; the checkbox undoes it.
        # Deleting the edit again hands the StrRef back, or it would be lost for nothing.
        if self._original.strref >= 0:
            if self._any_edited() and not self._clear.isChecked():
                self._clear.setChecked(True)
                self._auto_cleared = True
            elif not self._any_edited() and self._auto_cleared:
                self._clear.setChecked(False)
                self._auto_cleared = False
        self._refresh_note()

    def _on_clear_clicked(self) -> None:
        self._auto_cleared = False  # the user has taken over the checkbox

    def _on_clear_toggled(self, cleared: bool) -> None:
        self._strref.setEnabled(not self._strref_locked and not cleared)
        self._strref.setValue(_NO_STRREF if cleared else min(self._original.strref, _MAX_STRREF))

    def _any_edited(self) -> bool:
        return any(row.edited() for row in self._rows)

    def _refresh_note(self) -> None:
        typed = "".join(row.box.toPlainText() for row in self._rows)
        if any(ord(char) > 127 for char in typed):
            self._note.setText("Characters outside plain ASCII are saved as UTF-8; "
                               "check they display correctly in the game.")
        else:
            self._note.setText("")
        self._note.setVisible(bool(self._note.text()))

    # -- result ------------------------------------------------------------- #
    def value(self) -> LocString:
        """The edited value. Untouched text is returned exactly as it was read, so
        opening this on a string and pressing OK changes nothing."""
        substrings = [(row.string_id, row.text()) for row in self._rows]
        if not self._original.substrings and not self._any_edited():
            substrings = []  # a StrRef-only value stays StrRef-only until typed into
        strref = self._strref.value()
        if self._strref_locked and not self._clear.isChecked():
            strref = self._original.strref  # shown clamped; hand back what was read
        return LocString(strref=strref, substrings=substrings)
