"""The Party & Campaign screen.

Module-level settings that govern the party — the henchmen cap, party control and
XP scale — are read from ``module.ifo`` and editable.

The campaign side is reported rather than edited. A ``.sav`` carries an embedded
SQLite database (resource type 2077, magic ``SQL3``) holding whatever the campaign
persisted; on the owner's save it is 82 bytes, i.e. effectively empty. Vaultkeeper
does not open it: writing into a database whose schema belongs to the module's own
scripts is a good way to corrupt a campaign, and the byte-faithful ERF path has no
reason to touch it.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.ui.save_editor import tokens as t
from vaultkeeper.ui.save_editor import widgets as w

#: The NWN resource type of the campaign database embedded in a save.
CAMPAIGN_DB_RESTYPE = 2077


class PartyScreen(QWidget):
    """The Party & Campaign section."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self.setStyleSheet(f"background:{t.APP_BG};")
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(26, 22, 26, 22)
        self._outer.setSpacing(14)
        self.refresh()

    # -- data --------------------------------------------------------------- #
    def _fields(self) -> list:
        try:
            return self._window.session().module_fields()
        except Exception:
            return []

    def _pending_keys(self) -> set:
        session = self._window._session
        changes = session.pending_changes() if session is not None else []
        return {c.key for c in changes if c.kind == "module-field"}

    def _campaign_db(self):
        """``(present, size)`` for the save's embedded campaign database."""
        from vaultkeeper.core.formats.erf_reader import ErfReader

        save = self._window.save
        if save is None or save.sav_path is None:
            return False, 0
        try:
            reader = ErfReader()
            for res in reader.list_resources(save.sav_path):
                if res.res_type == CAMPAIGN_DB_RESTYPE:
                    return True, res.size
        except Exception:
            return False, 0
        return False, 0

    # -- rebuilding --------------------------------------------------------- #
    def refresh(self) -> None:
        _clear(self._outer)
        self._outer.addWidget(w.heading("Party & Campaign"))

        fields = self._fields()
        self._outer.addWidget(w.cap_label("Module settings"))
        if not fields:
            self._outer.addWidget(w.body(
                "This module records none of the party settings Vaultkeeper edits.",
                t.TEXT_3, 12.5,
            ))
        else:
            pending = self._pending_keys()
            panel = w.Panel(padding=0)
            panel.body_layout().setSpacing(0)
            for field in fields:
                panel.body_layout().addWidget(self._row(field, field.field in pending))
            self._outer.addWidget(panel)
            self._outer.addWidget(w.body(
                "Party control decides whether the player may take direct control "
                "of henchmen; the henchmen cap is how many may follow at once.",
                t.TEXT_3, 11.5,
            ))

        self._outer.addWidget(w.cap_label("Campaign database"))
        present, size = self._campaign_db()
        if present:
            self._outer.addWidget(w.body(
                f"This save carries an embedded campaign database of "
                f"{size:,} bytes (SQLite).",
                t.TEXT_2, 12.5,
            ))
            self._outer.addWidget(w.body(
                "Vaultkeeper reads and rewrites it byte for byte but never opens "
                "it: its tables belong to the module's own scripts, and editing a "
                "schema we do not own is a reliable way to break a campaign.",
                t.TEXT_3, 11.5,
            ))
        else:
            self._outer.addWidget(w.body(
                "This save carries no campaign database.", t.TEXT_3, 12.5
            ))
        self._outer.addStretch(1)

    def _row(self, field, dirty: bool) -> QWidget:
        row = QWidget()
        row.setStyleSheet(
            f"background:{t.gold_tint(0.12) if dirty else 'transparent'};"
            f"border-bottom:1px solid {t.hairline(0.06)};"
        )
        line = QHBoxLayout(row)
        line.setContentsMargins(14, 9, 14, 9)
        line.setSpacing(10)
        if dirty:
            line.addWidget(w.status_dot())
        line.addWidget(w.body(field.display, t.GOLD if dirty else t.TEXT, 12.5), 1)
        line.addWidget(w.mono(str(field.value), t.TEXT_2, 12))
        if self._window.editing:
            edit = w.small_ghost("Edit…")
            edit.clicked.connect(lambda _=False, f=field: self._edit(f))
            line.addWidget(edit)
        return row

    def _edit(self, field) -> None:
        from vaultkeeper.ui.dialogs.property_edit_dialog import PropertyEditDialog

        dialog = PropertyEditDialog(
            field.display, f"{field.display}:", int(field.value),
            minimum=field.minimum, maximum=field.maximum, parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._window.session().set_module_field(
                field.field, dialog.value(), where=field.display
            )
        except Exception as exc:
            QMessageBox.critical(self, "Edit failed", str(exc))
            return
        self._window.notify_changed()


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())
