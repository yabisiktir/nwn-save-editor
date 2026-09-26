"""Review and restore properties a player item lost versus its blueprint.

One panel per stripped item (see :mod:`nwnsaveeditor.stripped_items`): where its
blueprint came from, then a checkbox per missing property. Powers start ticked;
restrictions and drawbacks (use limitations, penalties) start **unticked** — a
player often removes those on purpose to use an item, and re-adding one can stop
the character equipping it. Nothing is written here: ``selected()`` returns the
picks and the host stages them as ordinary, individually undoable property adds.

Properties this save's item rules (``itemprops.2da``) forbid on the item's base type
are marked ⚠ — the game strips them on load — and one checkbox offers the item-rules
fix (``rules_fix()``; see :mod:`nwnsaveeditor.item_rules`). Items that lost nothing
but carry such properties are listed too (``blueprint is None``).

Themed like the other dialogs (``dialog_qss`` + a transparent scroll viewport).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nwnfile.item_properties import ItemProperty, default_property_names, describe_property
from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w


def property_label(p, tables=None, names=None) -> str:
    """A readable name for a :class:`~nwnsaveeditor.stripped_items.PropFields`."""
    prop = ItemProperty(p.property_name, p.subtype, p.cost_table, p.cost_value,
                        p.param1, p.param1_value)
    return describe_property(prop, names or default_property_names(), tables=tables)


class RestoreItemsDialog(QDialog):
    """List stripped items and let the user pick which lost properties to restore."""

    def __init__(self, stripped, *, tables=None, rules=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Restore stripped items")
        self.setStyleSheet(w.dialog_qss())  # wear the editor's theme, not the OS palette
        self.setMinimumWidth(540)
        self._checks: list[tuple[object, object, QCheckBox]] = []  # (entry, prop, box)
        names = default_property_names()

        layout = QVBoxLayout(self)
        intro = w.body(
            "These items have lost magical properties (fewer than the blueprint they "
            "were made from in your installed modules), or carry properties the game "
            "will remove when this save loads. Tick what to put back; each becomes a "
            "normal pending change you can undo or discard, and nothing is written "
            "until you save.", t.TEXT, 12.5)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        body = QWidget()
        w.own_style(body, "background:transparent;")
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        for entry in stripped:
            col.addWidget(self._panel(entry, tables, names))
        col.addStretch(1)

        self._rules_check: QCheckBox | None = None
        blocked_kinds = sorted({rules.base_item_label(e.item.base_item)
                                for e in stripped if e.blocked}) if rules else []

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(w.scroll_area_qss())  # transparent viewport → dialog bg shows
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        if blocked_kinds:
            kinds = ", ".join(blocked_kinds)
            self._rules_check = QCheckBox(
                f"Keep them when the game loads: let a {kinds} carry these properties "
                "in this save")
            self._rules_check.setChecked(True)
            self._rules_check.toggled.connect(self._refresh_ok)
            layout.addWidget(self._rules_check)
            why = w.body(
                "Adds a small hak to the top of this save’s hak list holding the item "
                "rules table (itemprops.2da) this save already uses, with only those "
                "cells switched on. Without it the game strips the ⚠ properties again "
                "the moment the save loads.", t.TEXT_2, 11.5)
            why.setWordWrap(True)
            layout.addWidget(why)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._refresh_ok()

    def _panel(self, entry, tables, names) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        w.own_style(
            frame, f"QFrame{{border:1px solid {t.hairline(0.12)};border-radius:6px;}}")
        box = QVBoxLayout(frame)
        item = entry.item
        name = item.name or item.tag or "(item)"
        if entry.blueprint is not None:
            head = f"{name}  —  has {len(item.props)} of {len(entry.blueprint.props)} properties"
        else:
            head = f"{name}  —  {len(entry.blocked)} properties will be removed on load"
        title = w.body(head, t.TEXT, 13)
        title.setWordWrap(True)
        box.addWidget(title)
        if entry.blueprint is not None:
            source = f"Blueprint “{entry.blueprint.resref}” from {entry.blueprint.origin}."
            if entry.alternatives:
                others = ", ".join(a.origin for a in entry.alternatives)
                source += (f" Other versions exist ({others}); this one matches the "
                           "item’s description or needs the fewest additions.")
            note = w.body(source, t.TEXT_2, 11.5)
            note.setWordWrap(True)
            box.addWidget(note)
        if entry.blocked:
            listed = "" if entry.missing else ": " + ", ".join(
                property_label(p, tables, names) for p in entry.blocked)
            warn = w.body(
                f"⚠ This save’s item rules don’t allow {len(entry.blocked)} of its "
                "properties on this kind of item, so the game removes them when the "
                f"save loads{listed}.", t.DANGER, 11.5)
            warn.setWordWrap(True)
            box.addWidget(warn)

        powers = [p for p in entry.missing if not p.limiting]
        limits = [p for p in entry.missing if p.limiting]
        for prop in powers:
            self._add_check(box, entry, prop, self._label(entry, prop, tables, names), True)
        if limits:
            head = w.body("Restrictions — off by default; re-adding one may stop you "
                          "equipping the item:", t.TEXT_2, 11.5)
            head.setWordWrap(True)
            box.addWidget(head)
            for prop in limits:
                self._add_check(box, entry, prop, self._label(entry, prop, tables, names),
                                False)
        return frame

    @staticmethod
    def _label(entry, prop, tables, names) -> str:
        label = property_label(prop, tables, names)
        return f"{label}  ⚠" if prop in entry.blocked else label

    def _add_check(self, box, entry, prop, label: str, checked: bool) -> None:
        check = QCheckBox(label)
        check.setChecked(checked)
        check.toggled.connect(self._refresh_ok)
        box.addWidget(check)
        self._checks.append((entry, prop, check))

    def _refresh_ok(self, *_args) -> None:
        rules = getattr(self, "_rules_check", None)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            any(c.isChecked() for _e, _p, c in self._checks)
            or bool(rules is not None and rules.isChecked()))

    def rules_fix(self) -> bool:
        """Whether to add the item-rules hak that keeps blocked properties on load."""
        return self._rules_check is not None and self._rules_check.isChecked()

    def selected(self) -> list[tuple[object, list]]:
        """``[(StrippedItem, [PropFields, …]), …]`` for every ticked property,
        grouped per item in display order."""
        out: dict[int, tuple[object, list]] = {}
        for entry, prop, check in self._checks:
            if check.isChecked():
                out.setdefault(id(entry), (entry, []))[1].append(prop)
        return list(out.values())
