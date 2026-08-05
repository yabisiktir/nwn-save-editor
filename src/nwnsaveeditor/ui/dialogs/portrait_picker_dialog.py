"""Pick a portrait by looking at it.

The portrait field used to open the same ID/Name table the feat and spell pickers
use. For a feat that is right — the name *is* the thing. For a portrait it is
useless: ``dw_f_07_`` tells you nothing, and there are 1,594 of them.

Two things make the list navigable, and both come out of ``portraits.2da`` rather
than from us guessing:

* **Only 275 of the 1,594 are humanoid** (``Sex`` 0 or 1). The rest are creatures
  and placeables — a bat, a barrel — which nobody is choosing for a character. So
  the default is the ones that fit this character, with the rest a click away.
* Pictures are loaded **as they are needed**, a page at a time. Decoding every
  humanoid portrait takes about a second and a half, and the whole table far more;
  neither belongs in front of a dialog opening.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nwnfile.look_tables import SEX_FEMALE, SEX_MALE
from nwnfile.portrait_images import art_height
from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w
from nwnsaveeditor.ui.icons import crop_portrait

#: How many portraits to build at once. A page of this many decodes in well under
#: a tenth of a second; the whole humanoid set takes about a second and a half.
PAGE = 60

#: Portraits decoded per turn of the event loop while filling the grid in. Small
#: enough that a turn stays imperceptible, large enough to finish in good time.
FILL_PER_TICK = 12

#: Distinguishes "not decoded yet" from "decoded, and there is no picture".
_UNREAD = object()

#: Cell geometry. A portrait's *picture* is 64x100 — the 64x128 file is padded to
#: a power of two, and :func:`crop_portrait` trims that off — so the cell reserves
#: the height of the art, not of the file.
_THUMB_W = 64
_THUMB_H = art_height(_THUMB_W, 128)


class PortraitPickerDialog(QDialog):
    """Choose a portrait from a grid of the actual pictures."""

    def __init__(
        self, entries, source, *, current: str = "", female: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._entries = list(entries)
        self._source = source
        self._current = current or ""
        self._chosen = self._current
        self._female = female
        self._filter = ""
        self._who = "fits"
        self._shown = PAGE
        #: resref -> QPixmap or None, decoded at most once each.
        self._pixmaps: dict[str, object] = {}
        #: Cells still waiting for their picture, and which grid they belong to.
        self._pending: list[tuple[QLabel, str]] = []
        #: resref -> (cell, name label), so the highlight can move without a rebuild.
        self._cells: dict[str, tuple[QWidget, QLabel]] = {}
        self._generation = 0
        self._filling = QTimer(self)
        self._filling.setInterval(0)  # between events, so the window stays alive
        self._filling.timeout.connect(self._fill_some)
        self.setWindowTitle("Choose a Portrait")
        self.resize(760, 640)

        layout = QVBoxLayout(self)
        layout.addWidget(w.heading("Choose a Portrait"))

        row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by name…")
        self._search.textChanged.connect(self._set_filter)
        row.addWidget(self._search, 1)
        self._who_control = w.SegmentedControl((
            ("fits", "Fits this character"),
            ("male", "Male"),
            ("female", "Female"),
            ("all", "Everything"),
        ))
        self._who_control.set_value(self._who)
        self._who_control.changed.connect(self._set_who)
        row.addWidget(self._who_control)
        layout.addLayout(row)

        self._count = w.cap_label("")
        layout.addWidget(self._count)

        # One scroll area for the life of the dialog, and a search box that is
        # never rebuilt — filtering rebuilds the grid on every keystroke, and a
        # box rebuilt with it would be destroyed under the user's hands.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setStyleSheet(w.scroll_area_qss())
        layout.addWidget(self._scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._render()

    # -- what to show ------------------------------------------------------ #
    def visible_entries(self) -> list:
        """The entries the current filter and audience leave."""
        wanted = self._filter.strip().lower()
        out = []
        for entry in self._entries:
            if wanted and wanted not in entry.resref.lower():
                continue
            if not self._passes_who(entry):
                continue
            out.append(entry)
        return out

    def _passes_who(self, entry) -> bool:
        if self._who == "all":
            return True
        if self._who == "male":
            return entry.sex == SEX_MALE
        if self._who == "female":
            return entry.sex == SEX_FEMALE
        # "fits": this character's own sex, and never a bat or a barrel.
        return entry.sex == (SEX_FEMALE if self._female else SEX_MALE)

    def _set_filter(self, text: str) -> None:
        self._filter = text
        self._shown = PAGE
        self._render()

    def _set_who(self, *_a) -> None:
        self._who = self._who_control.value()
        self._shown = PAGE
        self._render()

    def _show_more(self) -> None:
        self._shown += PAGE
        self._render()

    def _show_all(self, total: int) -> None:
        self._shown = total
        self._render()

    # -- filling the pictures in ------------------------------------------- #
    def _queue_picture(self, label, resref: str) -> None:
        """Show this cell's portrait now if it is known, or line it up to be read.

        Building the cells is free — 1,594 of them take 0.04s — but decoding their
        pictures takes about three and a half seconds, so **Show all** would freeze
        the window for as long if it did the work up front. Instead the grid appears
        at once and fills in behind, a few per turn of the event loop.
        """
        cached = self._pixmaps.get(resref, _UNREAD)
        if cached is not _UNREAD:
            self._apply(label, cached)
            return
        self._pending.append((label, resref))
        if not self._filling.isActive():
            self._filling.start(0)

    def _fill_some(self) -> None:
        """Decode a few queued portraits, preferring the ones being looked at."""
        generation = self._generation
        done = 0
        while self._pending and done < FILL_PER_TICK:
            index = self._next_to_fill()
            label, resref = self._pending.pop(index)
            pixmap = self._pixmaps.setdefault(resref, self._read(resref))
            if generation != self._generation:
                return  # the grid was rebuilt under us; those labels are gone
            self._apply(label, pixmap)
            done += 1
        if not self._pending:
            self._filling.stop()

    def _next_to_fill(self) -> int:
        """The queued cell worth doing first — one that is actually on screen.

        Without this, scrolling to the bottom of "everything" means waiting for the
        fill to walk there from the top.
        """
        for index, (label, _resref) in enumerate(self._pending[:200]):
            try:
                if not label.visibleRegion().isEmpty():
                    return index
            except RuntimeError:  # the label was deleted by a rebuild
                return index
        return 0

    def _apply(self, label, pixmap) -> None:
        try:
            if pixmap is None:
                label.setText("no\nimage")
                label.setStyleSheet(
                    f"color:{t.TEXT_3};font-family:{t.UI_FAMILY};font-size:10px;"
                    f"border:1px dashed {t.hairline(0.16)};border-radius:4px;"
                )
            else:
                label.setPixmap(pixmap)
        except RuntimeError:
            pass  # rebuilt away mid-flight; the new cell will ask again

    # -- the grid ---------------------------------------------------------- #
    def _render(self) -> None:
        visible = self.visible_entries()
        # The chosen portrait is always reachable, even when the filter excludes
        # it — otherwise OK would confirm something not on screen.
        shown = visible[: self._shown]
        if self._chosen and all(e.resref != self._chosen for e in shown):
            extra = next((e for e in self._entries if e.resref == self._chosen), None)
            if extra is not None:
                shown = [extra, *shown]

        self._count.setText(
            f"{len(visible)} portrait(s)"
            + (f" — showing {len(shown)}" if len(shown) < len(visible) else "")
        )

        # Anything queued or tracked belongs to the grid about to be thrown away.
        self._generation += 1
        self._pending.clear()
        self._cells.clear()

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        grid = QGridLayout(body)
        grid.setSpacing(10)
        grid.setContentsMargins(0, 0, 6, 0)
        columns = 7
        if not shown:
            grid.addWidget(w.body("No portrait matches that.", t.TEXT_3, 12), 0, 0)
        for index, entry in enumerate(shown):
            grid.addWidget(self._cell(entry), index // columns, index % columns)
        if len(visible) > self._shown:
            row = QHBoxLayout()
            more = w.ghost_button(f"Show {min(PAGE, len(visible) - self._shown)} more")
            more.clicked.connect(self._show_more)
            row.addWidget(more)
            # 1,594 portraits sixty at a time is twenty-six clicks. The pictures
            # fill in behind, so this costs a rebuild rather than a freeze.
            total = len(visible)
            rest = w.ghost_button(f"Show all {total}")
            rest.setToolTip("Build every remaining cell now; the pictures fill in")
            rest.clicked.connect(lambda _=False, n=total: self._show_all(n))
            row.addWidget(rest)
            row.addStretch(1)
            holder = QWidget()
            holder.setStyleSheet("background:transparent;")
            holder.setLayout(row)
            grid.addWidget(holder, len(shown) // columns + 1, 0, 1, columns)
        grid.setRowStretch(grid.rowCount(), 1)
        w.set_scroll_widget(self._scroll, body)

    def _cell(self, entry) -> QWidget:
        cell = QWidget()
        cell.setFixedSize(_THUMB_W + 12, _THUMB_H + 30)
        cell.setCursor(Qt.CursorShape.PointingHandCursor)
        column = QVBoxLayout(cell)
        column.setContentsMargins(5, 5, 5, 4)
        column.setSpacing(3)

        picture = QLabel()
        picture.setFixedSize(_THUMB_W, _THUMB_H)
        picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._queue_picture(picture, entry.resref)
        column.addWidget(picture, 0, Qt.AlignmentFlag.AlignHCenter)

        name = w.body(entry.resref.rstrip("_"), t.TEXT_2, 9.5)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setToolTip(entry.resref)
        column.addWidget(name)
        self._cells[entry.resref] = (cell, name)
        self._style_cell(entry.resref, entry.resref == self._chosen)

        cell.mousePressEvent = _left_click(lambda r=entry.resref: self._choose(r))
        cell.mouseDoubleClickEvent = _left_click(
            lambda r=entry.resref: self._choose_and_accept(r)
        )
        return cell

    def _read(self, resref: str):
        """Decode one portrait. Called once per resref — the result is cached.

        Without the cache every click re-decoded the whole grid, because choosing
        rebuilds it: a fifth of a second per click at sixty cells, and two seconds
        once everything is shown.
        """
        from nwnfile.formats.tga_reader import TGAReader

        try:
            raw = self._source.image_bytes(resref)
        except Exception:  # noqa: BLE001 — a portrait that cannot be read has none
            return None
        image = TGAReader().read_bytes(raw) if raw else None
        if image is None:
            return None
        rgba = image.to_rgba()
        qimage = QImage(
            bytes(rgba), image.width, image.height, QImage.Format.Format_RGBA8888
        )
        return crop_portrait(QPixmap.fromImage(qimage)).scaled(
            _THUMB_W, _THUMB_H,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    # -- choosing ---------------------------------------------------------- #
    def _style_cell(self, resref: str, selected: bool) -> None:
        entry = self._cells.get(resref)
        if entry is None:
            return
        cell, name = entry
        try:
            cell.setStyleSheet(
                f"background:{t.gold_tint(0.18) if selected else 'transparent'};"
                f"border:1px solid {t.GOLD if selected else t.hairline(0.12)};"
                f"border-radius:6px;"
            )
            name.setStyleSheet(
                name.styleSheet().rsplit("color:", 1)[0]
                + f"color:{t.GOLD if selected else t.TEXT_2};"
            )
        except RuntimeError:
            self._cells.pop(resref, None)  # rebuilt away

    def _choose(self, resref: str) -> None:
        """Move the highlight, without rebuilding the grid to do it.

        Selecting used to re-render, which at sixty cells cost a fifth of a second
        and with everything shown nearly a whole one — every click. Only two cells
        actually change.
        """
        previous, self._chosen = self._chosen, resref
        if previous == resref:
            return
        self._style_cell(previous, False)
        self._style_cell(resref, True)

    def _choose_and_accept(self, resref: str) -> None:
        self._chosen = resref
        self.accept()

    def selected_resref(self) -> str:
        """The chosen portrait's base resref (``""`` if nothing is chosen)."""
        return self._chosen


def _left_click(action):
    """A mouse handler that fires only on the left button."""

    def handler(event):
        if event.button() == Qt.MouseButton.LeftButton:
            action()

    return handler
