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
    QGridLayout,
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
        intro = w.cap_label(
            "These items' art isn't in the module you're playing, so they show "
            "default pictures. Pick what to do with each.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        bulk = QHBoxLayout()
        bulk.addWidget(w.cap_label("Set all:"))
        for label, choice in (("Keep", self.KEEP), ("Closest match", self.MATCH),
                              ("Extract", self.EXTRACT)):
            b = w.ghost_button(label)
            b.clicked.connect(lambda _=False, c=choice: self._set_all(c))
            bulk.addWidget(b)
        bulk.addStretch(1)
        layout.addLayout(bulk)

        # A frozen header outside the scroll so the column labels stay in view.
        # Its columns are configured identically to the body's, and a right margin
        # equal to the scrollbar width keeps the two in step despite it.
        top = Qt.AlignmentFlag.AlignTop
        centre = Qt.AlignmentFlag.AlignHCenter | top
        header_holder = QWidget()
        w.own_style(header_holder, "background:transparent;")
        header = QGridLayout(header_holder)
        header.setContentsMargins(0, 0, self._scrollbar_width(), 0)
        header.setHorizontalSpacing(12)
        self._config_columns(header)
        for col, text in enumerate(
                ("Item", "Original", "In-game now", "Closest", "Choice")):
            header.addWidget(w.cap_label(text), 0, col,
                             top if col in (0, 4) else centre)
        layout.addWidget(header_holder)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(w.scroll_area_qss())
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        body = QWidget()
        # The scroll body must be transparent so the dialog's own dark/light
        # background shows through — an unstyled viewport falls back to the OS
        # palette and washes the text out (see CLAUDE.md theming rule 4).
        w.own_style(body, "background:transparent;")
        grid = QGridLayout(body)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self._config_columns(grid)
        for r, (item_path, report) in enumerate(entries):
            self._add_row(grid, r, item_path, report)
        grid.setRowStretch(len(entries), 1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _config_columns(grid: QGridLayout) -> None:
        """Identical column sizing for the header and the body grids so they align:
        stretchy name/choice columns, fixed-width centred thumbnail columns."""
        grid.setColumnStretch(0, 3)
        for c in (1, 2, 3):
            grid.setColumnMinimumWidth(c, _THUMB + 16)
        grid.setColumnStretch(4, 5)

    def _scrollbar_width(self) -> int:
        from PySide6.QtWidgets import QStyle

        return self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent) or 14

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

    def _add_row(self, grid: QGridLayout, r: int, item_path: tuple, report) -> None:
        top = Qt.AlignmentFlag.AlignTop
        centre = Qt.AlignmentFlag.AlignHCenter | top
        name = QLabel(f"{report.resref}\n({report.slot})")
        name.setWordWrap(True)
        grid.addWidget(name, r, 0, top)
        grid.addWidget(self._thumb(report.original_image), r, 1, centre)
        grid.addWidget(self._thumb(report.current_image), r, 2, centre)
        grid.addWidget(self._thumb(report.match_image), r, 3, centre)

        choices = QWidget()
        w.own_style(choices, "background:transparent;")
        box = QVBoxLayout(choices)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        group = QButtonGroup(choices)
        keep = QRadioButton("Keep original (looks right only where its haks load)")
        group.addButton(keep, 0)
        box.addWidget(keep)
        has_match = report.match_number is not None
        if has_match:
            pct = int((report.match_score or 0) * 100)
            match = QRadioButton(f"Closest match ({pct}% similar)")
            group.addButton(match, 1)
            box.addWidget(match)
        can_extract = report.extract is not None
        if can_extract:
            n = len(report.extract.copies)
            extract = QRadioButton(
                f"Extract original art → override (true look everywhere, {n} file"
                f"{'' if n == 1 else 's'})")
            group.addButton(extract, 2)
            box.addWidget(extract)
        # Default to the highest-fidelity option available.
        default_id = 2 if can_extract else (1 if has_match else 0)
        button = group.button(default_id)
        if button is not None:
            button.setChecked(True)
        grid.addWidget(choices, r, 4)
        self._groups.append((item_path, report, group))

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
