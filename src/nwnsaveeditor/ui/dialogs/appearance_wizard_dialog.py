"""The appearance-reconcile wizard.

For gear whose custom art the current module lacks (a CEP2/Aielund character
played under CEP3 Swordflight, say), it shows each broken item three ways —
Original (what it should look like), In this module (what you see now), and the
proposed Closest match — and lets the user choose per item:

* **Keep original** — change nothing;
* **Closest match** — re-point at the nearest appearance the module already has;
* **Extract original** — copy the true icon into a free slot in ``override`` so it
  renders everywhere.

The dialog is static — building a row never rebuilds another — so it steers clear
of the "widget rebuilt under the user" trap. It collects choices only; the caller
applies them through :mod:`nwnsaveeditor.appearance_fix`.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nwnsaveeditor.appearance_fix import Decision
from nwnsaveeditor.ui.editor import widgets as w
from nwnsaveeditor.ui.icons import _pixmap

_THUMB = 48


class AppearanceWizardDialog(QDialog):
    KEEP, MATCH, EXTRACT = "keep", "match", "extract"

    def __init__(self, entries: list[tuple[tuple, object]], parent: QWidget | None = None):
        """``entries`` is ``[(item_path, ItemReport), …]`` for the broken items."""
        super().__init__(parent)
        self._entries = entries
        self._groups: list[tuple[tuple, object, QButtonGroup]] = []
        self.setWindowTitle("Fix Item Appearances")
        self.setStyleSheet(w.dialog_qss())
        self.resize(680, 560)

        layout = QVBoxLayout(self)
        layout.addWidget(w.heading("Fix Item Appearances"))
        layout.addWidget(w.cap_label(
            "These items use art this module doesn't have, so they show default "
            "pictures. Choose what to do with each — Extract keeps the true look in "
            "every module by copying it into your override folder."))

        bulk = QHBoxLayout()
        bulk.addWidget(w.cap_label("Set all:"))
        for label, choice in (("Keep", self.KEEP), ("Closest match", self.MATCH),
                              ("Extract", self.EXTRACT)):
            b = w.ghost_button(label)
            b.clicked.connect(lambda _=False, c=choice: self._set_all(c))
            bulk.addWidget(b)
        bulk.addStretch(1)
        layout.addLayout(bulk)

        header = QHBoxLayout()
        for text, stretch in (("Item", 3), ("Original", 1), ("In-game now", 1),
                              ("Closest", 1), ("Choice", 3)):
            lbl = w.cap_label(text)
            header.addWidget(lbl, stretch)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(w.scroll_area_qss())
        body = QWidget()
        # The scroll body must be transparent so the dialog's own dark/light
        # background shows through — an unstyled viewport falls back to the OS
        # palette and washes the text out (see CLAUDE.md theming rule 4).
        w.own_style(body, "background:transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(6)
        for item_path, report in entries:
            body_layout.addWidget(self._row(item_path, report))
        body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _thumb(self, image) -> QLabel:
        lbl = QLabel()
        lbl.setFixedSize(_THUMB, _THUMB)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = _pixmap(image) if image is not None else None
        if pixmap is not None:
            lbl.setPixmap(pixmap.scaled(
                _THUMB, _THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            lbl.setText("—")
        return lbl

    def _row(self, item_path: tuple, report) -> QFrame:
        frame = QFrame()
        w.own_style(frame, "background:transparent;")
        row = QHBoxLayout(frame)
        name = QLabel(f"{report.resref}\n({report.slot})")
        row.addWidget(name, 3)
        row.addWidget(self._thumb(report.original_image), 1)
        row.addWidget(self._thumb(report.current_image), 1)
        row.addWidget(self._thumb(report.match_image), 1)

        choices = QVBoxLayout()
        group = QButtonGroup(frame)
        keep = QRadioButton("Keep original (looks right only where its haks load)")
        group.addButton(keep, 0)
        choices.addWidget(keep)
        has_match = report.match_number is not None
        if has_match:
            pct = int((report.match_score or 0) * 100)
            match = QRadioButton(f"Closest match ({pct}% similar)")
            group.addButton(match, 1)
            choices.addWidget(match)
        can_extract = report.extract is not None
        if can_extract:
            n = len(report.extract.copies)
            extract = QRadioButton(
                f"Extract original art → override (true look everywhere, {n} file"
                f"{'' if n == 1 else 's'})")
            group.addButton(extract, 2)
            choices.addWidget(extract)
        # Default to the highest-fidelity option available.
        default_id = 2 if can_extract else (1 if has_match else 0)
        button = group.button(default_id)
        if button is not None:
            button.setChecked(True)
        row.addLayout(choices, 3)
        self._groups.append((item_path, report, group))
        return frame

    def _set_all(self, choice: str) -> None:
        """Bulk-set every row to a choice, where that choice is available."""
        target_id = {self.KEEP: 0, self.MATCH: 1, self.EXTRACT: 2}[choice]
        for _path, _report, group in self._groups:
            button = group.button(target_id)
            if button is not None:
                button.setChecked(True)

    def decisions(self) -> list[Decision]:
        """One :class:`Decision` per row, from the selected radio buttons."""
        choice_by_id = {0: self.KEEP, 1: self.MATCH, 2: self.EXTRACT}
        out = []
        for item_path, report, group in self._groups:
            choice = choice_by_id.get(group.checkedId(), self.KEEP)
            out.append(Decision(item_path, report, choice))
        return out
