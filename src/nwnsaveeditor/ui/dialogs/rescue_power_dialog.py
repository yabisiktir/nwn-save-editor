"""Review and rescue orphaned scripted item powers.

Shows each item whose "Unique Power"/"Activate Item" property has no script in
this save, with what a search of the installed modules/haks turned up:

* **Tier 1** — a standalone compiled script was found: offer a ticked checkbox to
  bundle it (and any missing scripts it calls) into a per-save hak;
* **Tier 1 (source only)** / **Tier 2 (dispatcher branch)** — the behaviour exists
  but can't be copied as-is; shown read-only with the source for reference, not
  auto-applied (that needs recompilation — a later phase);
* **not found** — nothing in the installed content.

Only Tier-1 matches are selectable; ``selected_tags`` returns the ticked ones. If
the target module doesn't run tag-based item scripts, nothing can be rescued and
the dialog says so. Themed like the other reused dialogs (``dialog_qss`` + a
transparent scroll viewport) so it reads in both light and dark.
"""
from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w


class RescuePowerDialog(QDialog):
    """List orphaned item powers and let the user rescue the auto-rescuable ones."""

    def __init__(self, orphans, matches, *, tagbased: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rescue item powers")
        self.setStyleSheet(w.dialog_qss())  # wear the editor's theme, not the OS palette
        self.setMinimumWidth(540)
        self._checks: dict[str, QCheckBox] = {}

        layout = QVBoxLayout(self)
        intro = w.body(
            "These items carry a scripted special power (a “Unique Power” / "
            "“Activate Item” property) whose script isn’t in this save, so the "
            "power does nothing here. Where the script was found in your installed "
            "modules or haks, it can be bundled into a per-save hak so the power "
            "works — the original save is never touched.", t.TEXT, 12.5)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        if not tagbased:
            warn = w.body(
                "⚠ This save’s module does not run tag-based item scripts, so a "
                "rescued script would never fire. Nothing can be rescued here.",
                t.DANGER, 12)
            warn.setWordWrap(True)
            layout.addWidget(warn)

        body = QWidget()
        w.own_style(body, "background:transparent;")
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        seen: set[str] = set()
        for orphan in orphans:
            if orphan.tag in seen:
                continue
            seen.add(orphan.tag)
            col.addWidget(self._entry(orphan, matches.get(orphan.tag), tagbased))
        col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(w.scroll_area_qss())  # transparent viewport → dialog bg shows
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Rescue selected")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._refresh_ok()

    def _entry(self, orphan, match, tagbased: bool) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        w.own_style(
            frame, f"QFrame{{border:1px solid {t.hairline(0.12)};border-radius:6px;}}")
        box = QVBoxLayout(frame)

        title = w.body(
            f"{orphan.item_name.strip() or '(item)'}  —  {orphan.label}", t.TEXT, 13)
        title.setWordWrap(True)
        box.addWidget(title)

        if match is not None and match.auto_rescuable:
            n = len(match.scripts)
            check = QCheckBox(
                f"Rescue from “{match.origin}” ({n} script{'s' if n != 1 else ''})")
            check.setChecked(tagbased)
            check.setEnabled(tagbased)
            check.toggled.connect(self._refresh_ok)
            self._checks[orphan.tag] = check
            box.addWidget(check)
        elif match is not None and match.needs_compile:
            box.addWidget(self._note(
                f"Only the script source was found in “{match.origin}”. It needs "
                "compiling before it can be bundled — not yet automated."))
        elif match is not None and match.tier == 2:
            box.addWidget(self._note(
                f"The behaviour is a branch inside “{match.dispatcher}” "
                f"(in “{match.origin}”). It can’t be copied as-is — it needs a "
                "compiled port. Source shown for reference:"))
            box.addWidget(self._preview(match.branch_source))
        else:
            box.addWidget(self._note(
                "No script for this power was found in your installed modules or "
                "haks. Nothing to rescue."))
        return frame

    @staticmethod
    def _note(text: str):
        label = w.body(text, t.TEXT_3, 11.5)
        label.setWordWrap(True)
        return label

    @staticmethod
    def _preview(source: str) -> QTextEdit:
        edit = QTextEdit()
        edit.setReadOnly(True)
        edit.setPlainText(source or "(source unavailable)")
        edit.setFixedHeight(150)
        edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        return edit

    def _refresh_ok(self) -> None:
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(any(c.isChecked() for c in self._checks.values()))

    def selected_tags(self) -> list[str]:
        """Tags of the auto-rescuable powers the user ticked."""
        return [tag for tag, check in self._checks.items() if check.isChecked()]
