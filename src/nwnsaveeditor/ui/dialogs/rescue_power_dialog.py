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

**The rescue runs inside this dialog.** When the host passes ``compile_power`` and
``finalize`` callbacks, clicking *Rescue selected* does not close the window — it
swaps the wizard body for a per-power progress list (each row ○→⏳→✓/✗) and then
shows the outcome in place with a *Close* button. The slow step is compiling a
Tier-2 branch (``nwnsc``); driving it per power here, with a repaint between each,
replaces the old "dialog closes, window freezes, a message box appears" gap.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w

#: (glyph, colour-token-name) for each step state in the progress list.
_STEP_STATES = {
    "pending": ("○", "TEXT_3"),
    "running": ("⏳", "GOLD"),
    "ok": ("✓", "GREEN"),
    "fail": ("✗", "DANGER"),
}


class RescuePowerDialog(QDialog):
    """List orphaned item powers, let the user rescue the auto-rescuable ones, and
    run the rescue inline with per-power progress.

    ``compile_power(tag) -> (ok, detail, ported_match | None)`` ports one Tier-2
    pick (the slow ``nwnsc`` step); ``finalize(chosen, failures) -> (ok, title,
    body)`` bundles the ready powers into the save and returns the outcome text.
    Both are supplied by the host window; without them the dialog just closes on
    *Rescue selected* (the old behaviour, used by selection-only tests)."""

    def __init__(self, orphans, matches, *, tagbased: bool, can_compile: bool = False,
                 compile_power: Callable | None = None,
                 finalize: Callable | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rescue item powers")
        self.setStyleSheet(w.dialog_qss())  # wear the editor's theme, not the OS palette
        self.setMinimumWidth(540)
        self._can_compile = can_compile
        self._matches = matches
        self._compile_power = compile_power
        self._finalize = finalize
        self._applying = False  # guards close/reject while the rescue is running
        self._checks: dict[str, QCheckBox] = {}          # tier-1: copy a standalone script
        self._compile_checks: dict[str, QCheckBox] = {}  # tier-2: compile a dispatcher branch

        self._layout = layout = QVBoxLayout(self)
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

        self._scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(w.scroll_area_qss())  # transparent viewport → dialog bg shows
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Rescue selected")
        # With host callbacks, OK runs the rescue in place (below) instead of closing.
        if self._finalize is not None:
            self._buttons.accepted.connect(self._start_apply)
        else:
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
            if self._can_compile:
                box.addWidget(self._note(
                    f"The behaviour is a branch inside “{match.dispatcher}” "
                    f"(in “{match.origin}”). It can be ported by compiling it into a "
                    "tag-script:"))
                check = QCheckBox("Compile & bundle this power (experimental)")
                check.setChecked(tagbased)
                check.setEnabled(tagbased)
                check.toggled.connect(self._refresh_ok)
                self._compile_checks[match.tag] = check
                box.addWidget(check)
            else:
                box.addWidget(self._note(
                    f"The behaviour is a branch inside “{match.dispatcher}” "
                    f"(in “{match.origin}”). It can’t be copied as-is — it needs a "
                    "compiled port, but no NWScript compiler was found. Source shown "
                    "for reference:"))
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
        checked = (any(c.isChecked() for c in self._checks.values())
                   or any(c.isChecked() for c in self._compile_checks.values()))
        ok.setEnabled(checked)

    # ----------------------------------------------------------------- apply --
    def _start_apply(self) -> None:
        """Run the rescue in place: swap the wizard for a live progress list, work
        one power at a time (repainting between each so the current one is visible),
        then show the outcome with a Close button. See the module docstring."""
        copy_tags = self.selected_tags()
        compile_tags = self.selected_compile_tags()
        if not copy_tags and not compile_tags:
            return
        self._applying = True
        self._scroll.hide()
        self._buttons.hide()

        panel = QWidget()
        w.own_style(panel, "background:transparent;")
        col = QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        col.addWidget(w.body("Rescuing selected powers…", t.TEXT, 13))
        rows: dict[tuple, QLabel] = {}
        for tag in compile_tags:
            rows[("compile", tag)] = self._step_row(col, f"Compiling “{tag}”…")
        for tag in copy_tags:
            rows[("copy", tag)] = self._step_row(col, f"Bundling “{tag}”")
        rows[("finalize",)] = self._step_row(col, "Adding the scripts to the save…")
        self._layout.addWidget(panel, 1)
        QApplication.processEvents()

        chosen = [self._matches[tag] for tag in copy_tags]
        for tag in copy_tags:  # copies are instant — no compile needed
            self._set_step(rows[("copy", tag)], "ok")
        failures: list[str] = []
        for tag in compile_tags:
            glyph = rows[("compile", tag)]
            self._set_step(glyph, "running")
            QApplication.processEvents()  # paint the ⏳ before the compile starts
            # Compiling shells out to nwnsc (seconds); run it off the GUI thread so
            # the window stays responsive instead of freezing on each power.
            ok, detail, ported = w.run_blocking(lambda tag=tag: self._compile_power(tag))
            if ported is not None:
                chosen.append(ported)
                self._set_step(glyph, "ok")
            else:
                failures.append(f"{tag}: {detail}")
                self._set_step(glyph, "fail")
            QApplication.processEvents()

        final = rows[("finalize",)]
        self._set_step(final, "running")
        QApplication.processEvents()
        ok, title, body = self._finalize(chosen, failures)
        self._set_step(final, "ok" if ok else "fail")
        self._show_result(col, title, body, ok)
        self._applying = False

    def _step_row(self, col: QVBoxLayout, label: str) -> QLabel:
        """A progress line: a status glyph + its label. Returns the glyph to update."""
        row = QWidget()
        w.own_style(row, "background:transparent;")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        glyph = QLabel()
        glyph.setFixedWidth(16)
        line.addWidget(glyph)
        line.addWidget(w.body(label, t.TEXT, 12.5), 1)
        col.addWidget(row)
        self._set_step(glyph, "pending")
        return glyph

    @staticmethod
    def _set_step(glyph: QLabel, state: str) -> None:
        char, token = _STEP_STATES[state]
        glyph.setText(char)
        w.own_style(
            glyph, f"font-size:13px;color:{getattr(t, token)};background:transparent;")

    def _show_result(self, col: QVBoxLayout, title: str, body: str, ok: bool) -> None:
        col.addWidget(w.hline())
        col.addWidget(w.body(title, t.GREEN if ok else t.DANGER, 13))
        detail = w.body(body, t.TEXT, 12)
        detail.setWordWrap(True)
        col.addWidget(detail)
        close = w.gold_button("Close")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)
        col.addLayout(buttons)
        col.addStretch(1)

    def reject(self) -> None:  # noqa: D102 — block Esc/Cancel mid-rescue
        if self._applying:
            return
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: D102, N802 — block the ✕ mid-rescue
        if self._applying:
            event.ignore()
            return
        super().closeEvent(event)

    def selected_tags(self) -> list[str]:
        """Tags of the auto-rescuable (Tier-1, copy) powers the user ticked."""
        return [tag for tag, check in self._checks.items() if check.isChecked()]

    def selected_compile_tags(self) -> list[str]:
        """Tags of the Tier-2 powers the user chose to compile-and-bundle."""
        return [tag for tag, check in self._compile_checks.items() if check.isChecked()]
