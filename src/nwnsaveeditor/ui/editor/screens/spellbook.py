"""The Spellbook screen — known and memorized spells per caster class and level.

Caster class along the top, spell level below it, then the list for that level with
per-row removal and the same searchable ID + Name picker the Feats tab uses.

A class's lists split into ``Known`` (what a spontaneous caster can cast) and
``Memorized`` (what a prepared caster has slotted); a class can have both, so each
is shown as its own group with its own count rather than merged.

PRC prestige spellbooks are badged and warn before staging: PRC routes their
casting through its own scripts and rebuilds them, so an edit may not stick.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.ui.save_editor import tokens as t
from vaultkeeper.ui.save_editor import widgets as w


class SpellbookScreen(QWidget):
    """The Spellbook section."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._class_index: int | None = None
        self._level: int | None = None
        self._filter = ""
        self.setStyleSheet(f"background:{t.APP_BG};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(16)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setStyleSheet(w.scroll_area_qss())
        outer.addWidget(self._scroll, 1)
        self.refresh()

    # -- data -------------------------------------------------------------- #
    def _book(self) -> list:
        try:
            return self._window.session().player_spellbook()
        except Exception:
            return []

    def _pending_spell_keys(self) -> set:
        """Staged spell changes as ``(class_index, list_field, spell_id)``.

        The session keys these as ``(class_index, list_field, verb, spell_id)``;
        the verb is dropped here because a removed spell is already gone from the
        list, so only additions have a row to mark.
        """
        return {
            (key[0], key[1], key[3])
            for key in (c.key for c in self._pending() if c.kind == "spell")
            if len(key) == 4
        }

    def _pending(self):
        session = self._window._session
        return session.pending_changes() if session is not None else []

    # -- rebuilding -------------------------------------------------------- #
    def refresh(self) -> None:
        book = self._book()
        content = QWidget()
        content.setStyleSheet("background:transparent;")
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 8, 0)
        column.setSpacing(16)

        if not book:
            column.addWidget(w.heading("Spellbook"))
            column.addWidget(w.body(
                "This character has no caster class with a spellbook.", t.TEXT_2, 13
            ))
            column.addStretch(1)
            w.set_scroll_widget(self._scroll, content)
            return

        chosen = next(
            (c for c in book if c.class_index == self._class_index), book[0]
        )
        self._class_index = chosen.class_index
        column.addWidget(self._class_row(book, chosen))

        levels = sorted({sl.level for sl in chosen.lists})
        if self._level not in levels:
            self._level = levels[0] if levels else None
        if self._level is not None:
            column.addWidget(self._level_row(chosen, levels))

        lists = [sl for sl in chosen.lists if sl.level == self._level]
        for spell_list in lists:
            column.addWidget(self._list_block(chosen, spell_list))
        if not lists:
            column.addWidget(w.body("Nothing at this level.", t.TEXT_3, 12.5))
        column.addStretch(1)
        w.set_scroll_widget(self._scroll, content)

    def _class_row(self, book: list, chosen) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(w.cap_label("Caster class"))
        row = QHBoxLayout()
        row.setSpacing(8)
        for spellbook in book:
            button = w.pill_toggle(spellbook.class_name)
            button.setChecked(spellbook.class_index == chosen.class_index)
            button.clicked.connect(
                lambda _=False, i=spellbook.class_index: self._choose_class(i)
            )
            row.addWidget(button)
            if not spellbook.is_base:
                row.addWidget(w.prc_badge())
        row.addStretch(1)
        column.addLayout(row)
        if not chosen.is_base:
            column.addWidget(w.body(
                "This is a PRC prestige spellbook. PRC rebuilds it from its own "
                "data, so an edit here may not stick in-game.",
                t.PRC_AMBER, 12,
            ))
        return holder

    def _level_row(self, chosen, levels: list[int]) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(w.cap_label("Spell level"))
        row = QHBoxLayout()
        row.setSpacing(6)
        for level in levels:
            count = sum(
                len(sl.spells) for sl in chosen.lists if sl.level == level
            )
            button = w.pill_toggle(f"L{level}  ({count})")
            button.setChecked(level == self._level)
            button.clicked.connect(lambda _=False, v=level: self._choose_level(v))
            row.addWidget(button)
        row.addStretch(1)
        column.addLayout(row)
        return holder

    def _list_block(self, chosen, spell_list) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(w.cap_label(
            f"{spell_list.kind} — level {spell_list.level} ({len(spell_list.spells)})"
        ))
        header.addStretch(1)
        if self._window.editing:
            add = w.small_ghost("+ Add a spell…")
            add.clicked.connect(lambda _=False, sl=spell_list: self._add_spell(chosen, sl))
            header.addWidget(add)
        column.addLayout(header)

        if not spell_list.spells:
            column.addWidget(w.body(
                "No spells prepared at this level.", t.TEXT_3, 12.5
            ))
            return holder

        search = QLineEdit()
        search.setPlaceholderText("Filter by name or id…")
        search.setText(self._filter)
        search.setStyleSheet(_input_qss())
        rows: list[tuple[str, QWidget]] = []
        search.textChanged.connect(
            lambda text, r=rows: self._apply_filter(text, r)
        )
        column.addWidget(search)

        pending = self._pending_spell_keys()
        panel = w.Panel(padding=0)
        panel.body_layout().setSpacing(0)
        for spell_id, name in sorted(spell_list.spells, key=lambda p: p[1].lower()):
            key = (chosen.class_index, spell_list.list_field, spell_id)
            row = self._spell_row(chosen, spell_list, spell_id, name, key in pending)
            rows.append((f"{name.lower()} {spell_id}", row))
            panel.body_layout().addWidget(row)
        column.addWidget(panel)
        self._apply_filter(self._filter, rows)
        return holder

    def _spell_row(self, chosen, spell_list, spell_id: int, name: str, dirty: bool) -> QWidget:
        row = QWidget()
        row.setStyleSheet(
            f"background:{t.gold_tint(0.12) if dirty else 'transparent'};"
            f"border-bottom:1px solid {t.hairline(0.06)};"
        )
        line = QHBoxLayout(row)
        line.setContentsMargins(14, 7, 14, 7)
        line.setSpacing(10)
        if dirty:
            line.addWidget(w.status_dot())
        line.addWidget(w.body(name, t.GOLD if dirty else t.TEXT, 13), 1)
        line.addWidget(w.mono(str(spell_id), t.TEXT_3, 11))
        if self._window.editing:
            remove = w.small_ghost("×")
            remove.setToolTip(f"Remove {name}")
            remove.clicked.connect(
                lambda _=False, s=spell_id: self._remove_spell(chosen, spell_list, s)
            )
            line.addWidget(remove)
        return row

    @staticmethod
    def _apply_filter(text: str, rows: list[tuple[str, QWidget]]) -> None:
        needle = text.strip().lower()
        for haystack, row in rows:
            row.setVisible(needle in haystack)

    # -- actions ----------------------------------------------------------- #
    def _choose_class(self, class_index: int) -> None:
        self._class_index = class_index
        self._level = None
        self.refresh()

    def _choose_level(self, level: int) -> None:
        self._level = level
        self.refresh()

    def _add_spell(self, chosen, spell_list) -> None:
        from vaultkeeper.game.character_reference import default_reference
        from vaultkeeper.ui.dialogs.id_picker_dialog import IdPickerDialog

        if not chosen.is_base and not _confirm_prc(self, chosen.class_name):
            return
        dialog = w.style_dialog(IdPickerDialog(
            f"Add a Spell — {chosen.class_name} level {spell_list.level}",
            default_reference().all_spell_ids(), value_header="Spell", parent=self,
        ))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        spell_id = dialog.selected_id()
        if spell_id is None:
            return
        self._window.session().add_spell(
            chosen.class_index, spell_list.list_field, spell_id
        )
        self._window.notify_changed()

    def _remove_spell(self, chosen, spell_list, spell_id: int) -> None:
        if not chosen.is_base and not _confirm_prc(self, chosen.class_name):
            return
        self._window.session().remove_spell(
            chosen.class_index, spell_list.list_field, spell_id
        )
        self._window.notify_changed()


def _input_qss() -> str:
    """The search field's chrome, rebuilt per call so it follows the theme."""
    return (
        f"QLineEdit{{background:{t.INPUT_BG};border:1px solid {t.hairline(0.18)};"
        f"border-radius:5px;color:{t.TEXT};font-family:{t.UI_FAMILY};font-size:12px;"
        f"padding:5px 8px;}}"
        f"QLineEdit:focus{{border-color:{t.gold_border(0.5)};}}"
    )


def _confirm_prc(parent, class_name: str) -> bool:
    from PySide6.QtWidgets import QMessageBox

    answer = QMessageBox.warning(
        parent, "PRC spellbook",
        f"{class_name} is a PRC class. PRC routes its casting through its own "
        f"scripts and rebuilds the spellbook, so this edit may not stick in-game."
        f"\n\nStage it anyway?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes
