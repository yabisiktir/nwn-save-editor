"""The Quests & World State screen.

**Variables** is the real half: a module keeps its persistent script state in
``module.ifo``'s ``VarTable`` — the flags and counters a campaign uses to remember
what has happened — and those are listed, searchable and editable here.

**Journal** is not. A quest journal lives in a ``.jrl`` resource, and no save
examined for this project contains one: a ``.sav`` holds only ``are``/``git``/
``fac``/``ifo`` plus an embedded SQLite blob. Rather than show an empty tab that
looks broken, the tab says what is missing and where the journal actually lives.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w
from nwnsaveeditor.world_state import matches

#: How many variable rows to build at once. A module can hold hundreds — the
#: owner's carries 821 — and building every row costs real time, so the list pages.
PAGE = 300


class QuestsScreen(QWidget):
    """The Quests & World State section."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._filter = ""
        self._shown = PAGE
        self.setStyleSheet(f"background:{t.APP_BG};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(14)
        outer.addWidget(w.heading("Quests & World State"))

        outer.addWidget(w.body(
            "A save carries the module's persistent script state but not the quest "
            "journal — there is no .jrl resource in a .sav, so journal entries can "
            "only be read in-game.",
            t.TEXT_3, 11.5,
        ))

        self._pages = QStackedWidget()
        self._pages.setStyleSheet("background:transparent;")
        self._variables_page = QWidget()
        self._variables_page.setStyleSheet("background:transparent;")
        self._variables_layout = QVBoxLayout(self._variables_page)
        self._variables_layout.setContentsMargins(0, 0, 0, 0)
        self._variables_layout.setSpacing(10)
        self._pages.addWidget(self._variables_page)
        outer.addWidget(self._pages, 1)

        # One scroll area for the life of the screen: rebuilding it would throw
        # the view back to the top on every edit and every "Show more".
        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._list_scroll.setStyleSheet(w.scroll_area_qss())

        self.refresh()

    # -- data --------------------------------------------------------------- #
    def _variables(self) -> list:
        try:
            return self._window.session().module_variables()
        except Exception:
            return []

    def _pending_keys(self) -> set:
        session = self._window._session
        changes = session.pending_changes() if session is not None else []
        return {c.key for c in changes if c.kind == "variable"}

    # -- rebuilding --------------------------------------------------------- #
    def refresh(self) -> None:
        self._variables_layout.removeWidget(self._list_scroll)
        self._list_scroll.setParent(None)  # kept alive by self, not by the layout
        _clear(self._variables_layout)
        variables = self._variables()
        if not variables:
            self._variables_layout.addWidget(w.body(
                "This module keeps no persistent variables.", t.TEXT_2, 13
            ))
            self._variables_layout.addStretch(1)
            self._show_tab()
            return

        visible = [v for v in variables if matches(v, self._filter)]
        header = QHBoxLayout()
        header.addWidget(w.cap_label(
            f"Module variables — {len(visible)} of {len(variables)}"
        ))
        header.addStretch(1)
        self._variables_layout.addLayout(header)

        search = QLineEdit()
        search.setPlaceholderText("Search by name or value…")
        search.setText(self._filter)
        search.setStyleSheet(
            f"QLineEdit{{background:{t.INPUT_BG};border:1px solid {t.hairline(0.18)};"
            f"border-radius:5px;color:{t.TEXT};font-family:{t.UI_FAMILY};"
            f"font-size:12px;padding:6px 9px;}}"
        )
        search.textChanged.connect(self._set_filter)
        self._variables_layout.addWidget(search)

        pending = self._pending_keys()
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(0)
        for variable in visible[: self._shown]:
            column.addWidget(self._row(variable, variable.index in pending))
        if len(visible) > self._shown:
            buttons = QHBoxLayout()
            more = w.ghost_button(f"Show {min(PAGE, len(visible) - self._shown)} more")
            more.clicked.connect(self._show_more)
            buttons.addWidget(more)
            total = len(visible)
            rest = w.ghost_button(f"Show all {total}")
            rest.setToolTip("Build every remaining row at once")
            rest.clicked.connect(lambda _=False, n=total: self._show_all(n))
            buttons.addWidget(rest)
            buttons.addStretch(1)
            holder = QWidget()
            holder.setStyleSheet("background:transparent;")
            holder.setLayout(buttons)
            column.addWidget(holder)
        column.addStretch(1)
        w.set_scroll_widget(self._list_scroll, body)
        self._variables_layout.addWidget(self._list_scroll, 1)
        self._show_tab()

    def _row(self, variable, dirty: bool) -> QWidget:
        row = QWidget()
        row.setStyleSheet(
            f"background:{t.gold_tint(0.12) if dirty else 'transparent'};"
            f"border-bottom:1px solid {t.hairline(0.06)};"
        )
        line = QHBoxLayout(row)
        line.setContentsMargins(10, 6, 10, 6)
        line.setSpacing(10)
        if dirty:
            line.addWidget(w.status_dot())
        line.addWidget(w.mono(variable.name, t.GOLD if dirty else t.TEXT, 11.5), 1)
        line.addWidget(w.body(variable.type_name, t.TEXT_3, 11))
        line.addWidget(w.mono(str(variable.value)[:48], t.TEXT_2, 11.5))
        if not variable.editable:
            locked = w.body("read-only", t.TEXT_3, 10.5)
            locked.setToolTip(variable.why_locked)
            line.addWidget(locked)
        elif self._window.editing:
            edit = w.small_ghost("Edit…")
            edit.clicked.connect(lambda _=False, v=variable: self._edit(v))
            line.addWidget(edit)
        return row

    # -- actions ------------------------------------------------------------ #
    def _show_tab(self) -> None:
        self._pages.setCurrentIndex(0)

    def _set_filter(self, text: str) -> None:
        self._filter = text
        self._shown = PAGE
        self.refresh()

    def _show_more(self) -> None:
        self._shown += PAGE
        self.refresh()

    def _show_all(self, total: int) -> None:
        self._shown = total
        self.refresh()

    def _edit(self, variable) -> None:
        from nwnsaveeditor.ui.dialogs.property_edit_dialog import PropertyEditDialog

        if isinstance(variable.value, str):
            text, ok = w.prompt_text(self, "Edit Variable", variable.name,
                                     str(variable.value))
            if not ok:
                return
            new_value = text
        else:
            dialog = w.style_dialog(PropertyEditDialog(
                variable.name, f"{variable.type_name}:", int(variable.value),
                minimum=-2_147_483_648, maximum=2_147_483_647,
                title="Edit Value", parent=self,
            ))
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            new_value = dialog.value()

        try:
            self._window.session().set_variable(
                variable.index, new_value, where=variable.name
            )
        except Exception as exc:
            QMessageBox.critical(self, "Edit failed", str(exc))
            return
        self._window.notify_changed()


def _scroll(body: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setStyleSheet(w.scroll_area_qss())
    area.setWidget(body)
    return area


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            w.retire(widget)
        elif item.layout() is not None:
            _clear(item.layout())
